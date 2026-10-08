"""Data validation for the committed Showdown snapshot (no database needed).

These run on every PR, so a bad monthly refresh (broken export, Showdown
changing a field) fails CI before it reaches Postgres. Two kinds of checks:
  - invariants that must hold for any correct export (unique ids, valid
    types, every learnset move exists...),
  - anchors: a few facts we verified by hand against Showdown's source.
"""

from collections import Counter

import pytest

from pokechamp.facts import to_id
from pokechamp.ingest.snapshot import STAT_KEYS, load_snapshot
from pokechamp.regulations import current_regulation
from pokechamp.sources import SOURCES

TYPES = {
    "Bug", "Dark", "Dragon", "Electric", "Fairy", "Fighting", "Fire", "Flying", "Ghost",
    "Grass", "Ground", "Ice", "Normal", "Poison", "Psychic", "Rock", "Steel", "Water",
}  # fmt: skip


@pytest.fixture(scope="module")
def snap():
    return load_snapshot()


@pytest.fixture(scope="module")
def species(snap):
    return {s.id: s for s in snap.species}


@pytest.fixture(scope="module")
def moves(snap):
    return {m.id: m for m in snap.moves}


@pytest.fixture(scope="module")
def items(snap):
    return {i.id: i for i in snap.items}


# ── provenance ──────────────────────────────────────────────────────────────


def test_snapshot_is_for_the_live_regulation(snap):
    assert snap.meta.regulation == current_regulation().code


def test_snapshot_source_is_approved_and_licensed(snap):
    src = SOURCES[snap.meta.source]
    assert src.status == "approved"
    assert snap.meta.license == src.license == "MIT"
    assert len(snap.meta.showdown_commit) == 40  # pinned to an exact commit


# ── invariants ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("table", ["species", "moves", "abilities", "items"])
def test_ids_are_unique_and_derived_from_names(snap, table):
    rows = getattr(snap, table)
    dupes = [i for i, n in Counter(r.id for r in rows).items() if n > 1]
    assert dupes == []
    assert [r.name for r in rows if to_id(r.name) != r.id] == []


def test_species_stats_and_types_are_valid(snap):
    for s in snap.species:
        assert set(s.base_stats) == set(STAT_KEYS), s.id
        assert all(1 <= v <= 255 for v in s.base_stats.values()), s.id
        assert 1 <= len(s.types) <= 2 and set(s.types) <= TYPES, s.id


def test_legal_flag_matches_reason(snap):
    for table in ("species",):
        for row in getattr(snap, table):
            assert row.legal == (row.illegal_reason is None), row.id


def test_learnsets_cover_exactly_the_team_legal_species(snap):
    team_legal = {s.id for s in snap.species if s.legal and not s.battle_only}
    assert set(snap.learnsets) == team_legal


def test_learnset_moves_exist_and_are_legal(snap, moves):
    for species_id, move_ids in snap.learnsets.items():
        assert move_ids, f"{species_id} has an empty learnset"
        bad = [m for m in move_ids if m not in moves or not moves[m].legal]
        assert bad == [], f"{species_id}: {bad}"


def test_legal_battle_only_forms_have_legal_bases(snap, species):
    by_name = {s.name: s for s in snap.species}
    for s in snap.species:
        if s.legal and s.battle_only:
            assert by_name[s.base_species].legal or any(
                f.legal and f.base_species == s.base_species and not f.battle_only
                for f in snap.species
            ), s.id


def test_legal_megas_need_a_legal_stone_that_points_back(snap, items):
    for s in snap.species:
        if s.legal and s.is_mega:
            stone = items[to_id(s.required_item)]
            assert stone.legal, s.id
            assert s.name in stone.mega_stone.values(), s.id


def test_type_chart_is_complete(snap):
    pairs = {(t.attacking, t.defending): t.multiplier for t in snap.type_chart}
    assert len(pairs) == 18 * 18
    assert {a for a, _ in pairs} == TYPES
    assert set(pairs.values()) <= {0, 0.5, 1, 2}


def test_natures(snap):
    assert len(snap.natures) == 25
    assert sum(1 for n in snap.natures if n.plus is None) == 5  # neutral natures


def test_champions_pp_cap(snap):
    # The Champions mod caps base PP at 20 (data/mods/champions/scripts.ts init()).
    assert max(m.pp for m in snap.moves) == 20


# ── formats ─────────────────────────────────────────────────────────────────


def test_formats_match_verified_rules(snap):
    by_type = {f.game_type: f for f in snap.formats}
    assert set(by_type) == {"doubles", "singles"}
    assert by_type["doubles"].picked_team_size == 4
    assert by_type["singles"].picked_team_size == 3
    for f in snap.formats:
        assert (f.team_size, f.level, f.sp_total, f.sp_max_per_stat) == (6, 50, 66, 32)
        assert f.item_clause and f.species_clause
        assert {"-tag:mythical", "-tag:restrictedlegendary"} <= set(f.banned)


# ── anchors (verified by hand against Showdown source, 2026-10-08) ─────────


def test_anchor_facts(species, moves, items, snap):
    assert species["incineroar"].legal and species["incineroar"].types == ["Fire", "Dark"]
    assert species["garchompmegaz"].legal and species["garchompmegaz"].types == ["Dragon"]
    assert species["garchompmegaz"].base_stats["spe"] == 151
    assert not species["amoonguss"].legal
    assert "Restricted Legendary" in species["calyrex"].illegal_reason
    assert moves["psyshieldbash"].base_power == 90
    assert not moves["terablast"].legal
    assert not items["choicespecs"].legal and items["lifeorb"].legal
    assert "knockoff" not in snap.learnsets["incineroar"]
    assert "fakeout" in snap.learnsets["incineroar"]


def test_roster_size_is_plausible(snap):
    # 349 regulation entries + 33 cosmetic/battle-only forms of legal species.
    # Not an exact pin: a mid-regulation Showdown fix may nudge it.
    legal = sum(1 for s in snap.species if s.legal)
    assert 340 <= legal <= 420
