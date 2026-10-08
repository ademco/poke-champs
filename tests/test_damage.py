"""Damage calculator vs @smogon/calc 0.12.0 (Champions mode), roll for roll.

tests/fixtures/damage_scenarios.json holds the inputs; damage_expected.json
holds @smogon/calc's outputs (tools/calc_fixtures/generate.js, run in Docker).
Every one of the 16 damage rolls must match exactly: off-by-one HP errors are
the kind that flip "2HKO" into "3HKO".
"""

import json
import re
from pathlib import Path

import pytest

from pokechamp.tools.damage import UnsupportedCalculation, calculate_from_spec
from pokechamp.tools.repo import SnapshotFacts

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIOS = json.loads((FIXTURES / "damage_scenarios.json").read_text())["scenarios"]
EXPECTED = json.loads((FIXTURES / "damage_expected.json").read_text())
# Between-hit effects (recovery, recoil, chip) are outside our KO summary by design.
BETWEEN_HIT_EFFECTS = re.compile(r"after|Sitrus|Leftovers|recoil|sand|Life Orb")


@pytest.fixture(scope="module")
def facts():
    return SnapshotFacts()


def test_fixtures_come_from_the_pinned_calc_version():
    assert EXPECTED["meta"]["calc"] == "@smogon/calc@0.12.0"
    assert set(EXPECTED["results"]) == {s["id"] for s in SCENARIOS}


SUPPORTED = [s for s in SCENARIOS if not s.get("expect_unsupported")]


@pytest.mark.parametrize("scenario", SUPPORTED, ids=[s["id"] for s in SUPPORTED])
def test_rolls_match_smogon_calc(facts, scenario):
    expected = EXPECTED["results"][scenario["id"]]
    result = calculate_from_spec(facts, scenario)
    assert result.rolls == expected["rolls"], expected.get("desc")
    if expected["ko"] and not BETWEEN_HIT_EFFECTS.search(expected["ko"]):
        assert result.ko_summary() == expected["ko"]


@pytest.mark.parametrize(
    "scenario", [s for s in SCENARIOS if s.get("expect_unsupported")], ids=lambda s: s["id"]
)
def test_unsupported_mechanics_refuse_instead_of_guessing(facts, scenario):
    with pytest.raises(UnsupportedCalculation):
        calculate_from_spec(facts, scenario)


def test_unknown_inputs_refuse(facts):
    base = {"attacker": {"species": "Garchomp"}, "defender": {"species": "Incineroar"}}
    with pytest.raises(UnsupportedCalculation, match="unknown move"):
        calculate_from_spec(facts, {**base, "move": "Shadow Surge"})
    with pytest.raises(UnsupportedCalculation, match="unknown Pokémon"):
        calculate_from_spec(
            facts, {**base, "attacker": {"species": "Garchompix"}, "move": "Earthquake"}
        )


def test_percentages_and_ko_wording(facts):
    r = calculate_from_spec(facts, SCENARIOS[0])  # Jolly Garchomp EQ vs bulky Incineroar
    assert (r.min_percent, r.max_percent) == (81.1, 96.0)
    assert r.ko_summary() == "guaranteed 2HKO"
