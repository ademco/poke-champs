"""Split documents into retrieval-sized chunks.

Why chunk at all? Retrieval returns whole chunks. Too big, and one chunk mixes
several topics: its embedding becomes a blurry average and the LLM gets lots
of irrelevant text. Too small, and a chunk loses the context needed to answer.

Strategy, structure first:
  1. Split notes at markdown headings (## sections are natural topic units).
  2. If a section is still too long, split at paragraph, then sentence boundaries.
  3. Overlap: repeat the last sentence of the previous piece, so a fact that
     straddles a boundary is still retrievable from either side.
  4. Prefix every chunk with "Title > Section", so a chunk saying "It lasts one
     to three turns" still carries what "it" is. This is a cheap form of
     contextual chunking that helps both embeddings and keyword search.

Sizes are counted in words (~1.3 tokens per word for English). The embedding
model (bge-small) reads at most 512 tokens, and our target is far below that.
"""

import hashlib
import re
from dataclasses import dataclass

from pokechamp.rag.corpus import Document

MAX_WORDS = 160
OVERLAP_SENTENCES = 1


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # f"{doc_id}#{index}": stable across runs
    doc_id: str
    index: int
    heading: str  # "Title > Section"
    text: str  # what gets embedded and shown to the LLM (heading included)
    word_count: int
    content_hash: str  # detects changes between ingests


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")


def _words(text: str) -> int:
    return len(text.split())


def _sections(doc: Document) -> list[tuple[str, str]]:
    """(heading, body) pairs. Short entity descriptions are a single section."""
    if doc.doc_type != "mechanics_note":
        return [(doc.title, doc.text)]
    sections: list[tuple[str, str]] = []
    heading, lines = doc.title, []
    for line in doc.text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if "\n".join(lines).strip():
                sections.append((heading, "\n".join(lines).strip()))
            level, title = len(m.group(1)), m.group(2).strip()
            heading = doc.title if level == 1 else f"{doc.title} > {title}"
            lines = []
        else:
            lines.append(line)
    if "\n".join(lines).strip():
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def _split_long(body: str, max_words: int) -> list[str]:
    """Greedy packing of paragraphs, then sentences, with sentence overlap."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = " ".join(para.split())
        units.extend(_SENTENCE_END.split(para) if _words(para) > max_words else [para])
    pieces: list[list[str]] = [[]]
    for unit in units:
        current = pieces[-1]
        if current and _words(" ".join(current + [unit])) > max_words:
            pieces.append(current[-OVERLAP_SENTENCES:] + [unit] if OVERLAP_SENTENCES else [unit])
        else:
            current.append(unit)
    return [" ".join(p) for p in pieces if p]


def chunk_document(doc: Document, max_words: int = MAX_WORDS) -> list[Chunk]:
    chunks = []
    for heading, body in _sections(doc):
        parts = [body] if _words(body) <= max_words else _split_long(body, max_words)
        for part in parts:
            text = part if doc.doc_type != "mechanics_note" else f"{heading}\n{part}"
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#{index}",
                    doc_id=doc.doc_id,
                    index=index,
                    heading=heading,
                    text=text,
                    word_count=_words(text),
                    content_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
                )
            )
    return chunks
