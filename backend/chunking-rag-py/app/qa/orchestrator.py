from typing import Any

from app.retriever.bm25 import bm25_search
from app.retriever.dense import dense_search
from app.retriever.rrf import rrf_fuse


def retrieve_and_rerank(
    question: str, *,
    embedder,
    reranker,
    db,
    threshold: float = 0.4,
    top_k_recall: int = 20,
    top_k_final: int = 5,
) -> list[dict[str, Any]]:
    """dense + BM25 → RRF → rerank → threshold filter → top_k_final.

    只检索 files.status='completed' 的 chunks（spec D6）。
    返回每个 chunk 附加 'rerank_score' 字段；未命中阈值时返回 []。
    """
    chunks = db.get_completed_chunks()
    if not chunks:
        return []

    q_vec = embedder.encode([question])[0]
    dense_hits = [c for c, _ in dense_search(q_vec, chunks, k=top_k_recall)]
    bm25_hits = [c for c, _ in bm25_search(question, chunks, k=top_k_recall)]

    fused = rrf_fuse([dense_hits, bm25_hits], k=60)[:top_k_recall]
    if not fused:
        return []

    scores = reranker.score(question, [c["content"] for c in fused])
    scored = [
        {**c, "rerank_score": s}
        for c, s in zip(fused, scores)
        if s >= threshold
    ]
    scored.sort(key=lambda c: -c["rerank_score"])
    return scored[:top_k_final]
