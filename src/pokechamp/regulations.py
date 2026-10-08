"""Known Pokémon Champions regulations and how to pick the current one.

Every record and chunk in this project is tagged with a regulation code, and
retrieval defaults to the current regulation. This module is the single place
that knows which regulation is current, so nothing else hardcodes "M-C".

Dates were verified on 2026-10-08 (see docs/DATA_SOURCES.md). Re-verify when a
new regulation is announced and add it here.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class Regulation:
    code: str
    start: datetime  # inclusive, UTC
    end: datetime | None  # exclusive, UTC; None = not announced yet
    # Showdown format IDs per game type. Used to fetch legality and usage stats.
    showdown_formats: dict[str, str] = field(default_factory=dict)


def _utc(y: int, m: int, d: int, hour: int = 0) -> datetime:
    return datetime(y, m, d, hour, tzinfo=UTC)


REGULATIONS: dict[str, Regulation] = {
    # M-A predates Showdown's per-regulation formats; no format IDs survive.
    "M-A": Regulation("M-A", _utc(2026, 4, 8), _utc(2026, 6, 17)),
    "M-B": Regulation(
        "M-B",
        _utc(2026, 6, 17),
        _utc(2026, 9, 9, 2),
        {"doubles": "gen9championsvgc2026regmb", "singles": "gen9championsbssregmb"},
    ),
    "M-C": Regulation(
        "M-C",
        _utc(2026, 9, 9, 2),
        # Serebii and Vice give 2026-12-02; not yet confirmed on an official page.
        _utc(2026, 12, 2),
        {"doubles": "gen9championsvgc2026regmc", "singles": "gen9championsbssregmc"},
    ),
}

GAME_TYPES = ("doubles", "singles")


def regulation_on(when: datetime) -> Regulation:
    """Return the regulation active at `when` (timezone-aware)."""
    if when.tzinfo is None:
        raise ValueError("pass a timezone-aware datetime to avoid off-by-hours bugs")
    for reg in REGULATIONS.values():
        if reg.start <= when and (reg.end is None or when < reg.end):
            return reg
    # After the last known end date: keep using the newest regulation and let
    # the data-refresh job flag that a new one needs to be added.
    newest = max(REGULATIONS.values(), key=lambda r: r.start)
    if when >= newest.start:
        return newest
    raise LookupError(f"no regulation known for {when.isoformat()} (before Champions launch)")


def current_regulation(now: datetime | None = None) -> Regulation:
    return regulation_on(now or datetime.now(UTC))
