"""The regulation filter must never leak another regulation's text.

During an M-C -> M-D switchover both regulations sit in the same tables. We
simulate that with a poisoned copy of the corpus tagged M-B, whose every chunk
contains a marker word, then check every search mode in both directions.
"""

import dataclasses
import os

import psycopg
import pytest
from psycopg import sql

from pokechamp.db import database_url
from pokechamp.db.migrate import migrate
from pokechamp.rag.corpus import build_corpus
from pokechamp.rag.embeddings import HashingEmbedder
from pokechamp.rag.index import load, prepare
from pokechamp.rag.rerank import OverlapReranker
from pokechamp.rag.search import hybrid_search, keyword_search, reranked_search, vector_search

pytestmark = pytest.mark.db
TEST_DB = "pokechamp_rag_regfilter"
MARKER = "zzleakmarker"


@pytest.fixture(scope="module")
def conn():
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
        embedder = HashingEmbedder()
        live = build_corpus()
        old = [dataclasses.replace(d, regulation="M-B", text=f"{d.text} {MARKER}") for d in live]
        load(c, live, prepare(live, embedder), embedder)
        load(c, old, prepare(old, embedder), embedder)
        yield c


def all_modes(conn, query, regulation):
    e = HashingEmbedder()
    return {
        "vector": vector_search(conn, e, query, 20, regulation),
        "keyword": keyword_search(conn, query, 20, regulation),
        "hybrid": hybrid_search(conn, e, query, 20, regulation),
        "rerank": reranked_search(conn, e, OverlapReranker(), query, 20, regulation),
    }


@pytest.mark.parametrize("query", [MARKER, f"sleep turns {MARKER}", "what does intimidate do"])
def test_live_regulation_never_returns_old_rows(conn, query):
    for mode, hits in all_modes(conn, query, "M-C").items():
        assert hits or (mode == "keyword" and query == MARKER), mode
        assert all(h.regulation == "M-C" and MARKER not in h.text for h in hits), mode


def test_old_regulation_returns_only_its_own_rows(conn):
    for mode, hits in all_modes(conn, f"sleep {MARKER}", "M-B").items():
        assert hits and all(h.regulation == "M-B" for h in hits), mode
