"""Evidence: everything the model is allowed to use, each piece citable by id.

Two kinds, matching the project's core rule (facts from tables, prose from RAG):

  S1..Sn  chunks from hybrid search (phase 4): mechanics notes and Showdown
          descriptions. Prose; good for "how does X work".
  F1..Fn  fact cards from the Postgres tables, for Pokémon, moves and items the
          question names: types, base stats, base power, and whether each is
          legal in the live regulation. Exact values the model must not guess.

Fact cards come from *deterministic name linking*, not from the LLM choosing
a tool: scan the question for known names (longest match first). That covers
the common "is X legal / what is X's base power" questions cheaply. Phase 7's
agent adds real tool calls (stat, speed and damage calculation, team checks).
"""

import re
from dataclasses import dataclass

import psycopg

from pokechamp.facts import to_id
from pokechamp.rag.embeddings import Embedder
from pokechamp.rag.search import Hit, hybrid_search
from pokechamp.tools.repo import Facts, ItemInfo, MoveInfo, SpeciesInfo

MAX_FACT_CARDS = 6
MAX_WINDOW = 4  # longest name in words ("Will-O-Wisp" is one token; "Mega Garchomp Z" is 3)
STAT_LABELS = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}


@dataclass(frozen=True)
class Evidence:
    id: str  # "S1" (search chunk) or "F1" (fact card)
    kind: str  # "chunk" | "fact"
    title: str
    text: str
    source: str  # key in pokechamp.sources.SOURCES
    license: str
    ref: str  # where it came from, for the citation shown to the user
    regulation: str


def _words(question: str) -> list[str]:
    # Keep hyphens and apostrophes inside names (Will-O-Wisp, Farfetch'd), but
    # drop a trailing possessive: "Garchomp's" -> "Garchomp".
    words = re.findall(r"[\w][\w'’\-.]*", question)
    return [re.sub(r"['’]s$", "", w).rstrip(".-") for w in words]


def _candidates(window: list[str]) -> list[str]:
    ids = [to_id("".join(window))]
    # "Mega Garchomp Z" / "Mega Garchomp-Z" -> Showdown's "Garchomp-Mega-Z".
    if len(window) > 1 and window[0].lower() == "mega":
        rest = [p for w in window[1:] for p in w.split("-") if p]
        ids += [to_id("".join(rest) + "mega"), to_id(rest[0] + "mega" + "".join(rest[1:]))]
    return ids


def link_entities(facts: Facts, question: str) -> list[tuple[str, str]]:
    """Find known species/move/item names in the question: [(kind, id)], in order.

    Longest match wins, matches don't overlap. A one-word *move* must be
    capitalised, because many moves are everyday words ("protect my side",
    "rest", "growth"); species and items match in any case ("is amoonguss legal").
    """
    known = facts.entity_ids()
    words = _words(question)
    found: list[tuple[str, str]] = []
    i = 0
    while i < len(words):
        for size in range(min(MAX_WINDOW, len(words) - i), 0, -1):
            window = words[i : i + size]
            lowercase_word = size == 1 and not window[0][:1].isupper()
            match = next(
                (
                    (kind, cid)
                    for cid in _candidates(window)
                    for kind in known
                    if cid in known[kind] and not (lowercase_word and kind == "move")
                ),
                None,
            )
            if match:
                found.append(match)
                # A Mega Stone implies the Mega form: link that too, so the
                # model sees the Mega's stats instead of guessing them.
                if match[0] == "item" and (stone := facts.item(match[1]).mega_stone):
                    found += [("species", to_id(mega)) for mega in stone.values()]
                i += size
                break
        else:
            i += 1
    unique = list(dict.fromkeys(found))  # de-duplicate, keep order
    return unique[:MAX_FACT_CARDS]


def _legal(ok: bool, reg: str, reason: str | None = None, label: str = "Legal") -> str:
    if ok:
        return f"{label} in Regulation {reg}: yes."
    return f"{label} in Regulation {reg}: NO" + (f" ({reason.rstrip('.')})" if reason else "") + "."


def species_card(s: SpeciesInfo, reg: str) -> str:
    stats = " / ".join(f"{STAT_LABELS[k]} {v}" for k, v in s.base_stats.items())
    parts = [
        f"{s.name} (Pokémon). Type: {'/'.join(s.types)}. Base stats: {stats}.",
        f"Abilities: {', '.join(s.abilities)}.",
    ]
    if s.is_mega:
        parts.append(
            f"Mega Evolution of {s.base_species}; needs the held item {s.required_item};"
            " exists only during battle."
        )
    parts.append(_legal(s.legal, reg, s.illegal_reason))
    return " ".join(parts)


def move_card(m: MoveInfo, reg: str) -> str:
    power = f"base power {m.base_power}" if m.base_power else "no base power (status/variable)"
    return (
        f"{m.name} (move). Type: {m.type}. Category: {m.category}. {power.capitalize()}."
        f" Priority: {m.priority:+d}. {_legal(m.legal, reg, label='Usable')}"
    )


def item_card(it: ItemInfo, reg: str) -> str:
    text = f"{it.name} (item)."
    if it.mega_stone:
        pairs = ", ".join(f"{base} -> {mega}" for base, mega in it.mega_stone.items())
        text += f" Mega Stone: {pairs}."
    return f"{text} {_legal(it.legal, reg)}"


def fact_cards(facts: Facts, question: str) -> list[Evidence]:
    reg = facts.regulation
    cards = []
    for kind, cid in link_entities(facts, question):
        if kind == "species":
            obj, table = facts.species(cid), "species"
            text = species_card(obj, reg)
        elif kind == "move":
            obj, table = facts.move(cid), "moves"
            text = move_card(obj, reg)
        else:
            obj, table = facts.item(cid), "items"
            text = item_card(obj, reg)
        cards.append(
            Evidence(
                id=f"F{len(cards) + 1}",
                kind="fact",
                title=obj.name,
                text=text,
                source="showdown",
                license="MIT",
                ref=f"{table} table, id={cid} (structured data from Showdown)",
                regulation=reg,
            )
        )
    return cards


def chunk_evidence(hits: list[Hit]) -> list[Evidence]:
    return [
        Evidence(
            id=f"S{i}",
            kind="chunk",
            title=h.heading or h.title,
            text=h.text,
            source=h.source,
            license=h.license,
            ref=h.ref,
            regulation=h.regulation,
        )
        for i, h in enumerate(hits, start=1)
    ]


def gather(
    conn: psycopg.Connection, facts: Facts, embedder: Embedder, question: str, k: int = 5
) -> list[Evidence]:
    """Fact cards first (exact), then the top-k chunks from hybrid search."""
    hits = hybrid_search(conn, embedder, question, k, regulation=facts.regulation)
    return fact_cards(facts, question) + chunk_evidence(hits)
