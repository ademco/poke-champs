"""Whitelist of data sources. Nothing gets ingested unless it is registered here.

Each entry mirrors a row in docs/DATA_SOURCES.md (a test keeps the two in sync).
`status` records whether we may ingest it yet:
  - "approved": license/terms checked and permit our use.
  - "pending": terms not verified yet; do not ingest.
  - "reference": used only to cross-check, never ingested as a primary source.
"""

from dataclasses import dataclass
from typing import Literal

Status = Literal["approved", "pending", "reference"]


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    license: str
    use: str
    status: Status


SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            "showdown",
            "Pokémon Showdown (data/ and data/mods/champions*)",
            "https://github.com/smogon/pokemon-showdown",
            "MIT",
            "Base facts, Champions legality, learnsets, items, move changes, mechanics code",
            "approved",
        ),
        Source(
            "smogon_calc",
            "@smogon/calc damage calculator",
            "https://github.com/smogon/damage-calc",
            "MIT",
            "Reference outputs to test our Python damage calc against",
            "approved",
        ),
        Source(
            "project_notes",
            "PokéChamp mechanics notes (data/corpus/notes/)",
            "https://github.com/ademco/poke-champs/tree/main/data/corpus/notes",
            "Project-authored; facts summarized from the MIT sources each note cites",
            "Short mechanics explanations for RAG, each citing the code it was verified from",
            "approved",
        ),
        Source(
            "community_data",
            "otterlyclueless/pokemon-champions-data",
            "https://github.com/otterlyclueless/pokemon-champions-data",
            "CC BY 4.0 (compiler's contributions; parts scraped from Serebii)",
            "Cross-check only; stale (2026-04-16, Reg M-A)",
            "reference",
        ),
        Source(
            "bulbapedia",
            "Bulbapedia mechanics pages",
            "https://bulbapedia.bulbagarden.net",
            "CC BY-NC-SA 2.5",
            "Unstructured mechanics text for RAG, with attribution",
            "pending",
        ),
        Source(
            "smogon_stats",
            "Smogon monthly usage stats (chaos JSON)",
            "https://www.smogon.com/stats/",
            "No explicit license found yet",
            "Usage %, common sets, teammates",
            "pending",
        ),
        Source(
            "pikalytics",
            "Pikalytics",
            "https://www.pikalytics.com",
            "Terms not verified",
            "Usage stats only if terms allow",
            "pending",
        ),
        Source(
            "limitless",
            "Limitless VGC (API)",
            "https://docs.limitlesstcg.com",
            "Terms not verified; public API, keys for public projects",
            "Tournament teams only if terms allow",
            "pending",
        ),
    ]
}
