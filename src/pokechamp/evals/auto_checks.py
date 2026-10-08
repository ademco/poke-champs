"""Run the golden set's auto-checks against the deterministic tools.

Each check kind maps to a function (facts, args, case_input) -> actual value,
compared with the case's `expected`. Kinds without a function yet are reported
as "pending", so the summary shows how much of the exam the system can already
grade itself.

Usage: python -m pokechamp.evals.auto_checks
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pokechamp.db import connect
from pokechamp.evals.golden_set import GoldenCase, load_golden_set
from pokechamp.tools import damage
from pokechamp.tools.legality import validate_team
from pokechamp.tools.repo import DbFacts, Facts
from pokechamp.tools.speed import compare
from pokechamp.tools.stats import calc_stat
from pokechamp.tools.team_parser import parse_team
from pokechamp.tools.typechart import effectiveness

CheckFn = Callable[[Facts, dict[str, Any], str], Any]


def _species_legal(facts: Facts, a: dict, _: str) -> bool:
    s = facts.species(a["species"])
    return bool(s and s.legal)


def _item_legal(facts: Facts, a: dict, _: str) -> bool:
    i = facts.item(a["item"])
    return bool(i and i.legal)


def _learnset(facts: Facts, a: dict, _: str) -> bool:
    s = facts.species(a["species"])
    m = facts.move(a["move"])
    if not (s and m):
        return False
    learner = facts.species(s.base_species) if s.battle_only else s
    return m.id in facts.learnset(learner.id)


def _stat_of(facts: Facts, spec: dict, stat: str) -> int:
    species = facts.species(spec["species"])
    return calc_stat(stat, species.base_stats[stat], spec["sp"], facts.nature(spec["nature"]))


def _stat(facts: Facts, a: dict, _: str) -> int:
    return _stat_of(facts, a, a["stat"])


def _speed_compare(facts: Facts, a: dict, _: str) -> dict:
    r = compare(
        _stat_of(facts, a["a"], "spe"),
        _stat_of(facts, a["b"], "spe"),
        trick_room=a.get("trick_room", False),
    )
    return {"a": r.a, "b": r.b, "faster": r.faster}


def _weakness_count(facts: Facts, a: dict, case_input: str) -> int:
    members = [facts.species(s.species) for s in parse_team(case_input)]
    return sum(1 for m in members if effectiveness(facts, a["attacking_type"], m.types) > 1)


def _team_legality(facts: Facts, a: dict, case_input: str) -> list[str]:
    problems = validate_team(
        facts,
        parse_team(case_input),
        game_type=a.get("game_type", "doubles"),
        ignore_team_size=a.get("ignore_team_size", False),
    )
    return sorted(p.code for p in problems)


def _damage_range(facts: Facts, a: dict, _: str) -> list[int]:
    return damage.calculate_from_spec(facts, a).rolls


CHECKS: dict[str, CheckFn] = {
    "pokemon_legal": _species_legal,
    "item_legal": _item_legal,
    "move_exists": lambda facts, a, _: facts.move(a["move"]) is not None,
    "learnset": _learnset,
    "stat": _stat,
    "speed_compare": _speed_compare,
    "type_weakness_count": _weakness_count,
    "team_legality": _team_legality,
    "damage_range": _damage_range,
}


@dataclass(frozen=True)
class Result:
    case_id: str
    kind: str
    status: str  # "pass" | "fail" | "pending" (no tool yet) | "dynamic" (expected computed later)
    detail: str = ""


def _normalize(kind: str, value: Any) -> Any:
    return sorted(value) if kind == "team_legality" else value


def run_check(facts: Facts, case: GoldenCase, index: int) -> Result:
    check = case.auto_checks[index]
    fn = CHECKS.get(check.kind)
    if fn is None:
        return Result(case.id, check.kind, "pending")
    if check.expected is None:
        return Result(case.id, check.kind, "dynamic")
    try:
        actual = fn(facts, check.args, case.input)
    except Exception as exc:  # a crashing tool is a failed check, not a crashed eval run
        return Result(case.id, check.kind, "fail", f"{type(exc).__name__}: {exc}")
    if _normalize(check.kind, actual) == _normalize(check.kind, check.expected):
        return Result(case.id, check.kind, "pass")
    return Result(
        case.id, check.kind, "fail", f"args={check.args} expected={check.expected!r} got={actual!r}"
    )


def run_all(facts: Facts) -> list[Result]:
    return [
        run_check(facts, case, i)
        for case in load_golden_set().cases
        for i in range(len(case.auto_checks))
    ]


def main() -> None:
    with connect() as conn:
        results = run_all(DbFacts(conn))
    counts = Counter(r.status for r in results)
    for r in results:
        if r.status == "fail":
            print(f"FAIL {r.case_id} {r.kind}: {r.detail}")
    graded = counts["pass"] + counts["fail"]
    pending = Counter(r.kind for r in results if r.status in ("pending", "dynamic"))
    print(f"auto-checks graded: {counts['pass']}/{graded} pass")
    print(f"not gradeable yet: {sum(pending.values())} -> {dict(sorted(pending.items()))}")
    if counts["fail"]:
        raise SystemExit(1)  # non-zero exit fails the CI step


if __name__ == "__main__":
    main()
