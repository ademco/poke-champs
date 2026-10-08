"""Shared helpers for fact lookups. The lookups themselves live in tools/repo.py."""

import re


def to_id(name: str) -> str:
    """Showdown's ID rule: lowercase, keep only a-z and 0-9 ("Mr. Mime" -> "mrmime")."""
    return re.sub(r"[^a-z0-9]", "", name.lower())
