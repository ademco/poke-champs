"""Champions damage calculator: a Python port of @smogon/calc 0.12.0's
`calculateChampions` (calc/src/mechanics/champions.ts, MIT).

Why port instead of calling @smogon/calc through Node? One runtime in the
container, plain-Python unit tests, and the agent can call it as an ordinary
function. Correctness is enforced by tests/fixtures/damage_expected.json:
outputs of the real @smogon/calc for the same inputs, compared roll by roll.

Honesty rule: anything @smogon/calc models that this port doesn't (see
damage_tables.UNSUPPORTED_*, multi-hit moves) raises UnsupportedCalculation.
A refusal is better than a confident wrong number.

Structure mirrors the original so the two can be diffed side by side:
  calculate() -> base power -> attack -> defense -> base damage -> 16 rolls
"""

import math
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

from pokechamp.tools.damage_tables import (
    BERRY_RESIST_TYPE,
    ITEM_BOOST_TYPE,
    MOLD_BREAKER_IGNORES,
    UNSUPPORTED_ABILITIES,
    UNSUPPORTED_ITEMS,
    UNSUPPORTED_MOVES,
)
from pokechamp.tools.mathutil import chain_mods, of16, of32, poke_round
from pokechamp.tools.repo import STATS, Facts, MoveInfo, SpeciesInfo
from pokechamp.tools.speed import SpeedContext, final_speed
from pokechamp.tools.stats import apply_stage, calc_stats


class UnsupportedCalculation(ValueError):
    """The inputs need a mechanic this port doesn't implement."""


@dataclass
class Combatant:
    species: SpeciesInfo
    raw_stats: dict[str, int]  # after SP and nature, before boosts
    ability: str = ""
    item: str = ""
    boosts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STATS[1:], 0))
    status: str = ""  # "brn" | "par" | "psn" | "tox" | "slp" | "frz" | ""
    cur_hp: int | None = None  # None = full HP
    ability_on: bool = False  # e.g. Intimidate activated (matches @smogon/calc's toggle)
    allies_fainted: int = 0  # Supreme Overlord

    @property
    def name(self) -> str:
        return self.species.name

    @property
    def types(self) -> tuple[str, ...]:
        return self.species.types

    @property
    def max_hp(self) -> int:
        return self.raw_stats["hp"]

    @property
    def hp(self) -> int:
        return self.max_hp if self.cur_hp is None else self.cur_hp

    def has_ability(self, *names: str) -> bool:
        return self.ability in names

    def has_item(self, *names: str) -> bool:
        return self.item in names


@dataclass
class Side:
    reflect: bool = False
    light_screen: bool = False
    aurora_veil: bool = False
    helping_hand: bool = False
    friend_guard: bool = False
    tailwind: bool = False


@dataclass
class FieldState:
    game_type: str = "doubles"  # "doubles" | "singles"
    weather: str | None = None  # "Sun" | "Rain" | "Sand" | "Snow"
    terrain: str | None = None  # "Electric" | "Grassy" | "Psychic" | "Misty"
    attacker_side: Side = field(default_factory=Side)
    defender_side: Side = field(default_factory=Side)


