"""Answer-quality and grounding evaluation (phase 5).

Two question sets:
  golden     the golden-set cases a text-grounded answerer can handle
             (mechanics + trick). Graded by code (status, citations,
             must_include) and by the rubric judge.
  retrieval  the 62 phase-4 retrieval questions. No reference answers, so they
             measure grounding only: does every claim's cited source support it?

Out of scope until later phases (reported, not hidden): meta questions (need
usage stats) and team analyses (need the phase-7 agent and its tools). Golden
cases whose checks need a calculation are kept: the right phase-5 behaviour is
status "needs_tool", i.e. *not* doing the math.

Usage: python -m pokechamp.evals.answers [--set golden|retrieval|all]
           [--model claude-haiku-5-5] [--effort low] [--judge claude-haiku-5-5]
           [--no-judge] [--limit N] [--out results.json]
Costs money: every question is one answerer call plus up to two judge calls.
"""

import argparse
import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pokechamp.answer.evidence import gather
from pokechamp.answer.llm import DEFAULT_MODEL, LLM, ClaudeLLM, Usage
from pokechamp.answer.pipeline import AnswerResult, answer_question
from pokechamp.db import connect
from pokechamp.evals.golden_set import GoldenCase, load_golden_set
from pokechamp.evals.judges import (
    DIMENSIONS,
    GroundingGrade,
    RubricGrade,
    grade_grounding,
    grade_rubric,
)
from pokechamp.evals.retrieval import load_retrieval_set
from pokechamp.rag.embeddings import get_embedder
from pokechamp.tools.repo import DbFacts

PHASE5_CATEGORIES = ("mechanics", "trick")
# Checks that need a calculation tool: a phase-5 answer should hand these off.
TOOL_CHECKS = {"stat", "speed_compare", "damage_range", "team_legality", "type_weakness_count"}


def expected_statuses(case: GoldenCase) -> set[str]:
    if TOOL_CHECKS & {c.kind for c in case.auto_checks}:
        return {"needs_tool"}
    if case.expected_behavior == "refuse":
        return {"not_found"}
    if case.expected_behavior == "correct":
        # A correction can come as an answer citing a source ("Choice Specs is
        # not legal [F1]") or as "not found" for a name that doesn't exist.
        return {"answered", "not_found"}
    return {"answered"}


def phase5_cases() -> list[GoldenCase]:
    return [c for c in load_golden_set().cases if c.category in PHASE5_CATEGORIES]


def text_checks(case: GoldenCase, result: AnswerResult) -> dict[str, list[str]]:
    """must_include / must_not_include, case-insensitive substring match."""
    text = (result.answer.answer if result.answer else "").lower()
    return {
        "missing": [s for s in case.must_include if s.lower() not in text],
        "forbidden": [s for s in case.must_not_include if s.lower() in text],
    }


@dataclass
class CaseOutcome:
    id: str
    set: str
    question: str
    result: AnswerResult
    expected_status: set[str] = field(default_factory=set)
    text: dict[str, list[str]] = field(default_factory=dict)
    rubric: RubricGrade | None = None
    grounding: GroundingGrade | None = None

    @property
    def status_ok(self) -> bool | None:
        if not self.expected_status:
            return None
        return bool(self.result.answer) and self.result.answer.status in self.expected_status

    def to_json(self) -> dict:
        a = self.result.answer
        return {
            "id": self.id,
            "set": self.set,
            "question": self.question,
            "status": a.status if a else None,
            "expected_status": sorted(self.expected_status),
            "answer": a.answer if a else None,
            "claims": [c.model_dump() for c in a.claims] if a else [],
            "evidence": [
                {"id": e.id, "title": e.title, "ref": e.ref} for e in self.result.evidence
            ],
            "problems": self.result.problems,
            "error": self.result.error,
            "text_checks": self.text,
            "rubric": (
                {"scores": self.rubric.scores, "passed": self.rubric.passed,
                 "rationale": self.rubric.rationale} if self.rubric else None
            ),
            "grounding": self.grounding.verdicts if self.grounding else None,
            "latency_s": round(self.result.latency_s, 2),
            "tokens": [self.result.usage.input_tokens, self.result.usage.output_tokens],
        }  # fmt: skip


def run(
    questions: list[tuple[str, str, str, GoldenCase | None]],
    answer_fn,
    judge: LLM | None,
) -> list[CaseOutcome]:
    """questions: (id, set, text, golden case or None). answer_fn(text) -> AnswerResult."""
    outcomes = []
    for qid, qset, text, case in questions:
        result = answer_fn(text)
        o = CaseOutcome(qid, qset, text, result)
        if case is not None:
            o.expected_status = expected_statuses(case)
            o.text = text_checks(case, result)
        if judge is not None and result.answer is not None:
            o.grounding = grade_grounding(judge, result)
            # The rubric needs a reference answer, and grades content: skip it
            # for hand-offs (needs_tool), which are graded on status alone.
            if case is not None and o.expected_status != {"needs_tool"}:
                o.rubric = grade_rubric(judge, case, result)
        outcomes.append(o)
        print(f"  {qid}: {result.answer.status if result.answer else 'ERROR'}", flush=True)
    return outcomes


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


