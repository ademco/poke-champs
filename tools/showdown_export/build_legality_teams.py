"""Write tests/fixtures/legality_teams.json: the golden-set teams plus edge cases.

Showdown's TeamValidator then judges each team (validate_teams.js), and
tests/test_legality.py checks that our Python validator agrees with it.
Run: python tools/showdown_export/build_legality_teams.py
"""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def mon(species, item, ability, moves, sp="32 HP / 32 Atk / 2 Def", nature="Adamant", extra=""):
    lines = [f"{species} @ {item}" if item else species, f"Ability: {ability}", f"EVs: {sp}"]
    lines.append(f"{nature} Nature")
    if extra:
        lines.append(extra)
    return "\n".join(lines + [f"- {m}" for m in moves])


def team(*sets):
    return "\n\n".join(sets)


def strip_preamble(text: str) -> str:
    """Drop leading prose ("Analyze this team:") that isn't part of a set.

    Showdown's importer would read it as a Pokémon; our parser skips it. We
    hand Showdown only the team so both validators judge the same input.
    """
    blocks = [b for b in text.split("\n\n") if b.strip()]
    while blocks and not any(
        ln.strip().startswith(("-", "Ability:", "EVs:")) for ln in blocks[0].splitlines()[1:]
    ):
        blocks.pop(0)
    return "\n\n".join(blocks)


FAST = "2 HP / 32 Atk / 32 Spe"
BASE = [
    mon("Incineroar", "Sitrus Berry", "Intimidate", ["Fake Out", "Parting Shot", "Flare Blitz", "Protect"]),
    mon("Sneasler", "White Herb", "Unburden", ["Fake Out", "Dire Claw", "Close Combat", "Protect"], FAST, "Jolly"),
    mon("Garchomp", "Garchompite Z", "Rough Skin", ["Dragon Claw", "Earthquake", "Rock Slide", "Protect"], FAST, "Jolly"),
    mon("Rillaboom", "Choice Scarf", "Grassy Surge", ["Grassy Glide", "Wood Hammer", "U-turn", "High Horsepower"], FAST, "Jolly"),
    mon("Whimsicott", "Focus Sash", "Prankster", ["Tailwind", "Moonblast", "Encore", "Protect"], "2 HP / 32 SpA / 32 Spe", "Timid"),
    mon("Kingambit", "Black Glasses", "Defiant", ["Kowtow Cleave", "Sucker Punch", "Iron Head", "Protect"]),
]  # fmt: skip
GAMBIT_MOVES = ["Kowtow Cleave", "Sucker Punch", "Iron Head", "Protect"]
CHOMP_MOVES = ["Dragon Claw", "Earthquake", "Rock Slide", "Protect"]


def swap(i, s):
    return team(*[s if j == i else b for j, b in enumerate(BASE)])


EXTRAS = {
    "legal-base": team(*BASE),
    "bad-ability": swap(2, mon("Garchomp", "Garchompite Z", "Intimidate", CHOMP_MOVES, FAST, "Jolly")),
    "unlearnable-move": swap(2, mon("Garchomp", "Garchompite Z", "Rough Skin", ["Dragon Claw", "Earthquake", "Spore", "Protect"], FAST, "Jolly")),
    "battle-only-mega-written": swap(2, mon("Garchomp-Mega-Z", "Garchompite Z", "Levitate", CHOMP_MOVES, FAST, "Jolly")),
    "species-clause": swap(5, mon("Garchomp", "Life Orb", "Rough Skin", CHOMP_MOVES, FAST, "Jolly")),
    "item-clause": swap(5, mon("Kingambit", "Sitrus Berry", "Defiant", GAMBIT_MOVES)),
    "restricted-legendary": swap(5, mon("Calyrex", "Leftovers", "Unnerve", ["Protect", "Psychic", "Giga Drain", "Leech Seed"], "32 HP / 32 SpA / 2 Def", "Modest")),
    "mythical": swap(5, mon("Mew", "Leftovers", "Synchronize", ["Protect", "Psychic", "Will-O-Wisp", "Transform"], "32 HP / 32 SpA / 2 Def", "Modest")),
    "made-up-move": swap(5, mon("Kingambit", "Black Glasses", "Defiant", ["Kowtow Cleave", "Shadow Surge", "Iron Head", "Protect"])),
    "five-moves": swap(5, mon("Kingambit", "Black Glasses", "Defiant", [*GAMBIT_MOVES, "Swords Dance"])),
    "ivs-not-31": swap(5, mon("Kingambit", "Black Glasses", "Defiant", GAMBIT_MOVES, extra="IVs: 0 Spe")),
    "sp-67": swap(5, mon("Kingambit", "Black Glasses", "Defiant", GAMBIT_MOVES, sp="32 HP / 32 Atk / 3 Def")),
    "sp-66-exact": swap(5, mon("Kingambit", "Black Glasses", "Defiant", GAMBIT_MOVES, sp="32 HP / 32 Atk / 2 Def")),
    "banned-item": swap(5, mon("Kingambit", "Choice Band", "Defiant", GAMBIT_MOVES)),
    "unknown-item": swap(5, mon("Kingambit", "Mega Banana", "Defiant", GAMBIT_MOVES)),
    "nonmatching-mega-stone": swap(0, mon("Incineroar", "Garchompite", "Intimidate", ["Fake Out", "Parting Shot", "Flare Blitz", "Protect"])),
    "five-pokemon": team(*BASE[:5]),
    "cosmetic-form": swap(5, mon("Vivillon-Fancy", "Black Glasses", "Compound Eyes", ["Hurricane", "Sleep Powder", "Protect", "Bug Buzz"], "32 HP / 32 SpA / 2 Def", "Modest")),
    "duplicate-move": swap(5, mon("Kingambit", "Black Glasses", "Defiant", ["Kowtow Cleave", "Kowtow Cleave", "Iron Head", "Protect"])),
}  # fmt: skip


def main() -> None:
    golden = {
        c["id"]: c for c in yaml.safe_load((ROOT / "evals/golden_set.yaml").read_text())["cases"]
    }
    teams = [
        {
            "id": f"golden-{cid}",
            "game_type": golden[cid]["game_type"],
            "text": strip_preamble(golden[cid]["input"]),
        }
        for cid in ("team-001", "team-002", "team-003", "team-004", "team-005", "team-006")
    ]
    teams += [{"id": k, "game_type": "doubles", "text": v} for k, v in EXTRAS.items()]
    teams.append({"id": "legal-base-singles", "game_type": "singles", "text": team(*BASE)})
    out = ROOT / "tests/fixtures/legality_teams.json"
    out.write_text(json.dumps({"teams": teams}, indent=1) + "\n")
    print(f"wrote {len(teams)} teams to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
