"""Retrieval over the chunk index: vector, keyword, hybrid (RRF), reranked.

Four ways to find chunks for a question, all filtered to one regulation:

  vector_search   embed the question, nearest chunks by cosine distance.
                  Good at meaning ("item that hurts you after each attack"),
                  weak at rare exact names it has never seen ("Kowtow Cleave").
  keyword_search  Postgres full-text search over the generated `tsv` column.
                  The mirror image: exact words, no meaning.
  hybrid_search   both lists fused with Reciprocal Rank Fusion. RRF only looks
                  at *ranks*, so the two incomparable score scales (cosine
                  vs ts_rank) never have to be calibrated against each other.
  rerank          a cross-encoder rescores the hybrid candidates by reading the
                  question and each chunk *together* (more accurate, slower,
                  so it only sees the top few dozen candidates).

Phase 4 measured each one on evals/retrieval_set.yaml (pokechamp.evals.retrieval,
62 questions, real models, CI): Recall@5 vector 0.82, keyword 0.76, hybrid 0.90,
hybrid + rerank 0.92 at ~20x the latency (~1 s per query on CPU). Default: hybrid.
The reranker stays available; phase 5 decides with answer-quality evals whether
its small top-5 gain is worth the second.

Filter + approximate index caveat: HNSW finds nearest neighbours first and the
WHERE clause filters afterwards, so a selective filter can leave fewer than k
results. pgvector 0.8's `hnsw.iterative_scan` keeps searching until enough rows
pass the filter; we turn it on so the regulation filter stays safe while
several regulations share the table during a switchover.

Usage: python -m pokechamp.rag.search [--mode vector|keyword|hybrid|rerank] "question"
"""

import argparse
from dataclasses import dataclass, replace

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from pokechamp.db import connect
from pokechamp.rag.embeddings import Embedder, get_embedder
from pokechamp.rag.rerank import Reranker
from pokechamp.regulations import current_regulation

# RRF constant from the original paper (Cormack et al., 2009). Larger values
# flatten the difference between rank 1 and rank 10.
RRF_K = 60
# How many results each retriever contributes before fusion / reranking.
CANDIDATES = 40
# What the app uses unless told otherwise; chosen from the phase-4 metrics above.
DEFAULT_MODE = "hybrid"


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    heading: str
    text: str
    # Meaning depends on the retriever: cosine similarity (vector), ts_rank_cd
    # (keyword), RRF score (hybrid) or cross-encoder logit (rerank). Only the
    # order is comparable across retrievers, never the number.
    score: float
    source: str
    license: str
    ref: str
    regulation: str


_SELECT = """
    SELECT c.chunk_id, c.doc_id, d.title, c.heading, c.text, {score} AS score,
           d.source, d.license, d.ref, c.regulation
    FROM chunks c
    JOIN documents d USING (regulation, doc_id)
"""


def _reg(regulation: str | None) -> str:
    return regulation or current_regulation().code


def vector_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    k: int = 5,
    regulation: str | None = None,
) -> list[Hit]:
    register_vector(conn)
    qvec = np.asarray(embedder.embed_query(query), dtype=np.float32)
    with conn.transaction():
        # SET LOCAL lasts only for this transaction.
        conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = conn.execute(
            _SELECT.format(score="1 - (c.embedding <=> %(q)s)")
            + """
            WHERE c.regulation = %(reg)s AND c.embedding_model = %(model)s
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s
            """,
            {"q": qvec, "reg": _reg(regulation), "model": embedder.name, "k": k},
        ).fetchall()
    return [Hit(*row) for row in rows]