@dataclass(frozen=True)
class DamageResult:
    attacker: str
    defender: str
    move: str
    rolls: list[int]  # 16 damage rolls, low to high; all 0 if no effect
    defender_hp: int  # max HP (percentages are of max HP)
    notes: tuple[str, ...] = ()
    defender_cur_hp: int | None = None  # None = full HP

    @property
    def min_percent(self) -> float:
        # Truncated to one decimal, as @smogon/calc displays it.
        return math.floor(1000 * self.rolls[0] / self.defender_hp) / 10

    @property
    def max_percent(self) -> float:
        return math.floor(1000 * self.rolls[-1] / self.defender_hp) / 10

    def ko_chance(self, max_hits: int = 4) -> tuple[int, float] | None:
        """(hits, probability) for the fewest hits that can KO from current HP.

        Each hit draws one of the 16 rolls with equal probability; we count
        combinations whose total reaches the defender's HP. Recovery, recoil,
        weather chip and berries between hits are NOT modeled; callers must say
        so rather than present this as the whole story.
        """
        if self.rolls[-1] == 0:
            return None
        hp = self.defender_hp if self.defender_cur_hp is None else self.defender_cur_hp
        dist = {0: 1}  # total damage -> number of roll combinations
        for hits in range(1, max_hits + 1):
            nxt: dict[int, int] = {}
            for total, ways in dist.items():
                for r in self.rolls:
                    nxt[total + r] = nxt.get(total + r, 0) + ways
            dist = nxt
            ko_ways = sum(w for total, w in dist.items() if total >= hp)
            if ko_ways:
                return hits, ko_ways / 16**hits
        return None

    def ko_summary(self) -> str:
        """Same wording as @smogon/calc for the no-recovery case."""
        if self.rolls[-1] == 0:
            return "no damage"
        ko = self.ko_chance()
        if ko is None:  # beyond 4 hits: report the bounds only
            hp = self.defender_hp if self.defender_cur_hp is None else self.defender_cur_hp
            most, least = math.ceil(hp / self.rolls[-1]), math.ceil(hp / max(self.rolls[0], 1))
            return f"{'guaranteed' if most == least else 'possible'} {most}HKO"
        hits, p = ko
        label = "OHKO" if hits == 1 else f"{hits}HKO"
        if p == 1:
            return f"guaranteed {label}"
        pct = Decimal(p * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP).normalize()
        return f"{pct:f}% chance to {label}"


# ── helpers mirroring util.ts ──────────────────────────────────────────────


def _modified_stat(stat: int, stage: int) -> int:
    return apply_stage(of16(stat), stage) if stage else stat


def _is_grounded(p: Combatant) -> bool:
    return not (
        "Flying" in p.types or p.has_ability("Levitate", "Eelevate") or p.has_item("Air Balloon")
    ) or p.has_item("Iron Ball")


def _count_boosts(boosts: dict[str, int]) -> int:
    return sum(b for b in boosts.values() if b > 0)  # only positive boosts count


def _weight(p: Combatant) -> float:
    hg = round(p.species.weightkg * 10)
    factor = 2 if p.has_ability("Heavy Metal") else 0.5 if p.has_ability("Light Metal") else 1
    if factor != 1:
        hg = max(math.trunc(hg * factor), 1)
    if p.has_item("Float Stone"):
        hg = max(math.trunc(hg * 0.5), 1)
    return hg / 10


def _apply_intimidate(source: Combatant, target: Combatant) -> None:
    if not (source.has_ability("Intimidate") and source.ability_on):
        return
    blocked = target.has_ability(
        "Clear Body", "White Smoke", "Hyper Cutter", "Full Metal Body",
        "Inner Focus", "Own Tempo", "Oblivious", "Scrappy",
    ) or target.has_item("Clear Amulet")  # fmt: skip
    if blocked:
        return
    b = target.boosts
    if target.has_ability("Contrary", "Defiant", "Guard Dog"):
        b["atk"] = min(6, b["atk"] + 1)
    elif target.has_ability("Simple"):
        b["atk"] = max(-6, b["atk"] - 2)
    else:
        b["atk"] = max(-6, b["atk"] - 1)
    if target.has_ability("Competitive"):
        b["spa"] = min(6, b["spa"] + 2)


def _check_supported(attacker: Combatant, defender: Combatant, move: MoveInfo) -> None:
    for p in (attacker, defender):
        if p.ability in UNSUPPORTED_ABILITIES:
            raise UnsupportedCalculation(f"ability {p.ability} ({p.name}) is not supported yet")
        if p.item in UNSUPPORTED_ITEMS:
            raise UnsupportedCalculation(f"item {p.item} ({p.name}) is not supported yet")
    if move.name in UNSUPPORTED_MOVES:
        raise UnsupportedCalculation(f"move {move.name} is not supported yet")
    if move.multihit:
        raise UnsupportedCalculation(f"multi-hit move {move.name} is not supported yet")


VARIABLE_BP_MOVES = frozenset({
    "Payback", "Electro Ball", "Gyro Ball", "Punishment", "Low Kick", "Grass Knot",
    "Hex", "Infernal Parade", "Barb Barrage", "Heavy Slam", "Heat Crash", "Stored Power",
    "Power Trip", "Acrobatics", "Smelling Salts", "Weather Ball", "Rising Voltage",
    "Eruption", "Water Spout", "Flail", "Reversal", "Hard Press",
})  # fmt: skip


# ── main entry point ───────────────────────────────────────────────────────


