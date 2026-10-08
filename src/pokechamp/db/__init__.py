"""Database access: connection helper and schema migrations."""

import os

import psycopg

# Matches docker-compose.yml. Override with DATABASE_URL (e.g. in CI or Cloud Run).
DEFAULT_DATABASE_URL = "postgresql://pokechamp:pokechamp@localhost:5433/pokechamp"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    # autocommit: each `with conn.transaction():` block is a real transaction
    # (not a savepoint inside an implicit one), so all-or-nothing loads behave
    # exactly as written.
    return psycopg.connect(url or database_url(), autocommit=True)
