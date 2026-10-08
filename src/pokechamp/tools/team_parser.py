"""Parse Showdown export text into structured sets.

Format (one block per Pokémon, blank line between blocks):
    Nickname (Species) (M) @ Item
    Ability: Intimidate
    Level: 50
    Tera Type: Fairy          <- not in Champions: kept as a warning
    EVs: 32 HP / 2 Atk         <- in Champions these numbers are Stat Points
    Adamant Nature
    - Fake Out

Security note: pasted text is untrusted. The parser only extracts fields; a
nickname such as "IGNORE PREVIOUS INSTRUCTIONS" is stored as a nickname string
and never interpreted. Lines it doesn't recognize become warnings, not errors,
so one odd line can't hide the rest of the team.
"""

import re
from dataclasses import dataclass, field

MAX_TEAM_TEXT = 20_000  # characters; far above any real team, stops pathological input
MAX_SETS = 24  # Showdown's own upper bound for custom games

_STAT_NAMES = {
    "hp": "hp", "atk": "atk", "def": "def", "spa": "spa", "spd": "spd", "spe": "spe",
    "satk": "spa", "sdef": "spd", "spatk": "spa", "spdef": "spd", "speed": "spe",
}  # fmt: skip


class TeamParseError(ValueError):
    pass


@dataclass
class PokemonSet:
    species: str
    nickname: str | None = None
    gender: str | None = None
    item: str | None = None
    ability: str | None = None
    nature: str | None = None
    level: int | None = None
    sp: dict[str, int] = field(default_factory=dict)  # from the "EVs:" line
    ivs: dict[str, int] = field(default_factory=dict)
    moves: list[str] = field(default_factory=list)
    tera_type: str | None = None  # parsed so we can say "Tera isn't in Champions"
    warnings: list[str] = field(default_factory=list)


def _parse_stat_line(text: str, where: str, warnings: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in text.split("/"):
        m = re.fullmatch(r"\s*(\d+)\s+([A-Za-z]+)\s*", part)
        stat = _STAT_NAMES.get(m.group(2).lower()) if m else None
        if not m or stat is None:
            warnings.append(f"could not read {where} entry {part.strip()!r}")
            continue
        out[stat] = int(m.group(1))
    return out


def _parse_header(line: str, s: PokemonSet) -> None:
    head, _, item = line.partition(" @ ")
    s.item = item.strip() or None
    head = head.strip()
    gm = re.search(r"\s\((M|F)\)$", head)
    if gm:
        s.gender = gm.group(1)
        head = head[: gm.start()].strip()
    # "Nickname (Species)": the species is the *last* parenthesised group.
    nm = re.fullmatch(r"(.*)\s\(([^()]+)\)", head)
    if nm:
        s.nickname, s.species = nm.group(1).strip() or None, nm.group(2).strip()
    else:
        s.species = head


def _parse_block(lines: list[str]) -> PokemonSet:
    s = PokemonSet(species="")
    _parse_header(lines[0], s)
    for raw in lines[1:]:
        line = raw.strip()
        key, sep, value = line.partition(":")
        value = value.strip()
        if line.startswith("-"):
            move = line.lstrip("-").strip()
            if move:
                s.moves.append(move)
        elif sep and key == "Ability":
            s.ability = value
        elif sep and key == "Level":
            s.level = int(value) if value.isdigit() else None
        elif sep and key == "EVs":
            s.sp = _parse_stat_line(value, "EVs/SP", s.warnings)
        elif sep and key == "IVs":
            s.ivs = _parse_stat_line(value, "IVs", s.warnings)
        elif sep and key == "Tera Type":
            s.tera_type = value
            s.warnings.append(
                "Tera Type line ignored: Terastallization is not in Pokémon Champions"
            )
        elif line.endswith(" Nature"):
            s.nature = line.removesuffix(" Nature").strip()
        elif sep and key in {"Shiny", "Happiness", "Pokeball", "Gigantamax", "Dynamax Level"}:
            continue  # cosmetic or not applicable; no effect on analysis
        else:
            s.warnings.append(f"unrecognized line ignored: {line[:80]!r}")
    return s


def parse_team(text: str) -> list[PokemonSet]:
    if len(text) > MAX_TEAM_TEXT:
        raise TeamParseError(f"team text is longer than {MAX_TEAM_TEXT} characters")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    # Drop preamble lines like "Analyze this team:" that precede the first set.
    # A real set's block has an Ability/EVs/Nature line or a "- move" line.
    sets = [
        _parse_block(b)
        for b in blocks
        if any(
            ln.strip().startswith(("-", "Ability:", "EVs:")) or ln.strip().endswith(" Nature")
            for ln in b[1:]
        )
    ]
    if not sets:
        raise TeamParseError("no Pokémon sets found in the text")
    if len(sets) > MAX_SETS:
        raise TeamParseError(f"more than {MAX_SETS} sets")
    return sets
