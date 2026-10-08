"""Game-accurate integer arithmetic, ported from @smogon/calc mechanics/util.ts.

The games multiply by fractions of 4096 and round in specific ways. Using
plain floats (x * 1.5) gives answers that are off by one HP surprisingly often,
which is exactly the kind of error a "2HKO or 3HKO?" question can't afford.
"""

import math


def poke_round(num: float) -> int:
    """Round half *down* (0.5 -> 0), unlike Python's round-half-even."""
    return math.ceil(num) if num % 1 > 0.5 else math.floor(num)


def of16(n: int) -> int:
    """16-bit overflow, as in the cartridge's arithmetic."""
    return n % 65536 if n > 65535 else n


def of32(n: float) -> float:
    return n % 4294967296 if n > 4294967295 else n


def chain_mods(mods: list[int], lower: int, upper: int) -> int:
    """Combine 4096-based modifiers the way the games do (rounded at each step)."""
    m = 4096
    for mod in mods:
        if mod != 4096:
            m = (m * mod + 2048) >> 12
    return max(min(m, upper), lower)
