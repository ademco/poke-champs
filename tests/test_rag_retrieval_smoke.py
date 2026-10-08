"""Smoke test: real embeddings retrieve the obviously-right chunk.

Not the retrieval evaluation (that's phase 4, with recall/MRR on a labelled
set). This only guards against a broken pipeline: wrong model, mismatched
query/document handling, a bad index. Needs both Postgres and the model, so it
runs in CI (which caches the model) and is skipped where either is missing.
"""

import os

import psycopg
import pytest
from psycopg import sql

from pokechamp.db import database_url
from pokechamp.db.migrate import migrate
from pokechamp.rag.corpus import build_corpus
from pokechamp.rag.index import load, prepare
from pokechamp.rag.search import vector_search

pytestmark = [pytest.mark.db, pytest.mark.model]
TEST_DB = "pokechamp_rag_smoke"

# question -> the document a correct retriever must surface in its top 5
CASES = {
    "What does Intimidate do?": "showdown:ability:intimidate",
    "How do stat points work in Champions?": "notes:stat-points",
    "How long does sleep last?": "notes:status-conditions",
    "Is Terastallization in Pokémon Champions?": "notes:mega-evolution",
    "What does Life Orb do?": "showdown:item:lifeorb",
    "How much damage do spread moves do in doubles?": "notes:doubles-damage-modifiers",
}


@pytest.fixture(scope="module")
def embedder():
    try:
        from pokechamp.rag.embeddings import FastEmbedEmbedder

        return FastEmbedEmbedder()
    except Exception as exc:
        if os.environ.get("REQUIRE_MODEL") == "1":
            raise
        pytest.skip(f"embedding model not available: {type(exc).__name__}")


@pytest.fixture(scope="module")
def conn(embedder):
    try:
        admin = psycopg.connect(database_url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip("Postgres not reachable")
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    url = psycopg.conninfo.make_conninfo(database_url(), dbname=TEST_DB)
    with psycopg.connect(url, autocommit=True) as c:
        migrate(c)
        corpus = build_corpus()
        load(c, corpus, prepare(corpus, embedder), embedder)
        yield c


def test_obvious_questions_find_the_right_document(conn, embedder):
    report, found = [], 0
    for question, expected in CASES.items():
        hits = vector_search(conn, embedder, question, k=5)
        ids = [h.doc_id for h in hits]
        rank = ids.index(expected) + 1 if expected in ids else None
        found += rank is not None
        report.append(f"{'OK ' if rank else 'MISS'} rank={rank} {question!r} -> top: {ids[:3]}")
    print("\n".join(report))  # visible with pytest -s / in CI logs on failure
    # Allow one miss: this is a smoke test, not the metric. Phase 4 measures properly.
    assert found >= len(CASES) - 1, "\n".join(report)
