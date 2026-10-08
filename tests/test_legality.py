"""Legality checker: hand-written cases plus agreement with Showdown's own
TeamValidator on 26 teams (tests/fixtures/showdown_validation.json, produced
by tools/showdown_export/validate_teams.js).

The two validators word problems differently, so we compare problem
*categories* per team (e.g. "illegal item", "can't learn"), not message text.
"""

import json
from pathlib import Path

import pytest

from pokechamp.tools.legality import validate_team
from pokechamp.tools.repo import SnapshotFacts
from pokechamp.tools.team_parser import parse_team

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def facts():
    return SnapshotFacts()


def codes(facts, text, **kw):
    return sorted(p.code for p in validate_team(facts, parse_team(text), **kw))


def test_mega_form_written_with_its_stone_is_accepted(facts):
    text = (
        "Garchomp-Mega-Z @ Garchompite Z\nAbility: Levitate\n"
        "EVs: 32 Atk\nJolly Nature\n- Earthquake"
    )
    assert codes(facts, text, ignore_team_size=True) == []


def test_mega_form_without_its_stone_is_rejected(facts):
    text = "Garchomp-Mega-Z @ Life Orb\nAbility: Levitate\nEVs: 32 Atk\nJolly Nature\n- Earthquake"
    assert codes(facts, text, ignore_team_size=True) == ["battle_only_species:Garchomp-Mega-Z"]


def test_illegal_pokemon_reports_one_root_cause_plus_its_item(facts):
    text = "Amoonguss @ Choice Specs\nAbility: Regenerator\n- Spore\n- Rage Powder"
    assert codes(facts, text, ignore_team_size=True) == [
        "item_illegal:Choice Specs",
        "species_illegal:Amoonguss",
    ]


def test_unknown_names_are_not_found_not_guessed(facts):
    text = "Garchompix @ Mega Banana\nAbility: Rough Skin\n- Earthquake"
    assert codes(facts, text, ignore_team_size=True) == [
        "item_not_found:Mega Banana",
        "species_not_found:Garchompix",
    ]


# ── agreement with Showdown's validator ────────────────────────────────────

# Showdown message fragment -> our problem-code prefix.
SHOWDOWN_CATEGORIES = [
    ("must bring at least", "team_too_small"),
    ("may only bring up to", "team_too_large"),
    ("Species Clause", "duplicate_species"),
    ("Item Clause", "duplicate_item"),
    ("nickname", "nickname_too_long"),
    ("is an invalid move", "move_not_found"),
    ("is an invalid item", "item_not_found"),
    ("'s item ", "item_illegal"),
    ("can't learn", "move_not_learnable"),
    ("can't have", "ability_invalid"),
    ("moves, which is more than", "too_many_moves"),
    ("multiple copies of", "duplicate_move"),
    ("IVs are not maxed", "iv_not_31"),
    ("total Stat Points", "sp_total_over_66"),
    ("Stat Points in", "sp_stat_over_32"),
    ("banned by", "species_illegal"),
    ("does not exist", "species_illegal"),  # after the item rule above
]


def showdown_categories(messages: list[str]) -> set[str]:
    cats = set()
    for msg in messages:
        if msg.startswith("("):  # continuation line of the previous message
            continue
        cat = next((c for frag, c in SHOWDOWN_CATEGORIES if frag in msg), None)
        assert cat, f"unmapped Showdown message: {msg}"
        cats.add(cat)
    return cats


TEAMS = json.loads((FIXTURES / "legality_teams.json").read_text())["teams"]
VERDICTS = json.loads((FIXTURES / "showdown_validation.json").read_text())["results"]


@pytest.mark.parametrize("team", TEAMS, ids=[t["id"] for t in TEAMS])
def test_agrees_with_showdown(facts, team):
    ours = validate_team(facts, parse_team(team["text"]), game_type=team["game_type"])
    our_cats = {p.code.split(":")[0] for p in ours}
    theirs = showdown_categories(VERDICTS[team["id"]]["problems"])
    assert our_cats == theirs, [p.message for p in ours]
