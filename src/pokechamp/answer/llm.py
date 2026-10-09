"""LLM clients: one small interface, a real Claude client and a scripted fake.

The answer pipeline and the judges only need "send a system prompt and a user
message, get back JSON matching this schema". Keeping that behind a Protocol
means unit tests and CI use `FakeLLM` (no key, no cost, deterministic) and only
`make ask` / `make eval-answers` ever call the paid API.

Structured outputs: `output_config.format` with a JSON schema makes the API
constrain generation so the reply *always* parses and matches the schema
(constrained decoding, not "please reply in JSON"). We still validate with
pydantic afterwards: the schema can't express rules like "cited ids must exist".
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# USD per million tokens (input, output), Anthropic API pricing as of 2026-10-06.
# Used only to report what an eval run cost; the bill is the source of truth.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
DEFAULT_MODEL = "claude-haiku-5-5"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0  # includes thinking tokens: they're billed as output
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls

    def cost_usd(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        pin, pout = PRICES[model]
        return (self.input_tokens * pin + self.output_tokens * pout) / 1_000_000


@dataclass
class LLMReply:
    data: dict[str, Any]
    usage: Usage
    latency_s: float
    stop_reason: str


class LLMError(RuntimeError):
    """The model didn't produce a usable reply (refusal, truncation, bad JSON)."""


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMReply: ...


class ClaudeLLM:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "low", max_tokens: int = 4000):
        import anthropic  # lazy: tests never need it

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set (copy .env.example to .env)")
        self.model = model
        # effort controls how much the model thinks (and how many output tokens
        # it spends). Short grounded answers from 5 sources don't need much;
        # the eval measures whether "low" costs quality.
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic()

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMReply:
        started = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        latency = time.perf_counter() - started
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens, 1)
        if response.stop_reason == "refusal":
            raise LLMError("model refused the request")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"reply truncated at max_tokens={self.max_tokens}")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("no text block in reply")
        return LLMReply(json.loads(text), usage, latency, response.stop_reason)


@dataclass
class FakeLLM:
    """Returns scripted replies, and records what it was asked (tests only).

    `responder` gets (system, user) and returns the reply dict, so a test can
    answer based on which sources were in the prompt.
    """

    responder: Callable[[str, str], dict[str, Any]]
    model: str = "fake-llm"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> LLMReply:
        self.calls.append((system, user))
        return LLMReply(self.responder(system, user), Usage(100, 50, 1), 0.0, "end_turn")
