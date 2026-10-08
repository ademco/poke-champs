"""Facts repository: one interface, two backends.

The tools (stats, legality, damage...) only ever talk to `Facts`. In the app,
`DbFacts` answers from Postgres; in fast unit tests, `SnapshotFacts` answers
from the committed JSON snapshot. Same idea as a Spring Data repository: the
business logic doesn't know or care where rows come from.

Lookups take display names or IDs ("Garchomp-Mega-Z" or "garchompmegaz") and
return None when something doesn't exist, so callers can say "not found"
instead of guessing.
"""

from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from pokechamp.facts import to_id
from pokechamp.ingest.snapshot import Snapshot, load_snapshot
from pokechamp.regulations import current_regulation

STATS = ("hp", "atk", "def", "spa", "spd", "spe")


@dataclass(frozen=True)
class SpeciesInfo:
    id: str
    name: str
    base_species: str
    types: tuple[str, ...]
    base_stats: dict[str, int]
    abilities: tuple[str, ...]
    weightkg: float
    battle_only: bool
    required_item: str | None
    is_mega: bool
    legal: bool
    illegal_reason: str | None


@dataclass(frozen=True)
class MoveInfo:
    id: str
    name: str
    type: str
    category: str
    base_power: int
    priority: int
    target: str
    flags: frozenset[str]
    legal: bool
    multihit: tuple[int, ...] | None
    has_secondary: bool
    recoil: bool
    has_crash_damage: bool
    override_offensive_stat: str | None
    override_defensive_stat: str | None
    ignore_defensive: bool
    will_crit: bool


@dataclass(frozen=True)
class ItemInfo:
    id: str
    name: str
    mega_stone: dict[str, str] | None
    legal: bool


@dataclass(frozen=True)
class FormatInfo:
    id: str
    game_type: str
    team_size: int
    picked_team_size: int
    level: int
    sp_total: int
    sp_max_per_stat: int
    item_clause: bool
    species_clause: bool


class Facts(Protocol):
    regulation: str

    def species(self, name: str) -> SpeciesInfo | None: ...
    def move(self, name: str) -> MoveInfo | None: ...
    def item(self, name: str) -> ItemInfo | None: ...
    def ability_exists(self, name: str) -> bool: ...
    def nature(self, name: str) -> tuple[str | None, str | None] | None: ...
    def learnset(self, species_id: str) -> frozenset[str]: ...
    def type_multiplier(self, attacking: str, defending: str) -> float: ...
    def format(self, game_type: str) -> FormatInfo: ...


def _species(d: dict) -> SpeciesInfo:
    return SpeciesInfo(
        id=d["id"],
        name=d["name"],
        base_species=d["base_species"],
        types=tuple(d["types"]),
        base_stats=dict(d["base_stats"]),
        abilities=tuple(d["abilities"].values()),
        weightkg=float(d["weightkg"]),
        battle_only=d["battle_only"],
        required_item=d["required_item"],
        is_mega=d["is_mega"],
        legal=d["legal"],
        illegal_reason=d["illegal_reason"],
    )


def _move(d: dict) -> MoveInfo:
    return MoveInfo(
        id=d["id"],
        name=d["name"],
        type=d["type"],
        category=d["category"],
        base_power=d["base_power"],
        priority=d["priority"],
        target=d["target"],
        flags=frozenset(d["flags"]),
        legal=d["legal"],
        multihit=tuple(d["multihit"]) if d["multihit"] else None,
        has_secondary=d["has_secondary"],
        recoil=d["recoil"],
        has_crash_damage=d["has_crash_damage"],
        override_offensive_stat=d["override_offensive_stat"],
        override_defensive_stat=d["override_defensive_stat"],
        ignore_defensive=d["ignore_defensive"],
        will_crit=d["will_crit"],
    )


def _format(d: dict) -> FormatInfo:
    return FormatInfo(**{k: d[k] for k in FormatInfo.__dataclass_fields__})


