"""Index the corpus: chunk -> embed -> store, atomically, like the facts loader.

One transaction: record an ingestion run per source, delete this regulation's
documents (chunks cascade), insert the new ones. A failure leaves the previous
index serving queries; a re-run produces the same rows.

Embedding happens *before* the transaction opens, so a slow model never holds
database locks.

Usage: python -m pokechamp.rag.index [--embedder fastembed|hashing]
"""

import argparse
import time
from collections import Counter

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from pokechamp.db import connect
from pokechamp.rag.chunking import Chunk, chunk_document
from pokechamp.rag.corpus import Document, build_corpus
from pokechamp.rag.embeddings import Embedder, get_embedder
from pokechamp.sources import SOURCES


def prepare(docs: list[Document], embedder: Embedder) -> list[tuple[Chunk, list[float]]]:
    chunks = [c for d in docs for c in chunk_document(d)]
    vectors = embedder.embed_documents([c.text for c in chunks])
    if any(len(v) != embedder.dim for v in vectors):
        raise ValueError("embedder returned vectors of the wrong dimension")
    return list(zip(chunks, vectors, strict=True))


def load(
    conn: psycopg.Connection,
    docs: list[Document],
    embedded: list[tuple[Chunk, list[float]]],
    embedder: Embedder,
) -> dict[str, int]:
    register_vector(conn)
    regulations = {d.regulation for d in docs}
    if len(regulations) != 1:
        raise ValueError(f"one regulation per index load, got {sorted(regulations)}")
    (reg,) = regulations
    with conn.transaction(), conn.cursor() as cur:
        run_ids = {}
        for source in sorted({d.source for d in docs}):
            src = SOURCES[source]
            retrieved = max(d.retrieved_at for d in docs if d.source == source)
            run_ids[source] = cur.execute(
                "INSERT INTO ingestion_runs"
                " (source, source_url, source_version, license, regulation, retrieved_at,"
                " row_counts)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    source, src.url, f"rag-index:{embedder.name}", src.license, reg, retrieved,
                    Jsonb(dict(Counter(d.doc_type for d in docs if d.source == source))),
                ),
            ).fetchone()[0]  # fmt: skip

        cur.execute("DELETE FROM documents WHERE regulation = %s", (reg,))  # chunks cascade
        with cur.copy(
            "COPY documents (regulation, doc_id, title, doc_type, source, license, ref,"
            " retrieved_at, metadata, run_id) FROM STDIN"
        ) as copy:
            for d in docs:
                copy.write_row(
                    (reg, d.doc_id, d.title, d.doc_type, d.source, d.license, d.ref,
                     d.retrieved_at, Jsonb(d.metadata), run_ids[d.source])
                )  # fmt: skip
        source_of = {d.doc_id: d.source for d in docs}
        cur.executemany(
            "INSERT INTO chunks (regulation, chunk_id, doc_id, chunk_index, heading, text,"
            " word_count, content_hash, embedding_model, embedding, run_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (reg, c.chunk_id, c.doc_id, c.index, c.heading, c.text, c.word_count,
                 c.content_hash, embedder.name, np.asarray(v, dtype=np.float32),
                 run_ids[source_of[c.doc_id]])
                for c, v in embedded
            ],
        )  # fmt: skip
    return {"documents": len(docs), "chunks": len(embedded)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedder", default="fastembed", choices=["fastembed", "hashing"])
    args = parser.parse_args()

    started = time.perf_counter()
    embedder = get_embedder(args.embedder)
    docs = build_corpus()
    embedded = prepare(docs, embedder)
    embed_secs = time.perf_counter() - started
    with connect() as conn:
        counts = load(conn, docs, embedded, embedder)
    print(
        f"indexed {counts['documents']} documents / {counts['chunks']} chunks"
        f" with {embedder.name} (embedding took {embed_secs:.1f}s)"
    )


if __name__ == "__main__":
    main()
