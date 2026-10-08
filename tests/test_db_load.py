"""Integration tests: migrate + load into a real Postgres.

Uses a separate database (pokechamp_test) created on the fly, so running tests
never touches your dev data. Skipped when no Postgres is reachable; CI runs
them against a Postgres service container.
"""

import os

import psycopg
import pytest
from psycopg import sql

from pokechamp.db import database_url
from pokechamp.db.migrate import migrate
from pokechamp.evals.auto_checks import run_all
from pokechamp.ingest.load_showdown import TABLES, load
from pokechamp.ingest.snapshot import load_snapshot

pytestmark = pytest.mark.db

TEST_DB = "pokechamp_test"


def _admin_url() -> str:
    return database_url()


@pytest.fixture(scope="module")
def conn():
    try:
        admin = psycopg.connect(_admin_url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        # Locally, no DB just means skip. In CI (REQUIRE_DB=1) a silent skip
        # would hide a broken pipeline, so fail instead.
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip("Postgres not reachable (start it with `make db-up`)")
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    url = psycopg.conninfo.make_conninfo(_admin_url(), dbname=TEST_DB)
    with psycopg.connect(url, autocommit=True) as c:
        migrate(c)
        yield c


@pytest.fixture(scope="module")
def snap():
    return load_snapshot()


@pytest.fixture(scope="module")
def loaded(conn, snap):
    return load(conn, snap)


def _counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def test_migrations_are_idempotent(conn):
    assert migrate(conn) == []


def test_row_counts_match_snapshot(conn, snap, loaded):
    counts = _counts(conn)
    assert counts["species"] == len(snap.species)
    assert counts["moves"] == len(snap.moves)
    assert counts["items"] == len(snap.items)
    assert counts["learnsets"] == sum(len(v) for v in snap.learnsets.values())
    assert counts["type_chart"] == 324


def test_every_row_has_provenance(conn, loaded):
    for table in TABLES:
        orphans = conn.execute(
            f"SELECT count(*) FROM {table} t LEFT JOIN ingestion_runs r ON r.id = t.run_id"
            " WHERE r.source IS NULL OR r.license IS NULL OR r.regulation <> t.regulation"
        ).fetchone()[0]
        assert orphans == 0, table


def test_reload_is_idempotent(conn, snap, loaded):
    before = _counts(conn)
    second = load(conn, snap)
    assert _counts(conn) == before
    # All rows now point at the newest run; nothing left over from the first.
    stale = conn.execute("SELECT count(*) FROM species WHERE run_id <> %s", (second,)).fetchone()
    assert stale[0] == 0


def test_failed_load_rolls_back_completely(conn, snap, loaded):
    before = _counts(conn)
    runs_before = conn.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0]
    # A duplicate move id violates the primary key midway through the load.
    broken = snap.model_copy(update={"moves": [*snap.moves, snap.moves[0]]})
    with pytest.raises(psycopg.errors.UniqueViolation):
        load(conn, broken)
    assert _counts(conn) == before
    assert conn.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0] == runs_before


def test_constraints_reject_bad_rows(conn, loaded):
    run_id = conn.execute("SELECT max(id) FROM ingestion_runs").fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
        conn.execute(
            "INSERT INTO learnsets VALUES ('M-C', 'garchomp', 'shadowsurge', %s)", (run_id,)
        )
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("INSERT INTO type_chart VALUES ('M-C', 'Fire', 'Fake', 3, %s)", (run_id,))


def test_golden_set_structured_checks_pass(conn, loaded):
    results = run_all(conn)
    failures = [r for r in results if r.status == "fail"]
    assert failures == []
    assert sum(r.status == "pass" for r in results) >= 10
