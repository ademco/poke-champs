"""Typed view of data/snapshots/showdown_champions.json.

The snapshot is produced by tools/showdown_export (Node, inside Docker) and
committed to git: Showdown is MIT-licensed, and committing the snapshot means
(1) CI and fresh clones need no Node, and (2) each monthly refresh shows up as
a reviewable diff ("Psyshield Bash went 70 -> 90 BP").

Pydantic validates the file on load, so a malformed export fails loudly here
instead of half-loading into Postgres.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "snapshots" / "showdown_champions.json"
)


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Meta(_Row):
    source: str
    source_url: str
    license: str
    showdown_commit: str
    exported_at: datetime
    regulation: str
    mod: str


class Format(_Row):
    id: str
    name: str
    game_type: Literal["doubles", "singles"]
    team_size: int
    picked_team_size: int
    level: int
    sp_total: int
    sp_max_per_stat: int
    item_clause: bool
    species_clause: bool
    banned: list[str]


STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")


class Species(_Row):
    id: str
    name: str
    num: int
    base_species: str
    forme: str | None
    types: list[str]
    base_stats: dict[str, int]
    abilities: dict[str, str]
    weightkg: float
    battle_only: bool
    required_item: str | None
    is_mega: bool
    legal: bool
    illegal_reason: str | None


class Move(_Row):
    id: str
    name: str
    num: int
    type: str
    category: Literal["Physical", "Special", "Status"]
    base_power: int
    accuracy: int | None
    pp: int
    priority: int
    target: str
    flags: list[str]
    short_desc: str | None
    legal: bool
    multihit: list[int] | None
    has_secondary: bool
    recoil: bool
    has_crash_damage: bool
    override_offensive_stat: str | None
    override_defensive_stat: str | None
    ignore_defensive: bool
    will_crit: bool


class Ability(_Row):
    id: str
    name: str
    short_desc: str | None
    legal: bool


class Item(_Row):
    id: str
    name: str
    short_desc: str | None
    mega_stone: dict[str, str] | None
    legal: bool


class Nature(_Row):
    name: str
    plus: str | None
    minus: str | None


class TypeChartEntry(_Row):
    attacking: str
    defending: str
    multiplier: float


class Snapshot(_Row):
    meta: Meta
    formats: list[Format]
    species: list[Species]
    moves: list[Move]
    abilities: list[Ability]
    items: list[Item]
    learnsets: dict[str, list[str]]
    natures: list[Nature]
    type_chart: list[TypeChartEntry]


def load_snapshot(path: Path = SNAPSHOT_PATH) -> Snapshot:
    return Snapshot.model_validate_json(path.read_bytes())
