"""Question -> evidence -> Claude -> validated, cited answer.

Usage: python -m pokechamp.answer.pipeline "How long does sleep last?"
       (or `make ask Q="..."`; needs ANTHROPIC_API_KEY and `make demo` first)
"""

import argparse
import time
from dataclasses import dataclass, field

import psycopg
from pydantic import ValidationError

from pokechamp.answer.evidence import Evidence, gather
from pokechamp.answer.llm import DEFAULT_MODEL, LLM, ClaudeLLM, LLMError, Usage
from pokechamp.answer.prompt import system_prompt, user_message
from pokechamp.answer.schema import ANSWER_SCHEMA, GroundedAnswer, citation_problems
from pokechamp.db import connect
from pokechamp.rag.embeddings import Embedder, get_embedder
from pokechamp.regulations import REGULATIONS
from pokechamp.tools.repo import DbFacts, Facts

MAX_QUESTION_CHARS = 2000  # a question, not a document; longer input is rejected


@dataclass
class AnswerResult:
    question: str
    answer: GroundedAnswer | None  # None when the model failed (error says why)
    evidence: list[Evidence]
    problems: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0
    model: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.answer is not None and not self.problems

    def cited(self) -> list[Evidence]:
        """The evidence the answer actually cites, in id order (for display)."""
        if not self.answer:
            return []
        ids = {sid for c in self.answer.claims for sid in c.source_ids}
        return [e for e in self.evidence if e.id in ids]


def answer_question(
    question: str,
    facts: Facts,
    evidence: list[Evidence],
    llm: LLM,
) -> AnswerResult:
    """The model step on its own (evidence already gathered): easy to test."""
    reg = REGULATIONS[facts.regulation]
    result = AnswerResult(question, None, evidence, model=llm.model)
    started = time.perf_counter()
    try:
        reply = llm.complete_json(
            system_prompt(reg), user_message(question, evidence), ANSWER_SCHEMA
        )
        result.usage = reply.usage
        result.answer = GroundedAnswer.model_validate(reply.data)
    except (LLMError, ValidationError, ValueError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.problems = ["no_valid_answer"]
        return result
    finally:
        result.latency_s = time.perf_counter() - started
    result.problems = citation_problems(result.answer, {e.id for e in evidence}, reg.code)
    return result


def ask(
    question: str,
    conn: psycopg.Connection,
    embedder: Embedder,
    llm: LLM,
    facts: Facts | None = None,
) -> AnswerResult:
    question = question.strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be 1-{MAX_QUESTION_CHARS} characters")
    facts = facts or DbFacts(conn)
    return answer_question(question, facts, gather(conn, facts, embedder, question), llm)


def render(result: AnswerResult) -> str:
    if result.answer is None:
        return f"(no answer: {result.error})"
    a = result.answer
    lines = [f"[{a.status}] (Regulation {a.regulation})", a.answer, "", "Sources:"]
    lines += [f"  [{e.id}] {e.title}: {e.source} ({e.license}), {e.ref}" for e in result.cited()]
    if result.problems:
        lines.append(f"\nWARNING, citation problems: {', '.join(result.problems)}")
    cost = result.usage.cost_usd(result.model)
    lines.append(
        f"\n{result.model}: {result.usage.input_tokens} in / {result.usage.output_tokens} out"
        f" tokens, {result.latency_s:.1f}s" + (f", ${cost:.5f}" if cost is not None else "")
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask a grounded question")
    parser.add_argument("question")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    args = parser.parse_args()
    llm = ClaudeLLM(args.model, effort=args.effort)
    with connect() as conn:
        print(render(ask(args.question, conn, get_embedder(), llm)))


if __name__ == "__main__":
    main()
