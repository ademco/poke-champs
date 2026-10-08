"""Champions stat calculation (level 50, Stat Points, IVs fixed at 31).

Formula, verified against Showdown (data/mods/champions/scripts.ts statModify)
and @smogon/calc (stats.ts calcStatChampions):
    HP    = base + SP + 75            (Shedinja: always 1)
    other = floor((base + SP + 20) * nature)   nature = 1.1 / 1.0 / 0.9
The nature step is floor(x * 110 / 100), done in integers so 1.1 never
introduces float error.
"""

from collections.abc import Mapping

from pokechamp.tools.repo import STATS

SP_MAX_PER_STAT = 32
SP_TOTAL = 66


class StatError(ValueError):
    """Bad input (unknown stat, SP out of range). Never silently clamped."""


def nature_percent(stat: str, nature: tuple[str | None, str | None]) -> int:
    plus, minus = nature
    if stat == plus:
        return 110
    if stat == minus:
        return 90
    return 100


def calc_stat(stat: str, base: int, sp: int, nature: tuple[str | None, str | None]) -> int:
    if stat not in STATS:
        raise StatError(f"unknown stat {stat!r}")
    if not 0 <= sp <= SP_MAX_PER_STAT:
        raise StatError(f"{sp} SP in {stat} is outside 0-{SP_MAX_PER_STAT}")
    if stat == "hp":
        return 1 if base == 1 else base + sp + 75
    return (base + sp + 20) * nature_percent(stat, nature) // 100


def calc_stats(
    base_stats: Mapping[str, int],
    sp: Mapping[str, int],
    nature: tuple[str | None, str | None],
) -> dict[str, int]:
    """All six stats. Missing SP entries count as 0."""
    unknown = set(sp) - set(STATS)
    if unknown:
        raise StatError(f"unknown stats {sorted(unknown)}")
    return {s: calc_stat(s, base_stats[s], sp.get(s, 0), nature) for s in STATS}


# Stat stages -6..+6 multiply by (2+n)/2 or 2/(2-n), rounding down (Gen 5+).
def apply_stage(stat: int, stage: int) -> int:
    if not -6 <= stage <= 6:
        raise StatError(f"stat stage {stage} outside -6..+6")
    num, den = (2 + stage, 2) if stage >= 0 else (2, 2 - stage)
    return stat * num // den