class SnapshotFacts:
    """Facts from the committed JSON snapshot. Fast, no database: for unit tests."""

    def __init__(self, snap: Snapshot | None = None):
        self._snap = snap or load_snapshot()
        self.regulation = self._snap.meta.regulation

    @cached_property
    def _species(self) -> dict[str, SpeciesInfo]:
        return {s.id: _species(s.model_dump()) for s in self._snap.species}

    @cached_property
    def _moves(self) -> dict[str, MoveInfo]:
        return {m.id: _move(m.model_dump()) for m in self._snap.moves}

    @cached_property
    def _items(self) -> dict[str, ItemInfo]:
        return {i.id: ItemInfo(i.id, i.name, i.mega_stone, i.legal) for i in self._snap.items}

    @cached_property
    def _types(self) -> dict[tuple[str, str], float]:
        return {(t.attacking, t.defending): t.multiplier for t in self._snap.type_chart}

    def species(self, name: str) -> SpeciesInfo | None:
        return self._species.get(to_id(name))

    def move(self, name: str) -> MoveInfo | None:
        return self._moves.get(to_id(name))

    def item(self, name: str) -> ItemInfo | None:
        return self._items.get(to_id(name))

    def ability_exists(self, name: str) -> bool:
        return any(a.id == to_id(name) for a in self._snap.abilities)

    def nature(self, name: str) -> tuple[str | None, str | None] | None:
        for n in self._snap.natures:
            if to_id(n.name) == to_id(name):
                return (n.plus, n.minus)
        return None

    def learnset(self, species_id: str) -> frozenset[str]:
        return frozenset(self._snap.learnsets.get(species_id, ()))

    def type_multiplier(self, attacking: str, defending: str) -> float:
        return self._types[(attacking, defending)]

    def format(self, game_type: str) -> FormatInfo:
        return next(_format(f.model_dump()) for f in self._snap.formats if f.game_type == game_type)


class DbFacts:
    """Facts from Postgres, scoped to one regulation (the live one by default)."""

    def __init__(self, conn: psycopg.Connection, regulation: str | None = None):
        self._conn = conn
        self.regulation = regulation or current_regulation().code

    def _one(self, query: str, *params):
        cur = self._conn.cursor(row_factory=dict_row)
        return cur.execute(query, (self.regulation, *params)).fetchone()

    def species(self, name: str) -> SpeciesInfo | None:
        row = self._one("SELECT * FROM species WHERE regulation = %s AND id = %s", to_id(name))
        if row is None:
            return None
        row["base_stats"] = {k: row[k] for k in STATS}
        return _species(row)

    def move(self, name: str) -> MoveInfo | None:
        row = self._one("SELECT * FROM moves WHERE regulation = %s AND id = %s", to_id(name))
        return _move(row) if row else None

    def item(self, name: str) -> ItemInfo | None:
        row = self._one("SELECT * FROM items WHERE regulation = %s AND id = %s", to_id(name))
        return ItemInfo(row["id"], row["name"], row["mega_stone"], row["legal"]) if row else None

    def ability_exists(self, name: str) -> bool:
        return bool(
            self._one("SELECT 1 FROM abilities WHERE regulation = %s AND id = %s", to_id(name))
        )

    def nature(self, name: str) -> tuple[str | None, str | None] | None:
        row = self._one(
            "SELECT plus, minus FROM natures WHERE regulation = %s AND lower(name) = %s",
            name.strip().lower(),
        )
        return (row["plus"], row["minus"]) if row else None

    def learnset(self, species_id: str) -> frozenset[str]:
        rows = self._conn.execute(
            "SELECT move_id FROM learnsets WHERE regulation = %s AND species_id = %s",
            (self.regulation, species_id),
        ).fetchall()
        return frozenset(r[0] for r in rows)

    def type_multiplier(self, attacking: str, defending: str) -> float:
        row = self._one(
            "SELECT multiplier FROM type_chart"
            " WHERE regulation = %s AND attacking = %s AND defending = %s",
            attacking,
            defending,
        )
        return float(row["multiplier"])

    def format(self, game_type: str) -> FormatInfo:
        return _format(
            self._one("SELECT * FROM formats WHERE regulation = %s AND game_type = %s", game_type)
        )
