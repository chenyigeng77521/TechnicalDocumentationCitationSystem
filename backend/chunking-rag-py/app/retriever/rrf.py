def rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """RRF: score(d) = Σ 1/(k + rank_i(d))。返回按融合分数降序的唯一 chunks。"""
    scores: dict[str, float] = {}
    chunk_by_id: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, chunk in enumerate(lst):
            cid = chunk["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            chunk_by_id[cid] = chunk
    return [chunk_by_id[cid] for cid in sorted(scores, key=lambda c: -scores[c])]
