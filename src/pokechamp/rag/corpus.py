"""Build the RAG corpus: the unstructured text the assistant can search.

Two sources today (both approved in docs/DATA_SOURCES.md):
  - Showdown descriptions of legal moves, abilities and items (MIT).
  - Project-authored mechanics notes in data/corpus/notes/, each citing the
    Showdown code it was verified from.

Design rule: corpus text explains *what things do*. Numbers that tools own
(base power, accuracy, stats, legality) are deliberately left out of entity
documents, so the model is pushed to call a tool for them instead of quoting
numbers out of a retrieved passage.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from pokechamp.ingest.snapshot import Snapshot, load_snapshot
from pokechamp.sources import SOURCES

NOTES_DIR = Path(__file__).resolve().parents[3] / "data" / "corpus" / "notes"

# Shown in a description when Champions changes the behavior and Showdown has
# no Champions-specific text: honest about possibly-stale prose.
STALE_WARNING = (
    "Note: Pokémon Champions changes how this {kind} works, and this description "
    "comes from the main-series games, so details may differ."
)


@dataclass(frozen=True)
class Document:
    doc_id: str  # stable: "showdown:move:earthquake", "notes:stat-points"
    title: str
    doc_type: str  # "move" | "ability" | "item" | "mechanics_note"
    source: str  # key in SOURCES
    license: str
    regulation: str
    retrieved_at: datetime
    ref: str  # where in the source this came from
    text: str
    metadata: dict = field(default_factory=dict)


def _entity_docs(snap: Snapshot) -> list[Document]:
    reg = snap.meta.regulation
    usable_abilities = {
        a for s in snap.species if s.legal for a in s.abilities.values()
    }  # abilities no legal Pokémon has are noise for a Champions assistant
    docs = []
    tables = (
        ("move", [m for m in snap.moves if m.legal], "data/text/moves.ts"),
        (
            "ability",
            [a for a in snap.abilities if a.name in usable_abilities],
            "data/text/abilities.ts",
        ),
        ("item", [i for i in snap.items if i.legal], "data/text/items.ts"),
    )
    for kind, rows, ref in tables:
        for row in rows:
            body = row.desc or row.short_desc
            if not body:
                continue
            header = f"{row.name} ({kind}"
            if kind == "move":
                header += f", {row.type}-type {row.category.lower()}"
            header += ")"
            stale = row.behavior_changed and not row.champions_text
            text = f"{header}. {body}"
            if stale:
                text += " " + STALE_WARNING.format(kind=kind)
            docs.append(
                Document(
                    doc_id=f"showdown:{kind}:{row.id}",
                    title=row.name,
                    doc_type=kind,
                    source="showdown",
                    license=SOURCES["showdown"].license,
                    regulation=reg,
                    retrieved_at=snap.meta.exported_at,
                    ref=f"{ref}#{row.id} (showdown@{snap.meta.showdown_commit[:10]})",
                    text=text,
                    metadata={
                        "behavior_changed": row.behavior_changed,
                        "champions_text": row.champions_text,
                    },
                )
            )
    return docs


def _parse_note(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path.name}: missing front matter")
    _, front, body = raw.split("---\n", 2)
    return yaml.safe_load(front), body.strip()


def _note_docs(notes_dir: Path) -> list[Document]:
    docs = []
    for path in sorted(notes_dir.glob("*.md")):
        meta, body = _parse_note(path)
        for ref in meta["sources"]:
            if ref["source"] not in SOURCES:
                raise ValueError(f"{path.name}: unknown source {ref['source']!r}")
        written = meta["written"]
        written = written if isinstance(written, date) else date.fromisoformat(written)
        docs.append(
            Document(
                doc_id=f"notes:{path.stem}",
                title=meta["title"],
                doc_type="mechanics_note",
                source="project_notes",
                license=SOURCES["project_notes"].license,
                regulation=meta["regulation"],
                retrieved_at=datetime(written.year, written.month, written.day),
                ref=f"data/corpus/notes/{path.name}",
                text=body,
                metadata={"cites": meta["sources"]},
            )
        )
    return docs


def build_corpus(snap: Snapshot | None = None, notes_dir: Path = NOTES_DIR) -> list[Document]:
    snap = snap or load_snapshot()
    return _entity_docs(snap) + _note_docs(notes_dir)
