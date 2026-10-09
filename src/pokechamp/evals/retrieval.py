"""Retrieval evaluation: how often does search surface the right document?

Each question in evals/retrieval_set.yaml is labelled with the document(s)
that answer it. For every retrieval configuration we run every question, turn
the ranked chunks into a ranked list of *documents* (first appearance wins),
and compute:

  Recall@k  share of questions with a relevant document in the top k.
            (With one relevant doc per question this is also "hit rate".)
  MRR@10    mean of 1/rank of the first relevant document (0 if not in the
            top 10). Rewards putting the answer *first*, not just somewhere.

Document-level labels stay valid when chunking changes; phase 5 feeds the LLM
the top chunks, so "is a chunk of the right document in the top 5" is the
question that matters.

Usage: python -m pokechamp.evals.retrieval [--embedder hashing] [--no-rerank] [--json out.json]
Needs a built index (make index).
"""

import argparse
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psycopg
import yaml
from pgvector.psycopg import register_vector
from pydantic import BaseModel, ConfigDict

from pokechamp.db import connect
from pokechamp.rag.embeddings import Embedder, PrefixedEmbedder, get_embedder
from pokechamp.rag.rerank import Reranker
from pokechamp.rag.search import (
    Hit,
    hybrid_search,
    keyword_search,
    reranked_search,
    vector_search,
)
from pokechamp.regulations import current_regulation

RETRIEVAL_SET = Path(__file__).resolve().parents[3] / "evals" / "retrieval_set.yaml"
KS = (1, 3, 5, 10)
# The configuration the app uses (see rag/search.py: DEFAULT_MODE) is the one CI gates.
GATED_CONFIG = "hybrid (vector + IDF keyword, RRF)"
DEPTH = 30  # chunks fetched per question; enough to rank 10 distinct documents


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    kind: str
    query: str
    relevant: list[str]


def load_retrieval_set(path: Path = RETRIEVAL_SET) -> list[RetrievalQuery]:
    data = yaml.safe_load(path.read_text())
    return [RetrievalQuery(**q) for q in data["queries"]]


def ranked_docs(hits: list[Hit]) -> list[str]:
    seen: list[str] = []
    for h in hits:
        if h.doc_id not in seen:
            seen.append(h.doc_id)
    return seen


def first_relevant_rank(docs: list[str], relevant: list[str]) -> int | None:
    for rank, doc in enumerate(docs, start=1):
        if doc in relevant:
            return rank
    return None


@dataclass
class ConfigResult:
    name: str
    ranks: dict[str, int | None] = field(default_factory=dict)  # query id -> rank
    latencies_ms: list[float] = field(default_factory=list)

    def recall(self, k: int, ids: list[str] | None = None) -> float:
        ids = ids if ids is not None else list(self.ranks)
        return sum(1 for i in ids if (r := self.ranks[i]) and r <= k) / len(ids)

    def mrr(self, ids: list[str] | None = None, cutoff: int = 10) -> float:
        ids = ids if ids is not None else list(self.ranks)
        return sum(1 / r for i in ids if (r := self.ranks[i]) and r <= cutoff) / len(ids)

    def summary(self) -> dict:
        return {
            "config": self.name,
            **{f"recall@{k}": round(self.recall(k), 3) for k in KS},
            "mrr@10": round(self.mrr(), 3),
            "median_ms": round(statistics.median(self.latencies_ms), 1),
        }


Retriever = Callable[[str], list[Hit]]


def evaluate(name: str, retrieve: Retriever, queries: list[RetrievalQuery]) -> ConfigResult:
    result = ConfigResult(name)
    for q in queries:
        started = time.perf_counter()
        hits = retrieve(q.query)
        result.latencies_ms.append((time.perf_counter() - started) * 1000)
        result.ranks[q.id] = first_relevant_rank(ranked_docs(hits), q.relevant)
    return result


def configurations(
    conn: psycopg.Connection, embedder: Embedder, reranker: Reranker | None
) -> dict[str, Retriever]:
    prefixed = PrefixedEmbedder(embedder)
    configs: dict[str, Retriever] = {
        "vector (baseline)": lambda q: vector_search(conn, embedder, q, DEPTH),
        "vector + BGE prefix": lambda q: vector_search(conn, prefixed, q, DEPTH),
        "keyword (ts_rank)": lambda q: keyword_search(conn, q, DEPTH, scoring="ts_rank"),
        "keyword (IDF)": lambda q: keyword_search(conn, q, DEPTH, scoring="idf"),
        "hybrid (vector + IDF keyword, RRF)": lambda q: hybrid_search(conn, embedder, q, DEPTH),
        "hybrid + BGE prefix": lambda q: hybrid_search(conn, prefixed, q, DEPTH),
    }
    if reranker is not None:
        configs["hybrid + rerank"] = lambda q: reranked_search(conn, embedder, reranker, q, DEPTH)
    return configs