def calculate(
    facts: Facts,
    attacker: Combatant,
    defender: Combatant,
    move: MoveInfo,
    fieldstate: FieldState | None = None,
    is_crit: bool = False,
) -> DamageResult:
    _check_supported(attacker, defender, move)
    if move.category != "Status" and move.base_power == 0 and move.name not in VARIABLE_BP_MOVES:
        raise UnsupportedCalculation(f"{move.name} has no fixed base power and isn't supported")

    # Work on copies: the calculation mutates boosts/abilities like the original.
    a = replace(attacker, boosts=dict(attacker.boosts))
    d = replace(defender, boosts=dict(defender.boosts))
    f = fieldstate or FieldState()
    f = replace(f, attacker_side=replace(f.attacker_side), defender_side=replace(f.defender_side))
    notes: list[str] = []

    def zero(reason: str) -> DamageResult:
        return DamageResult(a.name, d.name, move.name, [0] * 16, d.max_hp, (*notes, reason), d.hp)

    if a.has_ability("Air Lock", "Cloud Nine") or d.has_ability("Air Lock", "Cloud Nine"):
        f.weather = None

    # Final Speeds decide turn order (Payback, Analytic). Computed before any
    # ability swaps below, which replace the Combatant objects.
    a_speed, d_speed = (
        final_speed(
            p.raw_stats["spe"],
            SpeedContext(
                stage=p.boosts["spe"], tailwind=side.tailwind, item=p.item, ability=p.ability,
                weather=f.weather, terrain=f.terrain, paralyzed=p.status == "par",
            ),
        )
        for p, side in ((a, f.attacker_side), (d, f.defender_side))
    )  # fmt: skip
    _apply_intimidate(a, d)
    _apply_intimidate(d, a)
    if move.name in ("Meteor Beam", "Electro Shot"):
        a.boosts["spa"] = max(
            -6, min(6, a.boosts["spa"] + (-1 if a.has_ability("Contrary") else 1))
        )
    for p, side in ((a, f.defender_side), (d, f.attacker_side)):
        if p.has_ability("Infiltrator"):
            side.reflect = side.light_screen = side.aurora_veil = False

    if move.category == "Status":
        return zero("status move")

    if d.ability in MOLD_BREAKER_IGNORES and a.has_ability("Mold Breaker"):
        d = replace(d, ability="")

    is_critical = not d.has_ability("Shell Armor", "Battle Armor") and (
        is_crit or move.will_crit or (a.has_ability("Merciless") and d.status in ("psn", "tox"))
    )

    # Move type
    move_type = move.type
    if move.name == "Weather Ball":
        mega_sol = a.has_ability("Mega Sol")
        move_type = (
            "Fire" if f.weather == "Sun" or mega_sol
            else "Water" if f.weather == "Rain"
            else "Rock" if f.weather == "Sand"
            else "Ice" if f.weather == "Snow"
            else "Normal"
        )  # fmt: skip
    elif move.name in ("Brick Break", "Psychic Fangs"):
        f.defender_side.reflect = f.defender_side.light_screen = f.defender_side.aurora_veil = False

    ate_change = False
    if move.name not in ("Weather Ball", "Terrain Pulse", "Struggle"):
        normal = move_type == "Normal"
        ate = {
            "Aerilate": "Flying",
            "Dragonize": "Dragon",
            "Pixilate": "Fairy",
            "Refrigerate": "Ice",
        }
        if a.ability in ate and normal:
            move_type, ate_change = ate[a.ability], True
        elif a.has_ability("Liquid Voice") and "sound" in move.flags:
            move_type = "Water"

    def eff_one(def_type: str) -> float:
        if a.has_ability("Scrappy") and def_type == "Ghost" and move_type in ("Normal", "Fighting"):
            return 1
        if move.name == "Freeze-Dry" and def_type == "Water":
            return 2
        return facts.type_multiplier(move_type, def_type)

    type_eff = 1.0
    for t in d.types:
        type_eff *= eff_one(t)
    if type_eff == 0 and move_type == "Ground" and d.has_item("Iron Ball"):
        type_eff = 1
    if type_eff == 0:
        return zero("type immunity")

    absorbs = (
        (move_type == "Grass" and d.has_ability("Sap Sipper"))
        or (move_type == "Fire" and d.has_ability("Flash Fire"))
        or (move_type == "Water" and d.has_ability("Dry Skin", "Water Absorb"))
        or (
            move_type == "Electric" and d.has_ability("Lightning Rod", "Motor Drive", "Volt Absorb")
        )
        or (move_type == "Ground" and d.has_ability("Levitate", "Eelevate"))
        or ("bullet" in move.flags and d.has_ability("Bulletproof"))
        or (
            "sound" in move.flags and move.name != "Clangorous Soul" and d.has_ability("Soundproof")
        )
        or (move.priority > 0 and d.has_ability("Queenly Majesty", "Armor Tail"))
        or (move_type == "Ground" and d.has_ability("Earth Eater"))
    )
    if absorbs:
        return zero(f"blocked by {d.ability}")
    if move_type == "Ground" and d.has_item("Air Balloon"):
        return zero("blocked by Air Balloon")
    if move.priority > 0 and f.terrain == "Psychic" and _is_grounded(d):
        return zero("Psychic Terrain blocks priority")

    turn_order = "first" if a_speed > d_speed else "last"

    base_power = _base_power(facts, a, d, move, move_type, f, ate_change, turn_order)
    if base_power == 0:
        return zero("base power 0")
    attack = _attack(a, d, move, move_type, f, is_critical)
    defense = _defense(a, d, move, f, is_critical)
    base = _base_damage(a, move, move_type, base_power, attack, defense, f, is_critical)

    stab = 4096
    if move_type in a.types:
        stab += 2048
    elif a.has_ability("Protean", "Libero"):
        stab += 2048
    if a.has_ability("Adaptability") and move_type in a.types:
        stab += 2048

    burned = (
        a.status == "brn"
        and move.category == "Physical"
        and not a.has_ability("Guts")
        and move.name != "Facade"
    )
    final_mod = chain_mods(_final_mods(a, d, move, move_type, f, is_critical, type_eff), 41, 131072)

    rolls = []
    for i in range(16):
        dmg = math.floor(of32(base * (85 + i)) / 100)
        if stab != 4096:
            dmg = of32(dmg * stab) / 4096
        dmg = math.floor(of32(poke_round(dmg) * type_eff))
        if burned:
            dmg = dmg // 2
        rolls.append(of16(poke_round(max(1, of32(dmg * final_mod) / 4096))))
    if is_critical:
        notes.append("critical hit")
    return DamageResult(a.name, d.name, move.name, rolls, d.max_hp, tuple(notes), d.hp)


