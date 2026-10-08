"""Tiny migration runner: applies db/migrations/NNN_*.sql in order, once each.

Same idea as Flyway in Spring Boot: numbered SQL files plus a table recording
which ones ran. We don't need an ORM or Alembic for a handful of plain-SQL
files, and plain SQL is easier to read in an interview.

Usage: python -m pokechamp.db.migrate
"""

from pathlib import Path

import psycopg

from pokechamp.db import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def pending(conn: psycopg.Connection) -> list[Path]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    return [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.stem not in applied]


def migrate(conn: psycopg.Connection) -> list[str]:
    applied = []
    for path in pending(conn):
        # One transaction per file: a broken migration leaves no half-built schema.
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
        applied.append(path.stem)
    return applied


def main() -> None:
    with connect() as conn:
        applied = migrate(conn)
    print(f"applied: {', '.join(applied)}" if applied else "schema up to date")


if __name__ == "__main__":
    main()
