"""Vector store tests against real Postgres + pgvector (hashing embedder, so
no model download). The real-model retrieval smoke test is marked `model`."""

import os

import psycopg
import pytest
from psycopg import sql

from pokechamp.db import database_url
from pokechamp.db.migrate import migrate
from pokechamp.rag.corpus import build_corpus
from pokechamp.rag.embeddings import HashingEmbedder
from pokechamp.rag.index import load, prepare
from pokechamp.rag.search import vector_search

pytestmark = pytest.mark.db
TEST_DB = "pokechamp_rag_test"


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
        yield c


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def indexed(conn, corpus):
    embedder = HashingEmbedder()
    embedded = prepare(corpus, embedder)
    return load(conn, corpus, embedded, embedder), embedder


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_pgvector_and_indexes_exist(conn):
    assert conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    indexes = {
        r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
    }
    assert {"chunks_embedding_hnsw", "chunks_tsv_gin"} <= indexes


def test_load_counts_and_provenance(conn, indexed, corpus):
    counts, _ = indexed
    assert count(conn, "documents") == len(corpus) == counts["documents"]
    assert count(conn, "chunks") == counts["chunks"]
    orphans = conn.execute(
        "SELECT count(*) FROM documents d LEFT JOIN ingestion_runs r ON r.id = d.run_id"
        " WHERE r.license IS NULL OR r.regulation <> d.regulation"
    ).fetchone()[0]
    assert orphans == 0


def test_reindex_is_idempotent(conn, indexed, corpus):
    _, embedder = indexed
    before = (count(conn, "documents"), count(conn, "chunks"))
    load(conn, corpus, prepare(corpus, embedder), embedder)
    assert (count(conn, "documents"), count(conn, "chunks")) == before


def test_wrong_dimension_is_rejected_before_touching_the_db(conn, indexed, corpus):
    class BadEmbedder(HashingEmbedder):
        def embed_documents(self, texts):
            return [[0.0] * 10 for _ in texts]

    before = count(conn, "chunks")
    with pytest.raises(ValueError, match="dimension"):
        prepare(corpus[:3], BadEmbedder())
    assert count(conn, "chunks") == before


def test_search_returns_cited_hits_for_the_live_regulation(conn, indexed):
    _, embedder = indexed
    hits = vector_search(conn, embedder, "sleep shorter in champions misses one or two turns", k=3)
    assert hits[0].doc_id == "notes:status-conditions"
    assert all(h.regulation == "M-C" and h.source and h.ref and h.license for h in hits)


def test_search_filters_by_regulation(conn, indexed):
    _, embedder = indexed
    assert vector_search(conn, embedder, "stat points", k=3, regulation="M-B") == []


def test_tsvector_is_generated_for_keyword_search(conn, indexed):
    hit = conn.execute(
        "SELECT doc_id FROM chunks WHERE tsv @@ plainto_tsquery('english', 'Terastallization')"
    ).fetchall()
    assert ("notes:mega-evolution",) in hit
