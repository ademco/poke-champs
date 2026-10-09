"""Team analyzer (snapshot facts, no DB): stats and weaknesses match the golden set."""

from pokechamp.analyze import analyze_team, render
from pokechamp.evals.golden_set import load_golden_set
from pokechamp.tools.repo import SnapshotFacts


def team_text(case_id):
    case = next(c for c in load_golden_set().cases if c.id == case_id)
    return case.input.split("\n", 1)[1]


def test_team_001_report():
    r = analyze_team(SnapshotFacts(), team_text("team-001"))
    assert r.legal and len(r.members) == 6
    inc = r.members[0]
    assert inc.name == "Incineroar" and inc.stats["hp"] == 202
    scarf = next(m for m in r.members if m.item == "Choice Scarf")
    assert scarf.speed == scarf.stats["spe"] * 3 // 2  # Scarf applied
    assert scarf.speed_tailwind == scarf.speed * 2
    text = render(r)
    assert "Legality: LEGAL" in text and "Garchomp-Mega-Z" in text


def test_illegal_team_reports_problems_and_tera_note():
    r = analyze_team(SnapshotFacts(), team_text("team-004"))
    text = render(r)
    assert not r.legal or r.warnings
    assert "Tera" in text or any("Tera" in w for w in r.warnings)
