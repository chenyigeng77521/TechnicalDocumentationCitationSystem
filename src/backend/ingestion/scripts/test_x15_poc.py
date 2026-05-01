"""X1.5 严谨版 POC：验证"按源文件 offset 切片 + 拼 title prefix"能否让 reranker 把答案 chunks 选进 top-3。

不动主 DB，不改 API。模拟 X1.5 流程：
1. vec_search 拿 top-K 候选
2. 对每个候选，DB 查同 (file_path, title_path) 且 chunk_index ±2 的邻居
3. 算 offset 联合范围，读源文件按 offset 切片
4. content = title_path + "\n\n" + raw_slice
5. 把这些 X1.5 化的 chunks 送进 reranker
6. 对比 reranker top-3：raw chunks vs X1.5 chunks

测两个痛点 query：
- React data fetching
- K8s API 工作原理
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import sqlite3
import numpy as np

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import vector_search

DB_PATH = Path("backend/storage/index/knowledge.db")
RAW_DIR = Path("backend/storage/raw")
WINDOW = 2  # chunk_index ±2

QUERIES = [
    {
        "name": "React data fetching",
        "q": "从大多数后端或 REST 风格 API 获取数据时，React 建议使用哪些库？",
        "answer_keyword": ["TanStack Query", "SWR", "RTK Query"],
    },
    {
        "name": "K8s 工作原理",
        "q": "API 发起驱逐的工作原理是什么",
        "answer_keyword": ["kubelet", "宽限期", "EndpointSlice"],
    },
]


def fetch_section_chunks(conn, file_path, title_path, target_idx, window=WINDOW):
    """查同 (file_path, title_path) 内 chunk_index ±window 范围的全部 chunks。"""
    rows = conn.execute(
        """
        SELECT chunk_index, char_offset_start, char_offset_end
        FROM chunks
        WHERE file_path = ?
          AND COALESCE(title_path, '') = COALESCE(?, '')
          AND ABS(chunk_index - ?) <= ?
        ORDER BY chunk_index
        """,
        (file_path, title_path, target_idx, window),
    ).fetchall()
    return rows


def read_raw_slice(file_path, start, end, _cache={}):
    """读源 .md 文件按 offset 切片，CRLF 归一化（跟 chunker 入口一致）。LRU 简易实现。"""
    if file_path not in _cache:
        # file_path 是绝对路径或相对 RAW_DIR
        path = Path(file_path)
        if not path.is_absolute():
            path = RAW_DIR / file_path
        raw = path.read_text(encoding="utf-8")
        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        _cache[file_path] = normalized
    return _cache[file_path][start:end]


def build_x15_content(conn, chunk_dict):
    """模拟 X1.5：title_path + 源文件 offset 切片。"""
    fp = chunk_dict["file_path"]
    tp = chunk_dict.get("title_path") or ""
    target_idx = chunk_dict["chunk_index"]

    siblings = fetch_section_chunks(conn, fp, tp, target_idx)
    if not siblings:
        return chunk_dict["content"]

    window_start = min(r["char_offset_start"] for r in siblings)
    window_end = max(r["char_offset_end"] for r in siblings)
    raw_slice = read_raw_slice(fp, window_start, window_end)

    if tp:
        return f"{tp}\n\n{raw_slice}"
    return raw_slice


def main():
    print("Loading bge-m3 + bge-reranker-base...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer, CrossEncoder
    embed_model = SentenceTransformer("BAAI/bge-m3")
    rerank_model = CrossEncoder("BAAI/bge-reranker-base")
    print(f"  loaded in {time.time() - t0:.1f}s\n")

    init_db(DB_PATH)
    conn = get_connection(DB_PATH)

    for q_info in QUERIES:
        query = q_info["q"]
        print("=" * 110)
        print(f"Query: {q_info['name']}")
        print(f"  Q:    {query}")
        print(f"  关键词: {q_info['answer_keyword']}")
        print("=" * 110)

        # 拿 top-30 vec 候选（给 reranker 足够样本）
        q_emb = embed_model.encode(query, normalize_embeddings=True).tolist()
        candidates = vector_search(conn, q_emb, top_k=30)
        print(f"\n  vec_search top-30 候选数: {len(candidates)}")

        # 现状（raw content）
        raw_contents = [c["content"] for c in candidates]
        raw_pairs = [[query, t] for t in raw_contents]
        raw_scores = rerank_model.predict(raw_pairs)
        raw_top = sorted(zip(raw_scores, candidates), key=lambda x: -x[0])[:5]

        # X1.5（title + raw_slice）
        x15_contents = [build_x15_content(conn, c) for c in candidates]
        x15_pairs = [[query, t] for t in x15_contents]
        x15_scores = rerank_model.predict(x15_pairs)
        x15_top = sorted(
            zip(x15_scores, candidates, x15_contents), key=lambda x: -x[0]
        )[:5]

        # 打印对比
        print(f"\n  --- 现状 reranker top-5 (raw content) ---")
        for rank, (s, c) in enumerate(raw_top, 1):
            anchor = f"{Path(c['file_path']).name}#{c['char_offset_start']}"
            preview = (c["content"] or "")[:60].replace("\n", " ")
            has_kw = any(kw in c["content"] for kw in q_info["answer_keyword"])
            kw_mark = " ★含答案关键词" if has_kw else ""
            print(f"    {rank}  {s:.4f}  {anchor:50s}  {preview!r}{kw_mark}")

        print(f"\n  --- X1.5 reranker top-5 (title + raw_slice) ---")
        for rank, (s, c, content) in enumerate(x15_top, 1):
            anchor = f"{Path(c['file_path']).name}#{c['char_offset_start']}"
            preview = content[:80].replace("\n", " ")
            has_kw = any(kw in content for kw in q_info["answer_keyword"])
            kw_mark = " ★含答案关键词" if has_kw else ""
            print(f"    {rank}  {s:.4f}  {anchor:50s}  {preview!r}{kw_mark}")

        # 验收：top-3 是否含答案关键词
        x15_top3_has_answer = any(
            any(kw in content for kw in q_info["answer_keyword"])
            for s, c, content in x15_top[:3]
        )
        raw_top3_has_answer = any(
            any(kw in c["content"] for kw in q_info["answer_keyword"])
            for s, c in raw_top[:3]
        )
        print(f"\n  现状 top-3 含答案关键词? {raw_top3_has_answer}")
        print(f"  X1.5 top-3 含答案关键词? {x15_top3_has_answer}")
        if x15_top3_has_answer and not raw_top3_has_answer:
            print("  ✅ X1.5 解决了痛点！")
        elif x15_top3_has_answer:
            print("  ⚠️ 都含——X1.5 不变差")
        else:
            print("  ❌ X1.5 仍未解决")

    conn.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
