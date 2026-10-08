"""Effective Speed and move order, mirroring @smogon/calc's getFinalSpeed.

Order of operations (Champions = Gen 9 rules):
  1. stat stage multiplier
  2. chained modifiers in 4096ths: Tailwind 2x, speed abilities, Choice Scarf 1.5x
  3. paralysis: x0.5 (Gen 7+ value; Champions keeps it)
Trick Room reverses the order; equal Speed is a coin flip ("tie").
"""

from dataclasses import dataclass

from pokechamp.tools.mathutil import chain_mods, poke_round
from pokechamp.tools.stats import apply_stage

# Ability -> condition under which it doubles Speed.
WEATHER_SPEED_ABILITIES = {
    "Chlorophyll": "Sun",
    "Swift Swim": "Rain",
    "Sand Rush": "Sand",
    "Slush Rush": "Snow",
}


@dataclass(frozen=True)
class SpeedContext:
    stage: int = 0
    tailwind: bool = False
    item: str | None = None
    ability: str | None = None
    weather: str | None = None  # "Sun" | "Rain" | "Sand" | "Snow"
    terrain: str | None = None
    paralyzed: bool = False
    unburden_active: bool = False  # item was consumed/removed this battle


def final_speed(raw_speed: int, ctx: SpeedContext | None = None) -> int:
    ctx = ctx or SpeedContext()
    speed = apply_stage(raw_speed, ctx.stage)
    mods = []
    if ctx.tailwind:
        mods.append(8192)
    ability = ctx.ability or ""
    if (
        (ability == "Unburden" and ctx.unburden_active)
        or (ability in WEATHER_SPEED_ABILITIES and WEATHER_SPEED_ABILITIES[ability] == ctx.weather)
        or (ability == "Surge Surfer" and ctx.terrain == "Electric")
    ):
        mods.append(8192)
    elif ability == "Quick Feet" and ctx.paralyzed:
        mods.append(6144)
    if not (ability == "Unburden" and ctx.unburden_active):
        if ctx.item == "Choice Scarf":
            mods.append(6144)
        elif ctx.item == "Iron Ball":
            mods.append(2048)
    speed = poke_round(speed * chain_mods(mods, 410, 131172) / 4096)
    if ctx.paralyzed and ability != "Quick Feet":
        speed = speed * 50 // 100
    return speed


@dataclass(frozen=True)
class SpeedComparison:
    a: int
    b: int
    faster: str  # "a" | "b" | "tie": who moves first among same-priority moves


def compare(a_speed: int, b_speed: int, trick_room: bool = False) -> SpeedComparison:
    if a_speed == b_speed:
        return SpeedComparison(a_speed, b_speed, "tie")
    a_first = (a_speed < b_speed) if trick_room else (a_speed > b_speed)
    return SpeedComparison(a_speed, b_speed, "a" if a_first else "b")