def _base_power(facts, a, d, move, move_type, f, ate_change, turn_order) -> int:
    bp = move.base_power
    name = move.name
    if name == "Payback":
        bp = move.base_power * (2 if turn_order == "last" else 1)
    elif name == "Electro Ball":
        r = a.raw_stats["spe"] // max(d.raw_stats["spe"], 1)
        bp = 150 if r >= 4 else 120 if r >= 3 else 80 if r >= 2 else 60 if r >= 1 else 40
    elif name == "Gyro Ball":
        bp = min(150, (25 * d.raw_stats["spe"]) // max(a.raw_stats["spe"], 1) + 1)
    elif name == "Punishment":
        bp = min(200, 60 + 20 * _count_boosts(d.boosts))
    elif name in ("Low Kick", "Grass Knot"):
        w = _weight(d)
        bp = (
            120
            if w >= 200
            else 100
            if w >= 100
            else 80
            if w >= 50
            else 60
            if w >= 25
            else 40
            if w >= 10
            else 20
        )
    elif name in ("Hex", "Infernal Parade"):
        bp = move.base_power * (2 if d.status else 1)
    elif name == "Barb Barrage":
        bp = move.base_power * (2 if d.status in ("psn", "tox") else 1)
    elif name in ("Heavy Slam", "Heat Crash"):
        wr = _weight(a) / _weight(d)
        bp = 120 if wr >= 5 else 100 if wr >= 4 else 80 if wr >= 3 else 60 if wr >= 2 else 40
    elif name in ("Stored Power", "Power Trip"):
        bp = 20 + 20 * _count_boosts(a.boosts)
    elif name == "Acrobatics":
        bp = move.base_power * (2 if not a.item else 1)
    elif name == "Smelling Salts":
        bp = move.base_power * (2 if d.status == "par" else 1)
    elif name == "Weather Ball":
        bp = move.base_power * (2 if f.weather or a.has_ability("Mega Sol") else 1)
    elif name == "Rising Voltage":
        bp = move.base_power * (2 if _is_grounded(d) and f.terrain == "Electric" else 1)
    elif name in ("Eruption", "Water Spout"):
        bp = max(1, (150 * a.hp) // a.max_hp)
    elif name in ("Flail", "Reversal"):
        p = (48 * a.hp) // a.max_hp
        bp = (
            200
            if p <= 1
            else 150
            if p <= 4
            else 100
            if p <= 9
            else 80
            if p <= 16
            else 40
            if p <= 32
            else 20
        )
    elif name == "Hard Press":
        bp = 100 * ((d.hp * 4096) // d.max_hp)
        bp = ((100 * bp + 2048 - 1) // 4096) // 100 or 1
    if bp == 0:
        return 0
    mods = _bp_mods(facts, a, d, move, move_type, f, bp, ate_change, turn_order)
    return of16(max(1, poke_round(bp * chain_mods(mods, 41, 2097152) / 4096)))


def _bp_mods(facts, a, d, move, move_type, f, bp, ate_change, turn_order) -> list[int]:
    mods: list[int] = []
    resisted_knock_off = not d.item
    if d.item:
        item = facts.item(d.item)
        if item and item.mega_stone:
            resisted_knock_off = d.name in item.mega_stone or d.name in item.mega_stone.values()

    name = move.name
    if (name == "Facade" and a.status in ("brn", "par", "psn", "tox")) or (
        name == "Venoshock" and d.status in ("psn", "tox")
    ):
        mods.append(8192)
    elif name == "Expanding Force" and _is_grounded(a) and f.terrain == "Psychic":
        mods.append(6144)
    elif name == "Knock Off" and not resisted_knock_off:
        mods.append(6144)
    elif (
        name in ("Solar Beam", "Solar Blade")
        and f.weather in ("Rain", "Sand", "Snow")
        and not a.has_ability("Mega Sol")
    ):
        mods.append(2048)

    if f.attacker_side.helping_hand:
        mods.append(6144)
    if _is_grounded(a) and (f.terrain, move_type) in (
        ("Electric", "Electric"),
        ("Grassy", "Grass"),
        ("Psychic", "Psychic"),
    ):
        mods.append(5325)
    if _is_grounded(d) and (
        (f.terrain == "Misty" and move_type == "Dragon")
        or (f.terrain == "Grassy" and name in ("Bulldoze", "Earthquake"))
    ):
        mods.append(2048)

    if (
        (a.has_ability("Technician") and bp <= 60)
        or (a.has_ability("Mega Launcher") and "pulse" in move.flags)
        or (a.has_ability("Strong Jaw") and "bite" in move.flags)
        or (a.has_ability("Steely Spirit") and move_type == "Steel")
        or (a.has_ability("Sharpness") and "slicing" in move.flags)
    ):
        mods.append(6144)
    aura = f"{move_type} Aura"
    if a.has_ability(aura) or d.has_ability(aura):
        mods.append(5448)
    if (
        (a.has_ability("Sheer Force") and (move.has_secondary or name == "Electro Shot"))
        or (
            a.has_ability("Sand Force")
            and f.weather == "Sand"
            and move_type in ("Rock", "Ground", "Steel")
        )
        or (a.has_ability("Analytic") and turn_order != "first")
        or (a.has_ability("Tough Claws") and "contact" in move.flags)
        or (a.has_ability("Punk Rock") and "sound" in move.flags)
    ):
        mods.append(5325)
    if ate_change:
        mods.append(4915)
    if (a.has_ability("Reckless") and (move.recoil or move.has_crash_damage)) or (
        a.has_ability("Iron Fist") and "punch" in move.flags
    ):
        mods.append(4915)
    if d.has_ability("Dry Skin") and move_type == "Fire":
        mods.append(5120)
    if a.has_ability("Supreme Overlord") and a.allies_fainted:
        mods.append([4096, 4506, 4915, 5325, 5734, 6144][min(5, a.allies_fainted)])

    if a.item == f"{move_type} Gem":
        mods.append(5325)
    elif a.item and ITEM_BOOST_TYPE.get(a.item) == move_type:
        mods.append(4915)
    elif (a.has_item("Muscle Band") and move.category == "Physical") or (
        a.has_item("Wise Glasses") and move.category == "Special"
    ):
        mods.append(4505)
    return mods


def _attack(a, d, move, move_type, f, is_critical) -> int:
    source = d if move.name == "Foul Play" else a
    stat = (
        "def"
        if move.override_offensive_stat == "def"
        else ("spa" if move.category == "Special" else "atk")
    )
    boost = source.boosts[stat]
    if boost == 0 or (is_critical and boost < 0) or d.has_ability("Unaware"):
        attack = source.raw_stats[stat]
    else:
        attack = _modified_stat(source.raw_stats[stat], boost)
    if a.has_ability("Hustle") and move.category == "Physical":
        attack = poke_round(attack * 3 / 2)

    mods: list[int] = []
    low_hp = a.hp <= a.max_hp / 3
    if a.has_ability("Solar Power") and f.weather == "Sun" and move.category == "Special":
        mods.append(6144)
    elif (
        (a.has_ability("Guts") and a.status and move.category == "Physical")
        or (low_hp and (
            (a.has_ability("Overgrow") and move_type == "Grass")
            or (a.has_ability("Blaze") and move_type == "Fire")
            or (a.has_ability("Torrent") and move_type == "Water")
            or (a.has_ability("Swarm") and move_type == "Bug")
        ))
    ):  # fmt: skip
        mods.append(6144)
    elif a.has_ability("Flash Fire") and a.ability_on and move_type == "Fire":
        mods.append(6144)
    elif a.has_ability("Fire Mane") and move_type == "Fire":
        mods.append(6144)
    elif (a.has_ability("Water Bubble") and move_type == "Water") or (
        a.has_ability("Huge Power", "Pure Power") and move.category == "Physical"
    ):
        mods.append(8192)
    if (
        (d.has_ability("Thick Fat") and move_type in ("Fire", "Ice"))
        or (d.has_ability("Water Bubble") and move_type == "Fire")
        or (d.has_ability("Purifying Salt") and move_type == "Ghost")
    ):
        mods.append(2048)
    if d.has_ability("Heatproof") and move_type == "Fire":
        mods.append(2048)
    if a.has_item("Light Ball") and "Pikachu" in a.name:
        mods.append(8192)
    return of16(max(1, poke_round(attack * chain_mods(mods, 410, 131072) / 4096)))


def _defense(a, d, move, f, is_critical) -> int:
    hits_physical = move.override_defensive_stat == "def" or move.category == "Physical"
    stat = "def" if hits_physical else "spd"
    boost = d.boosts[stat]
    if (
        boost == 0
        or (is_critical and boost > 0)
        or move.ignore_defensive
        or a.has_ability("Unaware")
    ):
        defense = d.raw_stats[stat]
    else:
        defense = _modified_stat(d.raw_stats[stat], boost)
    if not a.has_ability("Mega Sol"):
        if f.weather == "Sand" and "Rock" in d.types and not hits_physical:
            defense = poke_round(defense * 3 / 2)
        if f.weather == "Snow" and "Ice" in d.types and hits_physical:
            defense = poke_round(defense * 3 / 2)
    mods: list[int] = []
    if d.has_ability("Marvel Scale") and d.status and hits_physical:
        mods.append(6144)
    elif d.has_ability("Grass Pelt") and f.terrain == "Grassy" and hits_physical:
        mods.append(6144)
    elif d.has_ability("Fur Coat") and hits_physical:
        mods.append(8192)
    return of16(max(1, poke_round(defense * chain_mods(mods, 410, 131072) / 4096)))


def _base_damage(a, move, move_type, bp, attack, defense, f, is_critical) -> int:
    level = 50
    base = math.floor(
        of32(math.floor(of32(of32((2 * level // 5 + 2) * bp) * attack) / defense) / 50 + 2)
    )
    if f.game_type != "singles" and move.target in ("allAdjacent", "allAdjacentFoes"):
        base = poke_round(of32(base * 3072) / 4096)
    mega_sol = a.has_ability("Mega Sol")
    if ((f.weather == "Sun" or mega_sol) and move_type == "Fire") or (
        f.weather == "Rain" and not mega_sol and move_type == "Water"
    ):
        base = poke_round(of32(base * 6144) / 4096)
    elif ((f.weather == "Sun" or mega_sol) and move_type == "Water") or (
        f.weather == "Rain" and move_type == "Fire"
    ):
        base = poke_round(of32(base * 2048) / 4096)
    if is_critical:
        base = math.floor(of32(base * 1.5))
    return base


def _final_mods(a, d, move, move_type, f, is_critical, type_eff) -> list[int]:
    mods: list[int] = []
    ds = f.defender_side
    screen = 2732 if f.game_type != "singles" else 2048
    if ds.reflect and move.category == "Physical" and not is_critical and not ds.aurora_veil:
        mods.append(screen)
    elif ds.light_screen and move.category == "Special" and not is_critical and not ds.aurora_veil:
        mods.append(screen)
    if ds.aurora_veil and not is_critical:
        mods.append(screen)
    if a.has_ability("Sniper") and is_critical:
        mods.append(6144)
    if d.has_ability("Multiscale") and d.hp == d.max_hp:
        mods.append(2048)
    if (
        d.has_ability("Fluffy", "Aura Guard")
        and "contact" in move.flags
        and not a.has_ability("Long Reach")
    ):
        mods.append(2048)
    elif d.has_ability("Punk Rock") and "sound" in move.flags:
        mods.append(2048)
    if d.has_ability("Solid Rock", "Filter") and type_eff > 1:
        mods.append(3072)
    if ds.friend_guard:
        mods.append(3072)
    if d.has_ability("Fluffy") and move_type == "Fire":
        mods.append(8192)
    if a.has_item("Expert Belt") and type_eff > 1:
        mods.append(4915)
    elif a.has_item("Life Orb"):
        mods.append(5324)
    berry = BERRY_RESIST_TYPE.get(d.item)
    if (
        berry == move_type
        and (type_eff > 1 or move_type == "Normal")
        and not a.has_ability("Unnerve")
    ):
        mods.append(1024 if d.has_ability("Ripen") else 2048)
    return mods


# ── building inputs from plain dicts (golden set, fixtures, agent tool calls) ──


def combatant_from_spec(facts: Facts, spec: dict) -> Combatant:
    """spec: {species, nature?, sp?: {stat: n}, ability?, item?, boosts?, status?, cur_hp?}.

    Defaults mirror @smogon/calc so fixtures compare like for like: first
    listed ability, no item, neutral nature (Serious), 0 SP.
    """
    species = facts.species(spec["species"])
    if species is None:
        raise UnsupportedCalculation(f"unknown Pokémon {spec['species']!r}")
    nature = facts.nature(spec.get("nature", "Serious"))
    if nature is None:
        raise UnsupportedCalculation(f"unknown nature {spec.get('nature')!r}")
    boosts = dict.fromkeys(STATS[1:], 0) | spec.get("boosts", {})
    return Combatant(
        species=species,
        raw_stats=calc_stats(species.base_stats, spec.get("sp", {}), nature),
        ability=spec.get("ability", species.abilities[0]),
        item=spec.get("item", ""),
        boosts=boosts,
        status=spec.get("status", ""),
        cur_hp=spec.get("cur_hp"),
        ability_on=spec.get("ability_on", False),
        allies_fainted=spec.get("allies_fainted", 0),
    )


def field_from_spec(spec: dict) -> FieldState:
    return FieldState(
        game_type=spec.get("game_type", "doubles"),
        weather=spec.get("weather"),
        terrain=spec.get("terrain"),
        attacker_side=Side(**spec.get("attacker_side", {})),
        defender_side=Side(**spec.get("defender_side", {})),
    )


def calculate_from_spec(facts: Facts, spec: dict) -> DamageResult:
    """spec: {attacker, defender, move, field?, crit?}; `spread: false` means a
    single-target hit (calculated as singles, like @smogon/calc)."""
    move = facts.move(spec["move"])
    if move is None:
        raise UnsupportedCalculation(f"unknown move {spec['move']!r}")
    field_spec = dict(spec.get("field", {}))
    if spec.get("spread") is False:
        field_spec["game_type"] = "singles"
    return calculate(
        facts,
        combatant_from_spec(facts, spec["attacker"]),
        combatant_from_spec(facts, spec["defender"]),
        move,
        field_from_spec(field_spec),
        is_crit=spec.get("crit", False),
    )