def keyword_search(
    conn: psycopg.Connection,
    query: str,
    k: int = 5,
    regulation: str | None = None,
    scoring: str = "idf",
) -> list[Hit]:
    """Full-text search. Matches chunks containing *any* query word.

    plainto_tsquery stems words and drops stopwords, but ANDs every term: a
    natural question ("how long does sleep last in champions") would need all
    its words in one chunk and usually match nothing. We OR them instead.

    scoring="ts_rank": Postgres' built-in ts_rank_cd. It counts matches and
      their proximity but has no IDF: a common word ("battle", in many
      chunks) counts as much as a rare one ("kowtow", in one chunk).
    scoring="idf": each matched word scores its inverse document frequency
      (the BM25 IDF formula; no term-frequency or length normalisation), so
      rare, specific words dominate. Document frequencies come from ts_stat
      over this regulation's chunks at query time: a full scan of the tsv
      column, fine at ~1k chunks; at scale they'd be precomputed at index time.
    """
    params = {"text": query, "reg": _reg(regulation), "k": k}
    or_query = (
        "SELECT replace(plainto_tsquery('english', %(text)s)::text, ' & ', ' | ')::tsquery AS q"
    )
    if scoring == "ts_rank":
        rows = conn.execute(
            f"WITH q AS ({or_query})"
            + _SELECT.format(score="ts_rank_cd(c.tsv, q.q)")
            + """
            CROSS JOIN q
            WHERE c.regulation = %(reg)s AND c.tsv @@ q.q
            ORDER BY score DESC, c.chunk_id
            LIMIT %(k)s
            """,
            params,
        ).fetchall()
    elif scoring == "idf":
        rows = conn.execute(
            f"""
            WITH q AS ({or_query}),
            n AS (SELECT count(*) AS n FROM chunks WHERE regulation = %(reg)s),
            df AS (
                SELECT word, ndoc FROM ts_stat(
                    format('SELECT tsv FROM chunks WHERE regulation = %%L', %(reg)s::text))
            ),
            terms AS (
                SELECT DISTINCT t.word,
                       ln((n.n - df.ndoc + 0.5) / (df.ndoc + 0.5) + 1) AS idf
                FROM unnest(tsvector_to_array(to_tsvector('english', %(text)s))) AS t(word)
                JOIN df USING (word) CROSS JOIN n
            ),
            scored AS (
                SELECT c.regulation, c.chunk_id, sum(terms.idf) AS score
                FROM chunks c CROSS JOIN q
                JOIN terms ON terms.word = ANY (tsvector_to_array(c.tsv))
                WHERE c.regulation = %(reg)s AND c.tsv @@ q.q  -- GIN pre-filter
                GROUP BY c.regulation, c.chunk_id
            )
            """
            + _SELECT.format(score="s.score")
            + """
            JOIN scored s USING (regulation, chunk_id)
            ORDER BY s.score DESC, c.chunk_id
            LIMIT %(k)s
            """,
            params,
        ).fetchall()
    else:
        raise ValueError(f"unknown scoring {scoring!r} (use 'idf' or 'ts_rank')")
    return [Hit(*row) for row in rows]


def rrf_fuse(rankings: list[list[Hit]], k: int, rrf_k: int = RRF_K) -> list[Hit]:
    """Reciprocal Rank Fusion: score = sum over lists of 1 / (rrf_k + rank).

    A chunk ranked high by either retriever scores well; one ranked high by
    both scores best. Ties break by chunk_id so results are deterministic.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    return [replace(first_seen[cid], score=scores[cid]) for cid in order]


def hybrid_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    k: int = 5,
    regulation: str | None = None,
    candidates: int = CANDIDATES,
) -> list[Hit]:
    return rrf_fuse(
        [
            vector_search(conn, embedder, query, candidates, regulation),
            keyword_search(conn, query, candidates, regulation),
        ],
        k,
    )


def reranked_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    reranker: Reranker,
    query: str,
    k: int = 5,
    regulation: str | None = None,
    candidates: int = CANDIDATES,
) -> list[Hit]:
    pool = hybrid_search(conn, embedder, query, candidates, regulation, candidates)
    return reranker.rerank(query, pool, k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the RAG index")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=5)
    modes = ["vector", "keyword", "hybrid", "rerank"]
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=modes)
    parser.add_argument("--embedder", default="fastembed", choices=["fastembed", "hashing"])
    args = parser.parse_args()
    with connect() as conn:
        if args.mode == "keyword":
            hits = keyword_search(conn, args.query, args.k)
        else:
            embedder = get_embedder(args.embedder)
            if args.mode == "vector":
                hits = vector_search(conn, embedder, args.query, args.k)
            elif args.mode == "hybrid":
                hits = hybrid_search(conn, embedder, args.query, args.k)
            else:
                from pokechamp.rag.rerank import CrossEncoderReranker

                hits = reranked_search(conn, embedder, CrossEncoderReranker(), args.query, args.k)
        for hit in hits:
            print(f"{hit.score:.3f}  {hit.heading}  [{hit.source}: {hit.ref}]")
            print(f"       {hit.text[:160]}")


if __name__ == "__main__":
    main()
