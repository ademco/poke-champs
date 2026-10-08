"""Structural checks on the golden set.

These don't grade answers (that starts once there is a system to grade). They
keep the exam itself well-formed: balanced, sourced, and consistent with the
regulation and source registries.
"""

from collections import Counter

import pytest

from pokechamp.evals.golden_set import load_golden_set
from pokechamp.regulations import REGULATIONS
from pokechamp.sources import SOURCES


@pytest.fixture(scope="module")
def golden():
    return load_golden_set()


def test_size_is_within_agreed_range(golden):
    assert 25 <= len(golden.cases) <= 40


def test_ids_are_unique(golden):
    counts = Counter(c.id for c in golden.cases)
    assert [i for i, n in counts.items() if n > 1] == []


def test_id_prefix_matches_category(golden):
    prefix = {"mechanics": "mech", "meta": "meta", "team_analysis": "team", "trick": "trick"}
    for case in golden.cases:
        assert case.id.startswith(prefix[case.category] + "-"), case.id


def test_every_category_is_represented(golden):
    counts = Counter(c.category for c in golden.cases)
    # Floors, not exact numbers: the set can grow without editing this test.
    assert counts["mechanics"] >= 8
    assert counts["meta"] >= 5
    assert counts["team_analysis"] >= 6
    assert counts["trick"] >= 8


def test_both_game_types_are_covered(golden):
    game_types = {c.game_type for c in golden.cases}
    assert {"doubles", "singles"} <= game_types


def test_regulations_are_known(golden):
    for case in golden.cases:
        assert case.regulation in REGULATIONS, case.id


def test_sources_are_registered(golden):
    for case in golden.cases:
        for ref in case.sources:
            assert ref.source in SOURCES, f"{case.id}: unknown source {ref.source!r}"


def test_trick_questions_never_expect_a_plain_answer(golden):
    # A trick question's right answer is a correction or a refusal.
    for case in golden.cases:
        if case.category == "trick":
            assert case.expected_behavior in {"correct", "refuse"}, case.id


def test_meta_cases_use_computed_expectations(golden):
    # Usage numbers change monthly, so meta answers must be checked against the
    # usage table at eval time, never against numbers frozen into the YAML.
    for case in golden.cases:
        if case.category == "meta":
            assert any(c.kind == "usage_top" for c in case.auto_checks), case.id
            assert all(c.expected is None for c in case.auto_checks), case.id


def test_most_cases_are_auto_checkable(golden):
    # Our design goal: prefer exact checks against structured data over
    # LLM-judge-only grading. Keep at least 60% auto-checkable.
    checkable = sum(1 for c in golden.cases if c.auto_checks)
    assert checkable / len(golden.cases) >= 0.6
