"""Run the golden set's auto-checks against the structured facts in Postgres.

Each check kind maps to a function. Kinds that need phase-2 tools (stat calc,
damage, team validation...) aren't registered yet and are reported as
"pending", so the summary shows exactly how much of the exam the system can
already grade itself.

Usage: python -m pokechamp.evals.auto_checks
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from pokechamp import facts
from pokechamp.db import connect
from pokechamp.evals.golden_set import AutoCheck, load_golden_set

CheckFn = Callable[[psycopg.Connection, dict[str, Any]], Any]

CHECKS: dict[str, CheckFn] = {
    "pokemon_legal": lambda conn, a: facts.species_legal(conn, a["species"], a.get("regulation")),
    "item_legal": lambda conn, a: facts.item_legal(conn, a["item"], a.get("regulation")),
    "move_exists": lambda conn, a: facts.move_exists(conn, a["move"]),
    "learnset": lambda conn, a: facts.can_learn(conn, a["species"], a["move"]),
}


@dataclass(frozen=True)
class Result:
    case_id: str
    kind: str
    status: str  # "pass" | "fail" | "pending" (no tool yet) | "dynamic" (expected computed later)
    detail: str = ""


def run_check(conn: psycopg.Connection, case_id: str, check: AutoCheck) -> Result:
    fn = CHECKS.get(check.kind)
    if fn is None:
        return Result(case_id, check.kind, "pending")
    if check.expected is None:
        return Result(case_id, check.kind, "dynamic")
    actual = fn(conn, check.args)
    if actual == check.expected:
        return Result(case_id, check.kind, "pass")
    return Result(
        case_id, check.kind, "fail", f"args={check.args} expected={check.expected!r} got={actual!r}"
    )


def run_all(conn: psycopg.Connection) -> list[Result]:
    return [
        run_check(conn, case.id, check)
        for case in load_golden_set().cases
        for check in case.auto_checks
    ]


def main() -> None:
    with connect() as conn:
        results = run_all(conn)
    counts = Counter(r.status for r in results)
    for r in results:
        if r.status == "fail":
            print(f"FAIL {r.case_id} {r.kind}: {r.detail}")
    graded = counts["pass"] + counts["fail"]
    pending = Counter(r.kind for r in results if r.status == "pending")
    print(f"auto-checks graded: {counts['pass']}/{graded} pass")
    print(f"not gradeable yet: {sum(pending.values())} -> {dict(sorted(pending.items()))}")
    if counts["fail"]:
        raise SystemExit(1)  # non-zero exit fails the CI step


if __name__ == "__main__":
    main()