def ann_overlap(
    conn: psycopg.Connection, embedder: Embedder, queries: list[RetrievalQuery], k: int = 10
) -> float:
    """Share of the exact top-k chunks that the HNSW index also returns.

    HNSW is approximate; at ~1k chunks it should be ~1.0. Measured, not assumed.
    """
    register_vector(conn)
    reg = current_regulation().code
    found = total = 0
    for q in queries:
        approx = {h.chunk_id for h in vector_search(conn, embedder, q.query, k)}
        qvec = np.asarray(embedder.embed_query(q.query), dtype=np.float32)
        with conn.transaction():
            conn.execute("SET LOCAL enable_indexscan = off")  # force an exact scan
            exact = {
                r[0]
                for r in conn.execute(
                    "SELECT chunk_id FROM chunks WHERE regulation = %s AND embedding_model = %s"
                    " ORDER BY embedding <=> %s LIMIT %s",
                    (reg, embedder.name, qvec, k),
                )
            }
        found += len(approx & exact)
        total += len(exact)
    return found / total if total else 1.0


def format_report(
    results: list[ConfigResult], queries: list[RetrievalQuery], ann: float | None
) -> str:
    lines = [
        f"Retrieval eval: {len(queries)} questions, document-level labels\n",
        "| config | R@1 | R@3 | R@5 | R@10 | MRR@10 | median ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s = r.summary()
        lines.append(
            f"| {r.name} | " + " | ".join(f"{s[f'recall@{k}']:.2f}" for k in KS)
            + f" | {s['mrr@10']:.2f} | {s['median_ms']:.0f} |"
        )  # fmt: skip

    by_kind: dict[str, list[str]] = defaultdict(list)
    for q in queries:
        by_kind[q.kind].append(q.id)
    kinds = sorted(by_kind)
    lines += [
        "\nRecall@5 by question kind\n",
        "| config | " + " | ".join(f"{k} ({len(by_kind[k])})" for k in kinds) + " |",
        "|---|" + "---|" * len(kinds),
    ]
    for r in results:
        lines.append(
            f"| {r.name} | " + " | ".join(f"{r.recall(5, by_kind[k]):.2f}" for k in kinds) + " |"
        )

    if ann is not None:
        lines.append(f"\nHNSW vs exact scan, top-10 chunk overlap: {ann:.3f}")

    text = {q.id: q for q in queries}
    for r in results:
        misses = [i for i, rank in r.ranks.items() if not rank or rank > 5]
        lines.append(f"\nMisses@5 for {r.name} ({len(misses)}):")
        lines += [f"  {i} rank={r.ranks[i]} {text[i].query!r}" for i in misses]
    return "\n".join(lines)


def run(
    conn: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker | None,
    queries: list[RetrievalQuery] | None = None,
) -> list[ConfigResult]:
    queries = queries or load_retrieval_set()
    return [
        evaluate(name, fn, queries) for name, fn in configurations(conn, embedder, reranker).items()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval configurations")
    parser.add_argument("--embedder", default="fastembed", choices=["fastembed", "hashing"])
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--json", type=Path, help="also write the summary as JSON")
    parser.add_argument(
        "--fail-under",
        type=float,
        help=f"exit 1 if {GATED_CONFIG!r} Recall@5 is below this (CI regression gate)",
    )
    args = parser.parse_args()

    embedder = get_embedder(args.embedder)
    reranker = None
    if not args.no_rerank:
        from pokechamp.rag.rerank import CrossEncoderReranker

        reranker = CrossEncoderReranker()
    queries = load_retrieval_set()
    with connect() as conn:
        # Warm-up so the first config doesn't pay model start-up in its latency.
        hybrid_search(conn, embedder, "warm up", 5)
        if reranker:
            reranked_search(conn, embedder, reranker, "warm up", 5)
        results = run(conn, embedder, reranker, queries)
        ann = ann_overlap(conn, embedder, queries)
    print(format_report(results, queries, ann))
    if args.fail_under is not None:
        gated = next(r for r in results if r.name == GATED_CONFIG)
        if gated.recall(5) < args.fail_under:
            raise SystemExit(
                f"FAIL: {GATED_CONFIG} Recall@5 {gated.recall(5):.3f} < {args.fail_under}"
            )
        print(f"\ngate passed: {GATED_CONFIG} Recall@5 {gated.recall(5):.3f} >= {args.fail_under}")
    if args.json:
        args.json.write_text(
            json.dumps({"results": [r.summary() for r in results], "ann_overlap": ann}, indent=2)
        )


if __name__ == "__main__":
    main()