def report(outcomes: list[CaseOutcome], model: str, judge_model: str | None) -> str:
    golden = [o for o in outcomes if o.set == "golden"]
    answered = [o for o in outcomes if o.result.answer]
    lines = [f"Answer eval: {model}" + (f", judged by {judge_model}" if judge_model else "")]
    lines += ["", "| check | result |", "|---|---|"]

    def row(label: str, value: str) -> None:
        lines.append(f"| {label} | {value} |")

    n = len(outcomes)
    row("valid JSON answer", _pct(len(answered), n))
    clean = sum(1 for o in outcomes if not o.result.problems)
    row("citations well-formed (ids exist, every claim cited)", _pct(clean, n))
    if golden:
        row("golden: expected status", _pct(sum(bool(o.status_ok) for o in golden), len(golden)))
        inc = [o for o in golden if o.result.answer and o.result.answer.status == "answered"]
        no_missing = sum(1 for o in inc if not o.text["missing"])
        row("golden (answered): all must_include present", _pct(no_missing, len(inc)))
        no_forbidden = sum(1 for o in golden if not o.text["forbidden"])
        row("golden: no must_not_include text", _pct(no_forbidden, len(golden)))

    graded = [o for o in outcomes if o.grounding and o.grounding.verdicts]
    if graded:
        claims = Counter(v for o in graded for v in o.grounding.verdicts)
        part, unsup = claims["partially_supported"], claims["unsupported"]
        sup = _pct(claims["supported"], sum(claims.values()))
        row("grounding: claims supported by their citation", f"{sup}; partial {part}, no {unsup}")
        faith = statistics.mean(o.grounding.supported for o in graded)
        row("grounding: mean faithfulness per answer", f"{faith:.2f}")
        all_sup = sum(1 for o in graded if set(o.grounding.verdicts) == {"supported"})
        row("grounding: answers with every claim supported", _pct(all_sup, len(graded)))

    rubric = [o for o in golden if o.rubric]
    if rubric:
        row(
            "rubric pass (docs/RUBRIC.md rule)",
            _pct(sum(o.rubric.passed for o in rubric), len(rubric)),
        )
        lines += ["", "Rubric mean score by dimension (0-2; n/a excluded)", ""]
        lines += ["| " + " | ".join(DIMENSIONS) + " |", "|" + "---|" * len(DIMENSIONS)]
        means = []
        for d in DIMENSIONS:
            vals = [o.rubric.scores[d] for o in rubric if o.rubric.scores[d] is not None]
            means.append(f"{statistics.mean(vals):.2f} (n={len(vals)})" if vals else "n/a")
        lines.append("| " + " | ".join(means) + " |")

    statuses = Counter(o.result.answer.status for o in answered)
    lat = [o.result.latency_s for o in answered]
    lines += ["", f"Status counts: {dict(statuses)}"]
    if lat:
        lines.append(f"Answer latency: median {statistics.median(lat):.1f}s, max {max(lat):.1f}s")

    lines += ["", "Golden cases needing attention:"]
    for o in golden:
        flags = []
        if not o.status_ok:
            got = o.result.answer.status if o.result.answer else "error"
            flags.append(f"status {got} (expected {'/'.join(sorted(o.expected_status))})")
        if o.text.get("missing") and o.result.answer and o.result.answer.status == "answered":
            flags.append(f"missing {o.text['missing']}")
        if o.text.get("forbidden"):
            flags.append(f"forbidden {o.text['forbidden']}")
        if o.result.problems:
            flags.append(f"problems {o.result.problems}")
        if o.rubric and not o.rubric.passed:
            flags.append(f"rubric fail {o.rubric.scores}")
        if flags:
            lines.append(f"  {o.id}: " + "; ".join(flags))
    return "\n".join(lines)


def usage_summary(outcomes: list[CaseOutcome], model: str, judge_model: str | None) -> str:
    ans, jud = Usage(), Usage()
    for o in outcomes:
        ans.add(o.result.usage)
        for g in (o.rubric, o.grounding):
            if g:
                jud.add(g.usage)
    parts = [f"answerer {ans.calls} calls, {ans.input_tokens}/{ans.output_tokens} tokens"]
    if (c := ans.cost_usd(model)) is not None:
        parts[-1] += f", ${c:.3f}"
    if judge_model and jud.calls:
        parts.append(f"judge {jud.calls} calls, {jud.input_tokens}/{jud.output_tokens} tokens")
        if (c := jud.cost_usd(judge_model)) is not None:
            parts[-1] += f", ${c:.3f}"
    return "Cost: " + "; ".join(parts)


def build_questions(which: str) -> list[tuple[str, str, str, GoldenCase | None]]:
    qs: list[tuple[str, str, str, GoldenCase | None]] = []
    if which in ("golden", "all"):
        qs += [(c.id, "golden", c.input, c) for c in phase5_cases()]
    if which in ("retrieval", "all"):
        qs += [(q.id, "retrieval", q.query, None) for q in load_retrieval_set()]
    return qs


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grounded answers (calls the API)")
    parser.add_argument("--set", default="all", choices=["golden", "retrieval", "all"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    parser.add_argument("--judge", default=DEFAULT_MODEL, help="judge model")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--limit", type=int, help="only the first N questions (smoke run)")
    parser.add_argument("--out", type=Path, help="write every answer and grade as JSON")
    args = parser.parse_args()

    questions = build_questions(args.set)[: args.limit]
    llm = ClaudeLLM(args.model, effort=args.effort)
    judge = None if args.no_judge else ClaudeLLM(args.judge, effort="medium")
    embedder = get_embedder()
    print(f"{len(questions)} questions, answerer {args.model} (effort {args.effort})")
    with connect() as conn:
        facts = DbFacts(conn)
        outcomes = run(
            questions,
            lambda q: answer_question(q, facts, gather(conn, facts, embedder, q), llm),
            judge,
        )
    judge_model = None if judge is None else args.judge
    print("\n" + report(outcomes, f"{args.model} (effort {args.effort})", judge_model))
    print("\n" + usage_summary(outcomes, args.model, judge_model))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps([o.to_json() for o in outcomes], indent=2, ensure_ascii=False)
        )
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
