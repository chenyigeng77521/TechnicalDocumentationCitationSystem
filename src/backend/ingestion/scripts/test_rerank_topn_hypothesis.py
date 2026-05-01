"""验证 RERANK_TOP_N 调大是否解决"返回 chunk 片段不够"的痛点。

用 RERANK_TOP_N ∈ {3, 7, 15, 25} 跑 query "API 发起驱逐的工作原理是什么"，
看 6 步流程 chunks (#4631 / #5623) 是否进入 reranker 的 top-N。

不依赖 ingestion HTTP 服务（直接 import chunks_repo + 模拟 pipeline）。
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

QUERY = "API 发起驱逐的工作原理是什么"
TARGET_ANCHORS = {  # 6 步内容
    "api-eviction.md#4631": "英文 6 步",
    "api-eviction.md#5623": "中文 6 步",
}
TOPN_VALUES = [3, 7, 15, 25]


def load_models():
    """加载 bge-m3 + bge-reranker-base."""
    print("Loading bge-m3...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer, CrossEncoder
    embed_model = SentenceTransformer("BAAI/bge-m3")
    print(f"  bge-m3 loaded in {time.time() - t0:.1f}s")
    print("Loading bge-reranker-base...")
    t0 = time.time()
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    print(f"  reranker loaded in {time.time() - t0:.1f}s")
    return embed_model, rerank_model


def fetch_candidates(query, embed_model):
    """调 ingestion 的 vector_search + text_search，合并去重。"""
    import sqlite3
    from backend.ingestion.db.connection import init_db, get_connection
    from backend.ingestion.db.chunks_repo import vector_search, text_search

    DB_PATH = Path("backend/storage/index/knowledge.db")
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)

    q_emb = embed_model.encode(query, normalize_embeddings=True).tolist()
    vec_results = vector_search(conn, q_emb, top_k=20)
    bm25_results = text_search(conn, query, top_k=20)
    conn.close()

    # 按 chunk_id 去重
    pool = {}
    for r in vec_results + bm25_results:
        cid = r["chunk_id"]
        if cid not in pool:
            pool[cid] = r
    return list(pool.values())


def rerank_with_topn(query, candidates, rerank_model, top_n):
    """模拟海军 Reranker.rerank 行为（含 _expand_rerank_context window=1）。"""
    import numpy as np
    # 上下文扩展（按 file_path + char_offset 排序，相邻 chunk 拼接）
    by_file: dict = {}
    for c in candidates:
        by_file.setdefault(c["file_path"], []).append(c)
    for fp in by_file:
        by_file[fp].sort(key=lambda x: x.get("char_offset_start", 0))
    index_map = {id(c): idx for fp, lst in by_file.items() for idx, c in enumerate(lst)}

    expanded_texts = []
    for c in candidates:
        fp = c["file_path"]
        file_chunks = by_file.get(fp, [])
        idx = index_map.get(id(c))
        if idx is None:
            expanded_texts.append(c["content"])
            continue
        parts = [file_chunks[j]["content"]
                 for j in range(max(0, idx - 1), min(len(file_chunks), idx + 2))]
        expanded_texts.append("\n".join(parts))

    pairs = [[query, t] for t in expanded_texts]
    scores = rerank_model.predict(pairs)
    sorted_idx = np.argsort(scores)[::-1]
    return [(float(scores[i]), candidates[i]) for i in sorted_idx[:top_n]]


def fmt_anchor(c):
    """规范成 'api-eviction.md#4631' 这种短格式。"""
    return f"{Path(c['file_path']).name}#{c['char_offset_start']}"


def main():
    embed_model, rerank_model = load_models()
    print(f"\nQuery: {QUERY}\n")

    candidates = fetch_candidates(QUERY, embed_model)
    print(f"两路合并候选池: {len(candidates)} chunks\n")

    print("=" * 100)
    print(f"目标：验证 6 步 chunks 是否进入 top-N")
    print(f"  - {list(TARGET_ANCHORS.keys())}")
    print("=" * 100)

    for top_n in TOPN_VALUES:
        print(f"\n--- RERANK_TOP_N = {top_n} ---")
        results = rerank_with_topn(QUERY, candidates, rerank_model, top_n)
        hits = []
        print(f"  reranker top-{top_n}:")
        for rank, (score, c) in enumerate(results, 1):
            anchor = fmt_anchor(c)
            mark = "  ★ 6步内容" if anchor in TARGET_ANCHORS else ""
            print(f"    {rank:2d}  {score:.4f}  {anchor:40s}  {(c['content'] or '')[:50]!r}{mark}")
            if anchor in TARGET_ANCHORS:
                hits.append((rank, anchor))
        if hits:
            print(f"  ✅ 6 步 chunks 命中: {hits}")
        else:
            print(f"  ❌ 6 步 chunks 未进 top-{top_n}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
