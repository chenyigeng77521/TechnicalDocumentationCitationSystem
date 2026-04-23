import jieba
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def bm25_search(query: str, chunks: list[dict], k: int = 20) -> list[tuple[dict, float]]:
    """对传入 chunks 即时建 BM25 index 并返回 top-k (chunk, score)。"""
    if not query.strip() or not chunks:
        return []
    corpus = [_tokenize(c["content"]) for c in chunks]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    idx = sorted(range(len(chunks)), key=lambda i: -scores[i])[:k]
    return [(chunks[i], float(scores[i])) for i in idx if scores[i] > 0]
