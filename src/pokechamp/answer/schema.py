"""The answer contract: a JSON schema the API enforces, plus checks it can't express.

Why claims, not just prose with footnotes: each claim carries the ids of the
sources that support it, so grounding can be checked claim by claim (by code:
"does S3 exist?", and by the judge: "does S3 actually say this?").

status:
  answered    the sources answer it (including correcting a false premise)
  not_found   the sources don't cover it: say so instead of using memory
  needs_tool  the answer needs a calculation (stats, damage, speed, team
              checks). The model must not do that math; phase 7's agent will
              route these to the deterministic tools.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["answered", "not_found", "needs_tool"]
CITE = re.compile(r"\[([SF]\d+)\]")

# Sent to the API as output_config.format. Structured outputs require every
# object to list all properties as required and forbid extra keys.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_found", "needs_tool"]},
        "answer": {
            "type": "string",
            "description": "Direct answer first, concise, with inline citations like [S1] or [F2].",
        },
        "claims": {
            "type": "array",
            "description": "Every factual statement in the answer, each with its source ids.",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "source_ids"],
                "additionalProperties": False,
            },
        },
        "regulation": {"type": "string", "description": "Regulation the answer applies to."},
    },
    "required": ["status", "answer", "claims", "regulation"],
    "additionalProperties": False,
}


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    source_ids: list[str]


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Status
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    regulation: str


def citation_problems(ans: GroundedAnswer, evidence_ids: set[str], regulation: str) -> list[str]:
    """Rules the schema can't enforce. Empty list = the answer is well-grounded in form.

    (Whether a cited source really *supports* its claim is semantic: the
    grounding judge checks that.)
    """
    problems = []
    if ans.regulation != regulation:
        problems.append(f"wrong_regulation:{ans.regulation}")
    for i, claim in enumerate(ans.claims):
        if not claim.source_ids:
            problems.append(f"uncited_claim:{i}")
        problems += [f"unknown_source:{sid}" for sid in claim.source_ids if sid not in evidence_ids]
    problems += [
        f"unknown_inline_source:{sid}"
        for sid in CITE.findall(ans.answer)
        if sid not in evidence_ids
    ]
    if ans.status == "answered" and not ans.claims:
        problems.append("answered_without_claims")
    return sorted(set(problems))
