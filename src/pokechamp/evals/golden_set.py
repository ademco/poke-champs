"""Schema and loader for the golden set (evals/golden_set.yaml).

The golden set is the fixed exam every later phase is graded on. Pydantic
validates each case on load, so a typo in the YAML fails CI instead of
silently producing a broken eval.

Two kinds of grading use these fields:
  - auto_checks: compared against our structured data / deterministic tools
    (exact, cheap, no LLM). Implemented from phase 1-2 onward.
  - must_include / must_not_include + the rubric in docs/RUBRIC.md: graded by
    an LLM judge for things code can't check (clarity, correct refusal, etc.).
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

GOLDEN_SET_PATH = Path(__file__).resolve().parents[3] / "evals" / "golden_set.yaml"

Category = Literal["mechanics", "meta", "team_analysis", "trick"]
Behavior = Literal["answer", "refuse", "correct"]
GameType = Literal["doubles", "singles", "any"]

# Checks that later phases implement. Adding a kind here is a deliberate act:
# the eval runner must know how to execute it.
AutoCheckKind = Literal[
    "stat",  # computed stat for a set (stat calc tool)
    "speed_compare",  # who is faster (speed tool)
    "pokemon_legal",  # species legal in a regulation
    "item_legal",
    "move_exists",
    "learnset",  # can species learn move in Champions
    "team_legality",  # full team validation; expected = list of problem codes
    "type_weakness_count",  # how many team members are weak to a type
    "usage_top",  # top-N from usage table (dynamic expected value)
    "damage_range",  # damage % range vs @smogon/calc fixture (dynamic)
]


class _Strict(BaseModel):
    # Reject unknown keys so a misspelled field fails loudly.
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(_Strict):
    source: str  # key in pokechamp.sources.SOURCES
    ref: str  # file/path/page within that source


class AutoCheck(_Strict):
    kind: AutoCheckKind
    args: dict[str, Any] = Field(default_factory=dict)
    # None = computed at eval time (e.g. usage stats change monthly).
    expected: Any = None


class GoldenCase(_Strict):
    id: str = Field(pattern=r"^(mech|meta|team|trick)-\d{3}$")
    category: Category
    game_type: GameType
    regulation: str
    input: str
    expected_behavior: Behavior
    expected_answer: str
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(min_length=1)
    auto_checks: list[AutoCheck] = Field(default_factory=list)
    notes: str = ""


class GoldenSet(_Strict):
    version: int
    verified_on: str
    cases: list[GoldenCase]


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> GoldenSet:
    with path.open(encoding="utf-8") as f:
        return GoldenSet.model_validate(yaml.safe_load(f))
