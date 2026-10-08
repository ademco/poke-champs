"""Retrieval eval machinery: metrics, fusion and the labelled set (no DB)."""

from pokechamp.evals.retrieval import (
    ConfigResult,
    first_relevant_rank,
    load_retrieval_set,
    ranked_docs,
)
from pokechamp.rag.corpus import build_corpus
from pokechamp.rag.rerank import OverlapReranker
from pokechamp.rag.search import Hit, rrf_fuse


def hit(chunk_id: str, text: str = "") -> Hit:
    return Hit(chunk_id, chunk_id.split("#")[0], "t", "h", text, 0.0, "s", "l", "r", "M-C")


def test_retrieval_set_is_valid_and_labels_exist():
    queries = load_retrieval_set()
    doc_ids = {d.doc_id for d in build_corpus()}
    assert len(queries) >= 50
    assert len({q.id for q in queries}) == len(queries)
    assert len({q.query.lower() for q in queries}) == len(queries)
    assert {q.kind for q in queries} == {"notes", "paraphrase", "keyword", "named"}
    missing = [(q.id, r) for q in queries for r in q.relevant if r not in doc_ids]
    assert missing == []


def test_ranked_docs_keeps_first_appearance():
    hits = [hit("a#0"), hit("b#0"), hit("a#1"), hit("c#0")]
    assert ranked_docs(hits) == ["a", "b", "c"]
    assert first_relevant_rank(["a", "b", "c"], ["c", "b"]) == 2
    assert first_relevant_rank(["a"], ["z"]) is None


def test_recall_and_mrr():
    r = ConfigResult("x", ranks={"q1": 1, "q2": 3, "q3": None, "q4": 11})
    assert r.recall(1) == 0.25
    assert r.recall(3) == 0.5
    assert r.recall(10) == 0.5  # rank 11 is outside the top 10
    assert r.mrr() == (1 + 1 / 3) / 4


def test_rrf_rewards_agreement_and_is_deterministic():
    vector = [hit("a#0"), hit("b#0"), hit("c#0")]
    keyword = [hit("c#0"), hit("d#0"), hit("a#0")]
    fused = [h.chunk_id for h in rrf_fuse([vector, keyword], k=4)]
    # a and c appear in both lists; a ranks 1st+3rd, c ranks 3rd+1st: a tie,
    # broken by chunk_id. b and d appear once each, at rank 2.
    assert fused == ["a#0", "c#0", "b#0", "d#0"]
    assert rrf_fuse([vector, keyword], k=4) == rrf_fuse([vector, keyword], k=4)
    assert rrf_fuse([[], []], k=3) == []


def test_reranker_reorders_and_truncates():
    hits = [hit("a#0", "nothing here"), hit("b#0", "sleep lasts two turns"), hit("c#0", "sleep")]
    out = OverlapReranker().rerank("how long does sleep last", hits, k=2)
    assert [h.chunk_id for h in out] == ["b#0", "c#0"]
    assert OverlapReranker().rerank("q", [], k=3) == []
