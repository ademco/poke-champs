"""Phase 5 eval machinery with fake answerer and fake judge (no API calls)."""

from test_answer import answer, chunk

from pokechamp.answer.llm import FakeLLM, Usage
from pokechamp.answer.pipeline import answer_question
from pokechamp.evals.answers import (
    build_questions,
    expected_statuses,
    phase5_cases,
    report,
    run,
    text_checks,
    usage_summary,
)
from pokechamp.evals.judges import RubricGrade, grade_grounding
from pokechamp.tools.repo import SnapshotFacts


def by_id(cid):
    return next(c for c in phase5_cases() if c.id == cid)


def test_phase5_scope_and_expected_statuses():
    cases = phase5_cases()
    assert {c.category for c in cases} == {"mechanics", "trick"}
    assert expected_statuses(by_id("mech-002")) == {"needs_tool"}  # stat calc: hand off
    assert expected_statuses(by_id("mech-005")) == {"answered"}
    assert expected_statuses(by_id("trick-009")) == {"not_found"}  # made-up Pokémon
    assert expected_statuses(by_id("trick-001")) == {"answered", "not_found"}
    assert len(build_questions("all")) == len(cases) + 62


def test_rubric_pass_rule():
    full = dict.fromkeys(["correctness", "grounding", "regulation", "helpfulness"], 2)
    na = {"false_premise": None, "safety": None}
    assert RubricGrade(full | na, "", Usage()).passed
    assert not RubricGrade(full | na | {"correctness": 0}, "", Usage()).passed  # critical 0
    assert RubricGrade(full | na | {"helpfulness": 0}, "", Usage()).passed is False  # 6/8 < 10/12
    assert RubricGrade(full | na | {"regulation": 1}, "", Usage()).passed  # 7/8 >= 10/12


def test_grounding_grade_counts_skipped_claims_as_unsupported():
    facts = SnapshotFacts()
    two = answer(claims=[{"text": "a", "source_ids": ["S1"]}, {"text": "b", "source_ids": ["S1"]}])
    result = answer_question("q", facts, [chunk()], FakeLLM(lambda s, u: two.model_dump()))
    judge = FakeLLM(lambda s, u: {"verdicts": [{"claim": 0, "verdict": "supported", "reason": ""}]})
    grade = grade_grounding(judge, result)
    assert grade.verdicts == ["supported", "unsupported"] and grade.supported == 0.5
    assert "Sleep lasts one or two turns" in judge.calls[0][1]  # judge sees the cited text


def test_run_and_report_end_to_end_with_fakes():
    facts = SnapshotFacts()
    llm = FakeLLM(lambda s, u: answer(answer="Sleep lasts one or two turns [S1].").model_dump())

    def judge_reply(system, user):
        if "<reference_answer>" in user:
            return {"rationale": "ok", "correctness": "2", "grounding": "2", "regulation": "2",
                    "false_premise": "n/a", "safety": "n/a", "helpfulness": "2"}  # fmt: skip
        return {"verdicts": [{"claim": 0, "verdict": "supported", "reason": ""}]}

    judge = FakeLLM(judge_reply)
    questions = [q for q in build_questions("all") if q[0] in ("mech-005", "mech-002", "n10")]
    outcomes = run(questions, lambda q: answer_question(q, facts, [chunk()], llm), judge)
    mech5, mech2, n10 = (
        next(o for o in outcomes if o.id == i) for i in ("mech-005", "mech-002", "n10")
    )  # noqa: E501
    assert mech5.status_ok and mech5.rubric.passed
    assert mech2.status_ok is False and mech2.rubric is None  # expected needs_tool; no rubric
    assert n10.status_ok is None and n10.grounding.supported == 1.0
    text = report(outcomes, "fake", "fake-judge")
    assert "golden: expected status | 1/2 (50%)" in text
    assert "mech-002: status answered (expected needs_tool)" in text
    assert "rubric pass" in text and "Cost:" in usage_summary(outcomes, "fake", "fake")


def test_text_checks_are_case_insensitive():
    facts = SnapshotFacts()
    case = by_id("mech-001")
    reply = answer(answer="You get 66 stat points, max 32 per stat; ivs are fixed.")
    result = answer_question("q", facts, [chunk()], FakeLLM(lambda s, u: reply.model_dump()))
    assert text_checks(case, result) == {"missing": [], "forbidden": []}
