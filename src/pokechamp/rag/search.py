"""Vector search over the chunk index (the phase-3 baseline).

Phase 4 measures this against a labelled question set, then adds keyword
(hybrid) search and reranking. For now it's the simplest correct thing: embed
the question, return the k nearest chunks by cosine distance, filtered to the
live regulation.

Filter + approximate index caveat: HNSW finds the nearest neighbours first and
the WHERE clause filters afterwards, so a selective filter can leave fewer
than k results. pgvector 0.8's `hnsw.iterative_scan` keeps searching until
enough rows pass the filter; we turn it on so the regulation filter stays safe
once several regulations share the table during a switchover.

Usage: python -m pokechamp.rag.search "what does intimidate do?"
"""

import argparse
from dataclasses import dataclass

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from pokechamp.db import connect
from pokechamp.rag.embeddings import Embedder, get_embedder
from pokechamp.regulations import current_regulation


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    heading: str
    text: str
    score: float  # cosine similarity, 1.0 = same direction
    source: str
    license: str
    ref: str
    regulation: str


def vector_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    k: int = 5,
    regulation: str | None = None,
) -> list[Hit]:
    register_vector(conn)
    reg = regulation or current_regulation().code
    qvec = np.asarray(embedder.embed_query(query), dtype=np.float32)
    with conn.transaction():
        # SET LOCAL lasts only for this transaction.
        conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.doc_id, d.title, c.heading, c.text,
                   1 - (c.embedding <=> %(q)s) AS score,
                   d.source, d.license, d.ref, c.regulation
            FROM chunks c
            JOIN documents d USING (regulation, doc_id)
            WHERE c.regulation = %(reg)s AND c.embedding_model = %(model)s
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(k)s
            """,
            {"q": qvec, "reg": reg, "model": embedder.name, "k": k},
        ).fetchall()
    return [Hit(*row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Vector search over the RAG index")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--embedder", default="fastembed", choices=["fastembed", "hashing"])
    args = parser.parse_args()
    with connect() as conn:
        for hit in vector_search(conn, get_embedder(args.embedder), args.query, args.k):
            print(f"{hit.score:.3f}  {hit.heading}  [{hit.source}: {hit.ref}]")
            print(f"       {hit.text[:160]}")


if __name__ == "__main__":
    main()
