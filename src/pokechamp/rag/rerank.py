"""Rerankers: rescore a short candidate list by reading query and chunk together.

The embedder (a "bi-encoder") turns the question and each chunk into vectors
*separately*, which is what makes searching a whole index fast, but it never
sees the two texts side by side. A cross-encoder takes the pair as one input
and outputs a relevance score, so it can notice that "how long" asks for a
duration or that a chunk is about the wrong move. It is far too slow to run
over every chunk, so it only reorders the top candidates from hybrid search.

Implementations:
  - CrossEncoderReranker: Xenova/ms-marco-MiniLM-L-6-v2 through fastembed
    (ONNX, CPU). 22M parameters, ~80 MB download, Apache-2.0. Chosen as the
    smallest option for the 8 GB Mac; peak memory is measured in CI.
  - OverlapReranker: word-overlap scoring, a test double (no download).
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from pokechamp.rag.embeddings import MODEL_CACHE

if TYPE_CHECKING:
    from pokechamp.rag.search import Hit

DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, hits: Sequence["Hit"], k: int) -> list["Hit"]: ...


def _top_k(hits: Sequence["Hit"], scores: Sequence[float], k: int) -> list["Hit"]:
    # Stable sort: equal scores keep the incoming (hybrid) order.
    order = sorted(range(len(hits)), key=lambda i: -scores[i])[:k]
    return [replace(hits[i], score=float(scores[i])) for i in order]


class CrossEncoderReranker:
    def __init__(self, model: str = DEFAULT_RERANKER, batch_size: int = 32):
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # heavy, lazy

        self.name = model
        self._batch_size = batch_size
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        self._model = TextCrossEncoder(model_name=model, cache_dir=str(MODEL_CACHE))

    def rerank(self, query: str, hits: Sequence["Hit"], k: int) -> list["Hit"]:
        if not hits:
            return []
        scores = list(
            self._model.rerank(query, [h.text for h in hits], batch_size=self._batch_size)
        )
        return _top_k(hits, scores, k)


class OverlapReranker:
    """Scores by the fraction of query words found in the chunk (tests only)."""

    name = "overlap-test-reranker"

    def rerank(self, query: str, hits: Sequence["Hit"], k: int) -> list["Hit"]:
        words = set(re.findall(r"[a-z0-9]+", query.lower()))
        scores = [
            len(words & set(re.findall(r"[a-z0-9]+", h.text.lower()))) / (len(words) or 1)
            for h in hits
        ]
        return _top_k(hits, scores, k)
