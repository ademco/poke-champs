"""MVP web app against a real Postgres (facts + hashing-embedder index), fake LLM."""

import os

import psycopg
import pytest
from psycopg import sql

from pokechamp.answer.llm import FakeLLM
from pokechamp.db import database_url
from pokechamp.db.migrate import migrate
from pokechamp.ingest.load_showdown import load as load_facts
from pokechamp.ingest.snapshot import load_snapshot
from pokechamp.rag.corpus import build_corpus
from pokechamp.rag.embeddings import HashingEmbedder
from pokechamp.rag.index import load as load_index
from pokechamp.rag.index import prepare
from pokechamp.web.app import create_app

pytestmark = pytest.mark.db
TEST_DB = "pokechamp_web_test"

TEAM = """Incineroar @ Sitrus Berry
Ability: Intimidate
EVs: 32 HP / 2 Atk / 32 SpD
Careful Nature
- Fake Out
- Flare Blitz

Garchomp @ Garchompite Z
Ability: Rough Skin
EVs: 32 Atk / 2 Def / 32 Spe
Jolly Nature
- Earthquake
- Dragon Claw
"""


@pytest.fixture(scope="module")
def url():
    try:
        admin = psycopg.connect(database_url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip("Postgres not reachable (start it with `make db-up`)")
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    url = psycopg.conninfo.make_conninfo(database_url(), dbname=TEST_DB)
    with psycopg.connect(url, autocommit=True) as c:
        migrate(c)
        load_facts(c, load_snapshot())
        corpus = build_corpus()
        e = HashingEmbedder()
        load_index(c, corpus, prepare(corpus, e), e)
    return url


def reply(system, user):
    return {"status": "answered", "answer": "Sleep lasts one or two turns [S1].",
            "claims": [{"text": "Sleep lasts 1-2 turns.", "source_ids": ["S1"]}],
            "regulation": "M-C"}  # fmt: skip


@pytest.fixture
def client(url):
    def connect():
        return psycopg.connect(url, autocommit=True)

    app = create_app(connect, embedder=HashingEmbedder(), llm=FakeLLM(reply))
    return app.test_client()


def test_page_and_health(client):
    assert b"Analyze a team" in client.get("/").data
    h = client.get("/health").get_json()
    assert h == {"status": "ok", "database": True, "regulation": "M-C", "questions_enabled": True}


def test_analyze_team(client):
    r = client.post("/api/analyze", json={"team": TEAM})
    body = r.get_json()
    assert r.status_code == 200 and body["regulation"] == "M-C"
    # 2 Pokémon: legal sets, but ranked needs 6
    assert [p["code"] for p in body["problems"]] == ["team_too_small:2"]
    chomp = body["members"][1]
    assert chomp["stats"]["spe"] == 169  # matches golden mech-002
    assert chomp["mega"]["name"] == "Garchomp-Mega-Z"
    assert "Speed order" in body["text"]


def test_analyze_rejects_bad_input(client):
    assert client.post("/api/analyze", json={}).status_code == 400
    assert (
        client.post("/api/analyze", json={"team": TEAM, "game_type": "triples"}).status_code == 400
    )


def test_ask_returns_cited_answer(client):
    r = client.post("/api/ask", json={"question": "How long does sleep last?"})
    body = r.get_json()
    assert r.status_code == 200 and body["status"] == "answered"
    assert [s["id"] for s in body["sources"]] == ["S1"] and body["sources"][0]["license"]
    assert body["warnings"] == []


def test_ask_without_key_explains_and_analysis_still_works(url):
    app = create_app(lambda: psycopg.connect(url, autocommit=True), HashingEmbedder(), llm=None)
    c = app.test_client()
    r = c.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.get_json()["error"]
    assert c.get("/health").get_json()["questions_enabled"] is False
    assert c.post("/api/analyze", json={"team": TEAM}).status_code == 200
