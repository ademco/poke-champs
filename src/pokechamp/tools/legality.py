"""Team legality for the live regulation, from the structured facts.

Returns machine-readable problem codes (graded exactly by the golden set) plus
a human-readable message for each. Rules come from the `formats` table and the
validator-checked learnsets, so the LLM never decides what is legal.

Reporting choice: when a Pokémon itself is illegal or unknown, we report that
one root cause and skip its moves/ability. Listing four "can't learn" errors
for a Pokémon that can't be used at all is noise. Its *item* is still checked,
because an item's legality doesn't depend on who holds it.
"""

from collections import Counter
from dataclasses import dataclass

from pokechamp.facts import to_id
from pokechamp.tools.repo import STATS, Facts
from pokechamp.tools.team_parser import PokemonSet

MAX_NICKNAME = 18  # Showdown's team validator limit


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


def _item_problems(facts: Facts, s: PokemonSet) -> list[Problem]:
    # Independent of the holder, so it's reported even when the Pokémon is
    # illegal: you'd still need to swap the item after swapping the Pokémon.
    if not s.item:
        return []
    item = facts.item(s.item)
    if item is None:
        return [Problem(f"item_not_found:{s.item}", f"No item called {s.item!r} exists.")]
    if not item.legal:
        return [
            Problem(
                f"item_illegal:{item.name}",
                f"{item.name} is not available in Pokémon Champions (Reg {facts.regulation}).",
            )
        ]
    return []


def validate_set(facts: Facts, s: PokemonSet, sp_total: int, sp_max: int) -> list[Problem]:
    probs = _item_problems(facts, s)
    # Also holder-independent. (A pasted prompt injection usually lives in the
    # nickname, and is usually far over the limit.)
    if s.nickname and len(s.nickname) > MAX_NICKNAME:
        probs.append(
            Problem(
                f"nickname_too_long:{s.species}",
                f"{s.species}'s nickname is {len(s.nickname)} characters (max {MAX_NICKNAME}).",
            )
        )
    species = facts.species(s.species)
    if species is None:
        return [
            Problem(f"species_not_found:{s.species}", f"No Pokémon called {s.species!r} exists."),
            *probs,
        ]
    # A battle-only form written with its own trigger item ("Garchomp-Mega-Z @
    # Garchompite Z") is accepted, as Showdown does: it's the base Pokémon that
    # transforms in battle. Its abilities count from either form.
    allowed_abilities = set(species.abilities)
    if species.battle_only:
        holds_trigger = bool(
            species.required_item and s.item and to_id(s.item) == to_id(species.required_item)
        )
        base = facts.species(species.base_species)
        if not holds_trigger or base is None:
            stone = f" (hold {species.required_item})" if species.required_item else ""
            return [
                Problem(
                    f"battle_only_species:{species.name}",
                    f"{species.name} only appears in battle; "
                    f"register {species.base_species}{stone}.",
                ),
                *probs,
            ]
        allowed_abilities |= set(base.abilities)
        species = base
    if not species.legal:
        return [Problem(f"species_illegal:{species.name}", species.illegal_reason or ""), *probs]

    who = species.name
    if s.ability and to_id(s.ability) not in {to_id(a) for a in allowed_abilities}:
        probs.append(
            Problem(
                f"ability_invalid:{who}:{s.ability}",
                f"{who} can't have {s.ability}; options: {', '.join(sorted(allowed_abilities))}.",
            )
        )

    if s.nature and facts.nature(s.nature) is None:
        probs.append(Problem(f"nature_not_found:{who}:{s.nature}", f"Unknown nature {s.nature!r}."))

    if not s.moves:
        probs.append(Problem(f"no_moves:{who}", f"{who} has no moves."))
    if len(s.moves) > 4:
        probs.append(Problem(f"too_many_moves:{who}", f"{who} has {len(s.moves)} moves (max 4)."))
    learnset = facts.learnset(species.id)
    for move_name, n in Counter(to_id(m) for m in s.moves).items():
        if n > 1:
            probs.append(Problem(f"duplicate_move:{who}:{move_name}", f"{who} repeats a move."))
    for move_name in s.moves:
        move = facts.move(move_name)
        if move is None:
            probs.append(
                Problem(
                    f"move_not_found:{who}:{move_name}", f"No move called {move_name!r} exists."
                )
            )
        elif move.id not in learnset:
            probs.append(
                Problem(
                    f"move_not_learnable:{who}:{move.name}",
                    f"{who} can't learn {move.name} in Pokémon Champions (Reg {facts.regulation}).",
                )
            )

    for stat, value in s.sp.items():
        if value > sp_max:
            probs.append(
                Problem(
                    f"sp_stat_over_{sp_max}:{who}:{stat}",
                    f"{who} has {value} SP in {stat} (max {sp_max}).",
                )
            )
    total = sum(s.sp.values())
    if total > sp_total:
        probs.append(
            Problem(
                f"sp_total_over_{sp_total}:{who}:{total}",
                f"{who} has {total} SP in total (max {sp_total}).",
            )
        )
    for stat in STATS:
        if s.ivs.get(stat, 31) != 31:
            probs.append(
                Problem(
                    f"iv_not_31:{who}:{stat}", f"IVs are fixed at 31 in Champions ({who} {stat})."
                )
            )
    return probs


def validate_team(
    facts: Facts,
    sets: list[PokemonSet],
    game_type: str = "doubles",
    ignore_team_size: bool = False,
) -> list[Problem]:
    fmt = facts.format(game_type)
    probs: list[Problem] = []
    for s in sets:
        probs.extend(validate_set(facts, s, fmt.sp_total, fmt.sp_max_per_stat))

    if not ignore_team_size and len(sets) < fmt.team_size:
        probs.append(
            Problem(
                f"team_too_small:{len(sets)}",
                f"Ranked needs {fmt.team_size} Pokémon; got {len(sets)}.",
            )
        )
    if len(sets) > fmt.team_size:
        probs.append(Problem(f"team_too_large:{len(sets)}", f"At most {fmt.team_size} Pokémon."))

    if fmt.species_clause:
        bases = Counter(
            (facts.species(s.species).base_species if facts.species(s.species) else s.species)
            for s in sets
        )
        for base, n in bases.items():
            if n > 1:
                probs.append(Problem(f"duplicate_species:{base}", f"Species Clause: {n}x {base}."))
    if fmt.item_clause:
        items = Counter(
            (facts.item(s.item).name if facts.item(s.item) else s.item) for s in sets if s.item
        )
        for item, n in items.items():
            if n > 1:
                probs.append(
                    Problem(f"duplicate_item:{item}", f"Item Clause: {item} is used {n} times.")
                )
    return probs
