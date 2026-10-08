"""Read-only lookups over the structured facts tables.

These are the building blocks for phase 2's tools. Every function takes the
regulation explicitly (defaulting to the live one) so nothing can accidentally
answer from a stale regulation's rows during a switchover.
"""

import re

import psycopg

from pokechamp.regulations import current_regulation


def to_id(name: str) -> str:
    """Showdown's ID rule: lowercase, keep only a-z and 0-9 ("Mr. Mime" -> "mrmime")."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _reg(regulation: str | None) -> str:
    return regulation or current_regulation().code


def species_row(conn: psycopg.Connection, name: str, regulation: str | None = None):
    """Return (id, name, legal, illegal_reason, battle_only, base_species) or None if unknown."""
    return conn.execute(
        "SELECT id, name, legal, illegal_reason, battle_only, base_species"
        " FROM species WHERE regulation = %s AND id = %s",
        (_reg(regulation), to_id(name)),
    ).fetchone()


def species_legal(conn: psycopg.Connection, name: str, regulation: str | None = None) -> bool:
    row = species_row(conn, name, regulation)
    return bool(row and row[2])


def item_legal(conn: psycopg.Connection, name: str, regulation: str | None = None) -> bool:
    row = conn.execute(
        "SELECT legal FROM items WHERE regulation = %s AND id = %s",
        (_reg(regulation), to_id(name)),
    ).fetchone()
    return bool(row and row[0])


def move_exists(conn: psycopg.Connection, name: str, regulation: str | None = None) -> bool:
    """True if the move exists at all (legal or not). False means 'made up'."""
    row = conn.execute(
        "SELECT 1 FROM moves WHERE regulation = %s AND id = %s",
        (_reg(regulation), to_id(name)),
    ).fetchone()
    return row is not None


def can_learn(
    conn: psycopg.Connection, species: str, move: str, regulation: str | None = None
) -> bool:
    """Can this species learn this move in Champions? Megas use their base form's moves."""
    reg = _reg(regulation)
    row = species_row(conn, species, reg)
    if row is None:
        return False
    learner_id = to_id(row[5]) if row[4] else row[0]  # battle-only -> base species
    hit = conn.execute(
        "SELECT 1 FROM learnsets WHERE regulation = %s AND species_id = %s AND move_id = %s",
        (reg, learner_id, to_id(move)),
    ).fetchone()
    return hit is not None
