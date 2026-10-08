"""Corpus and chunking tests (no database, no model)."""

from datetime import datetime

import pytest

from pokechamp.rag.chunking import MAX_WORDS, chunk_document
from pokechamp.rag.corpus import STALE_WARNING, Document, build_corpus
from pokechamp.regulations import current_regulation
from pokechamp.sources import SOURCES


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def by_id(corpus):
    return {d.doc_id: d for d in corpus}


# ── corpus ─────────────────────────────────────────────────────────────────


def test_doc_ids_are_unique(corpus):
    assert len({d.doc_id for d in corpus}) == len(corpus)


def test_every_document_has_provenance(corpus):
    live = current_regulation().code
    for d in corpus:
        assert SOURCES[d.source].status == "approved", d.doc_id
        assert d.license and d.ref and d.retrieved_at, d.doc_id
        assert d.regulation == live, d.doc_id


def test_only_champions_relevant_entities(by_id):
    assert "showdown:move:fakeout" in by_id
    assert "showdown:move:terablast" not in by_id  # not in Champions
    assert "showdown:item:choicespecs" not in by_id  # not in Champions
    assert "showdown:item:lifeorb" in by_id
    assert "showdown:ability:intimidate" in by_id


def test_stale_descriptions_are_flagged(by_id):
    warning = STALE_WARNING.format(kind="move")
    # Encore's behavior changes in Champions and Showdown has no Champions text for it.
    assert warning in by_id["showdown:move:encore"].text
    # Moonblast changed too, but Showdown wrote a Champions-specific description.
    assert "10% chance" in by_id["showdown:move:moonblast"].text
    assert warning not in by_id["showdown:move:moonblast"].text
    assert warning not in by_id["showdown:move:earthquake"].text


def test_notes_cite_registered_sources(corpus):
    notes = [d for d in corpus if d.doc_type == "mechanics_note"]
    assert len(notes) >= 8
    for note in notes:
        assert note.metadata["cites"], note.doc_id
        assert all(c["source"] in SOURCES for c in note.metadata["cites"]), note.doc_id


def test_no_unlicensed_prose_in_the_corpus(corpus):
    # Bulbapedia (CC BY-NC-SA) and other prose sources aren't approved yet.
    assert {d.source for d in corpus} <= {"showdown", "project_notes"}


# ── chunking ───────────────────────────────────────────────────────────────


def _doc(text: str, doc_type: str = "mechanics_note") -> Document:
    return Document(
        doc_id="t:doc", title="Title", doc_type=doc_type, source="project_notes",
        license="x", regulation="M-C", retrieved_at=datetime(2026, 10, 8), ref="r", text=text,
    )  # fmt: skip


def test_notes_split_at_headings_with_context_prefix():
    chunks = chunk_document(_doc("# Title\n\n## Sleep\nLasts two turns.\n\n## Freeze\nThaws."))
    assert [c.heading for c in chunks] == ["Title > Sleep", "Title > Freeze"]
    assert chunks[0].text == "Title > Sleep\nLasts two turns."


def test_long_sections_split_with_sentence_overlap():
    sentences = [f"Sentence number {i} talks about stat points in detail here." for i in range(60)]
    chunks = chunk_document(_doc("## Long\n" + " ".join(sentences)))
    assert len(chunks) > 1
    heading_words = len("Title > Long".split())
    assert all(c.word_count <= MAX_WORDS + heading_words for c in chunks)
    # the last sentence of one chunk opens the next (overlap)
    first_tail = chunks[0].text.split(". ")[-1].rstrip(".")
    assert first_tail in chunks[1].text


def test_entity_descriptions_are_one_chunk_without_prefix():
    (chunk,) = chunk_document(_doc("Earthquake (move). Hits all adjacent.", doc_type="move"))
    assert chunk.text == "Earthquake (move). Hits all adjacent."


def test_chunk_ids_and_hashes_are_stable():
    a = chunk_document(_doc("## A\nOne.\n\n## B\nTwo."))
    b = chunk_document(_doc("## A\nOne.\n\n## B\nTwo."))
    assert [(c.chunk_id, c.content_hash) for c in a] == [(c.chunk_id, c.content_hash) for c in b]
    assert [c.chunk_id for c in a] == ["t:doc#0", "t:doc#1"]


def test_whole_corpus_chunks_within_model_limits(corpus):
    chunks = [c for d in corpus for c in chunk_document(d)]
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    # bge-small reads at most 512 tokens (~390 words); stay well under.
    assert max(c.word_count for c in chunks) <= 300
    assert all(c.text.strip() for c in chunks)
