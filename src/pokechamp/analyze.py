"""Team analysis: paste a Showdown team, get a report. Deterministic, no LLM.

Everything here is computed by the phase-2 tools from the Postgres/snapshot
facts: legality, final stats (Stat Point formula), Speed with Tailwind and
Choice Scarf, and shared type weaknesses. No model is involved, so no number
can be hallucinated, and it works offline with no API key.

Usage: python -m pokechamp.analyze team.txt [--singles]
       (or `make analyze FILE=team.txt`; `-` reads stdin)
"""

import argparse
import sys
from dataclasses import dataclass, field

from pokechamp.tools.legality import Problem, validate_team
from pokechamp.tools.repo import Facts, SpeciesInfo
from pokechamp.tools.speed import SpeedContext, final_speed
from pokechamp.tools.stats import StatError, calc_stats
from pokechamp.tools.team_parser import PokemonSet, parse_team
from pokechamp.tools.typechart import team_weaknesses

STAT_LABELS = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}


@dataclass
class MemberReport:
    name: str  # as written ("Garchomp"), or the Mega form it becomes
    types: tuple[str, ...]
    item: str | None
    ability: str | None
    nature: str
    stats: dict[str, int]
    sp_used: int
    speed: int  # in battle, with its own item/ability (e.g. Scarf)
    speed_tailwind: int
    mega: "MemberReport | None" = None


@dataclass
class TeamReport:
    regulation: str
    game_type: str
    problems: list[Problem]
    members: list[MemberReport]
    weaknesses: list[dict]  # worst shared weaknesses
    warnings: list[str] = field(default_factory=list)  # parser notes, e.g. Tera lines

    @property
    def legal(self) -> bool:
        return not self.problems

    def to_json(self) -> dict:
        def member(m: MemberReport) -> dict:
            d = {k: v for k, v in m.__dict__.items() if k != "mega"}
            d["mega"] = member(m.mega) if m.mega else None
            return d

        return {
            "regulation": self.regulation,
            "game_type": self.game_type,
            "legal": self.legal,
            "problems": [{"code": p.code, "message": p.message} for p in self.problems],
            "members": [member(m) for m in self.members],
            "weaknesses": self.weaknesses,
            "warnings": self.warnings,
            "source": "Computed from Pokémon Showdown data (MIT) by deterministic tools.",
        }


def _member(
    facts: Facts, s: PokemonSet, sp: SpeciesInfo, warnings: list[str]
) -> MemberReport | None:
    nature = facts.nature(s.nature) if s.nature else None
    if s.nature and nature is None:
        warnings.append(f"{s.species}: unknown nature {s.nature!r}, assumed neutral")
    try:
        stats = calc_stats(sp.base_stats, s.sp, nature or (None, None))
    except StatError as exc:
        warnings.append(f"{s.species}: stats not computed ({exc})")
        return None
    ctx = SpeedContext(item=s.item, ability=s.ability)
    return MemberReport(
        name=sp.name,
        types=sp.types,
        item=s.item,
        ability=s.ability,
        nature=s.nature or "neutral",
        stats=stats,
        sp_used=sum(s.sp.values()),
        speed=final_speed(stats["spe"], ctx),
        speed_tailwind=final_speed(
            stats["spe"], SpeedContext(item=s.item, ability=s.ability, tailwind=True)
        ),
    )


def analyze_team(facts: Facts, text: str, game_type: str = "doubles") -> TeamReport:
    sets = parse_team(text)
    problems = validate_team(facts, sets, game_type)
    warnings = [f"{s.species}: {w}" for s in sets for w in s.warnings]
    members: list[MemberReport] = []
    for s in sets:
        sp = facts.species(s.species)
        if sp is None:
            continue  # legality already reports unknown species
        m = _member(facts, s, sp, warnings)
        if m is None:
            continue
        # Holding its Mega Stone: also report the Mega form (same SP and nature).
        stone = facts.item(s.item).mega_stone if s.item and facts.item(s.item) else None
        if stone and (mega_name := stone.get(sp.name)) and (mega := facts.species(mega_name)):
            m.mega = _member(facts, s, mega, warnings)
        members.append(m)

    # Weaknesses use the form each Pokémon battles in most of the time: the Mega
    # if it has one (it Mega Evolves on turn 1), else the base form.
    typed = [((m.mega or m).name, (m.mega or m).types) for m in members]
    weaknesses = [
        {
            "type": w.attacking_type,
            "weak": [{"member": n, "multiplier": x} for n, x in w.weak],
            "resist": [{"member": n, "multiplier": x} for n, x in w.resist],
        }
        for w in team_weaknesses(facts, typed)
        if len(w.weak) >= 2 and len(w.weak) > len(w.resist)
    ]
    return TeamReport(facts.regulation, game_type, problems, members, weaknesses, warnings)


def render(r: TeamReport) -> str:
    lines = [f"Team analysis, Regulation {r.regulation} {r.game_type}", ""]
    if r.legal:
        lines.append("Legality: LEGAL")
    else:
        lines.append(f"Legality: {len(r.problems)} problem(s)")
        lines += [f"  - {p.message}" for p in r.problems]
    for w in r.warnings:
        lines.append(f"  note: {w}")

    lines += ["", "Stats (level 50, IVs 31, your Stat Points and nature):"]
    for m in r.members:
        for form in (m, m.mega):
            if form is None:
                continue
            stats = " / ".join(f"{STAT_LABELS[k]} {v}" for k, v in form.stats.items())
            label = f"  {form.name} [{'/'.join(form.types)}]"
            lines.append(f"{label}: {stats}  ({m.sp_used}/66 SP)")

    lines += ["", "Speed order (fastest first; Tailwind doubles Speed):"]
    order = sorted(((m.mega or m) for m in r.members), key=lambda f: -f.speed)
    for f in order:
        item = f" @ {f.item}" if f.item else ""
        lines.append(f"  {f.speed:>4}  (Tailwind {f.speed_tailwind:>4})  {f.name}{item}")

    lines += ["", "Shared weaknesses (more weak than resistant; types only, abilities like"]
    lines += ["Levitate are not counted yet):"]
    if not r.weaknesses:
        lines.append("  none: no attacking type hits 2+ members super-effectively unchecked")
    for w in r.weaknesses:
        weak = ", ".join(f"{x['member']} x{x['multiplier']:g}" for x in w["weak"])
        resist = ", ".join(x["member"] for x in w["resist"]) or "nobody"
        lines.append(f"  {w['type']}: weak {weak}; resists: {resist}")
    lines += ["", "Source: Pokémon Showdown data (MIT), computed by deterministic tools."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a Showdown-format team")
    parser.add_argument("file", help="team text file, or - for stdin")
    parser.add_argument("--singles", action="store_true", help="BSS singles rules")
    args = parser.parse_args()
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    from pokechamp.db import connect
    from pokechamp.tools.repo import DbFacts

    with connect() as conn:
        report = analyze_team(DbFacts(conn), text, "singles" if args.singles else "doubles")
    print(render(report))


if __name__ == "__main__":
    main()
