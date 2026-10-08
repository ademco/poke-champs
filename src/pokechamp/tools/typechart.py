"""Type effectiveness from the type_chart table (never from the LLM's memory).

These are *type-only* matchups. Abilities that change them (Levitate, Flash
Fire, Thick Fat...) are handled by the damage calculator, and the team report
says so instead of quietly mixing the two.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pokechamp.tools.repo import Facts

TYPES = (
    "Bug", "Dark", "Dragon", "Electric", "Fairy", "Fighting", "Fire", "Flying", "Ghost",
    "Grass", "Ground", "Ice", "Normal", "Poison", "Psychic", "Rock", "Steel", "Water",
)  # fmt: skip


def effectiveness(facts: Facts, attacking: str, defending: Sequence[str]) -> float:
    """Product over the defender's types: 0, 0.25, 0.5, 1, 2 or 4."""
    result = 1.0
    for t in defending:
        result *= facts.type_multiplier(attacking, t)
    return result


@dataclass(frozen=True)
class TeamWeakness:
    attacking_type: str
    weak: tuple[tuple[str, float], ...]  # (member, multiplier > 1)
    resist: tuple[tuple[str, float], ...]  # (member, multiplier < 1, including 0)


def team_weaknesses(
    facts: Facts, members: Sequence[tuple[str, Sequence[str]]]
) -> list[TeamWeakness]:
    """For each attacking type: who is hit super-effectively and who resists.

    `members` is [(name, types), ...]. Sorted worst-first: most weak members,
    then fewest resists.
    """
    report = []
    for atk in TYPES:
        mults = [(name, effectiveness(facts, atk, types)) for name, types in members]
        report.append(
            TeamWeakness(
                atk,
                tuple((n, m) for n, m in mults if m > 1),
                tuple((n, m) for n, m in mults if m < 1),
            )
        )
    return sorted(report, key=lambda w: (-len(w.weak), len(w.resist), w.attacking_type))
