"""Embedders: text -> vector. One interface, swappable implementations.

An embedding model maps text to a point in a high-dimensional space (here 384
numbers) such that texts with similar meaning land close together. "Close" is
measured by cosine similarity: the angle between two vectors, ignoring length.
Retrieval then means "find the chunk vectors nearest to the question vector".

Implementations:
  - FastEmbedEmbedder: BAAI/bge-small-en-v1.5 through fastembed (ONNX runtime,
    no PyTorch). 33M parameters, ~130 MB download, runs on CPU. Used for real.
  - HashingEmbedder: a deterministic bag-of-words hash. No download, no
    meaning, only shared words. Used in unit tests so they run anywhere (this
    is a test double, like a mock repository in Spring tests). Never used for
    real retrieval.

The model name is stored with every chunk, because vectors from two different
models are not comparable: switching models means re-embedding everything.
"""

import hashlib
import math
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
MODEL_CACHE = Path(
    os.environ.get("POKECHAMP_MODEL_CACHE", Path.home() / ".cache" / "pokechamp" / "models")
)


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL, batch_size: int = 64):
        from fastembed import TextEmbedding  # imported lazily: heavy, and not needed by tests

        self.name = model
        self.dim = DIM
        self._batch_size = batch_size
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        self._model = TextEmbedding(model_name=model, cache_dir=str(MODEL_CACHE))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts), batch_size=self._batch_size)]

    def embed_query(self, text: str) -> list[float]:
        # fastembed embeds the query as-is (verified in fastembed 0.9.0 source:
        # no instruction prefix). BGE v1.5 is designed to work without one;
        # whether BGE's optional "Represent this sentence..." prefix helps on
        # our questions is a phase-4 experiment, measured, not assumed.
        return next(iter(self._model.query_embed(text))).tolist()


class HashingEmbedder:
    """Deterministic bag-of-words vectors for tests (signed feature hashing)."""

    name = "hashing-test-embedder"
    dim = DIM

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# BGE v1.5's optional instruction for short queries that retrieve passages
# (from the BAAI model card). Documents are embedded without it.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class PrefixedEmbedder:
    """Wraps an embedder and prepends an instruction to queries only.

    Keeps the wrapped model's name: the stored document vectors are unchanged,
    so the same index serves both variants (a phase-4 experiment).
    """

    def __init__(self, inner: Embedder, prefix: str = BGE_QUERY_INSTRUCTION):
        self._inner, self._prefix = inner, prefix
        self.name, self.dim = inner.name, inner.dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(self._prefix + text)


def get_embedder(kind: str = "fastembed") -> Embedder:
    if kind == "fastembed":
        return FastEmbedEmbedder()
    if kind == "hashing":
        return HashingEmbedder()
    raise ValueError(f"unknown embedder {kind!r} (use 'fastembed' or 'hashing')")


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a, b = list(a), list(b)
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
