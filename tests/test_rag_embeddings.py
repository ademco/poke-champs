"""Embedder tests. The real-model tests need the bge-small download: they're
skipped locally if it isn't available, and required in CI (REQUIRE_MODEL=1)."""

import math
import os

import pytest

from pokechamp.rag.embeddings import DIM, HashingEmbedder, cosine


def test_hashing_embedder_is_deterministic_and_normalized():
    e = HashingEmbedder()
    a, b = e.embed_documents(["Intimidate lowers Attack"] * 2)
    assert a == b and len(a) == DIM
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0)


def test_hashing_embedder_shares_words_not_meaning():
    # Documents the limitation that makes the real model necessary.
    e = HashingEmbedder()
    q = e.embed_query("lowers attack")
    assert cosine(q, e.embed_query("lowers the attack stat")) > cosine(
        q, e.embed_query("heals some HP")
    )
    # Synonyms share no words, so the hashing embedder sees no similarity.
    assert abs(cosine(e.embed_query("sleep"), e.embed_query("asleep drowsy"))) < 0.3


@pytest.fixture(scope="module")
def real_embedder():
    try:
        from pokechamp.rag.embeddings import FastEmbedEmbedder

        return FastEmbedEmbedder()
    except Exception as exc:  # no network / no cached model
        if os.environ.get("REQUIRE_MODEL") == "1":
            raise
        pytest.skip(f"embedding model not available: {type(exc).__name__}")


@pytest.mark.model
def test_real_model_dimension_and_semantics(real_embedder):
    q = real_embedder.embed_query(
        "Which ability lowers the opponent's Attack when it enters battle?"
    )
    docs = real_embedder.embed_documents(
        [
            "Intimidate (ability). On switch-in, this Pokemon lowers the Attack of "
            "opponents by 1 stage.",
            "Regenerator (ability). This Pokemon restores 1/3 of its maximum HP "
            "when it switches out.",
        ]
    )
    assert len(q) == DIM and all(len(d) == DIM for d in docs)
    assert cosine(q, docs[0]) > cosine(q, docs[1])
