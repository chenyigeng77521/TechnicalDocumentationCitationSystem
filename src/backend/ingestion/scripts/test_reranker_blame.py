"""定位"6 步 chunks 拿低分"的责任：是 ingestion 内容质量问题，还是 reranker 本身评分问题？

设计：4 种内容预处理 × 4 个目标 chunk，对比 reranker score。
- A 当前 raw（含英文 HTML 注释）
- B 拼 title_path 前缀
- C 剥英文 HTML 注释
- D 剥英文 + 拼 title

如果 B/C/D 大幅提升 6 步 chunks 分数 → ingestion 可优化（我们的活）
如果不提升 → reranker 本身评分偏 → 海军的活
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

QUERY = "API 发起驱逐的工作原理是什么"

# 4 个目标 chunks (api-eviction.md)
TARGETS = [
    ("#721",  "高分 chunk 1"),
    ("#4453", "高分 chunk 2 (cross-boundary, 含 'Pod is deleted as follows:')"),
    ("#4631", "★ 6步英文 chunk"),
    ("#5623", "★ 6步中文 chunk"),
]

# 把英文 HTML 注释 <!-- ... --> 剥掉
ENG_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->", re.MULTILINE)


def strip_english_comments(text: str) -> str:
    return ENG_COMMENT_RE.sub("", text).strip()


def variant_a(c):
    """原始内容"""
    return c["content"]


def variant_b(c):
    """拼 title_path 在最前面"""
    tp = c.get("title_path") or ""
    return f"{tp}\n\n{c['content']}" if tp else c["content"]


def variant_c(c):
    """剥英文 HTML 注释"""
    return strip_english_comments(c["content"])


def variant_d(c):
    """剥英文 + 拼 title"""
    tp = c.get("title_path") or ""
    stripped = strip_english_comments(c["content"])
    return f"{tp}\n\n{stripped}" if tp else stripped


def fetch_chunks():
    import sqlite3
    conn = sqlite3.connect("backend/storage/index/knowledge.db")
    conn.row_factory = sqlite3.Row
    chunks = {}
    for anchor_short, _label in TARGETS:
        offset = int(anchor_short.lstrip("#"))
        row = conn.execute(
            "SELECT * FROM chunks WHERE file_path LIKE '%api-eviction.md' AND char_offset_start = ?",
            (offset,),
        ).fetchone()
        if row:
            chunks[anchor_short] = dict(row)
    conn.close()
    return chunks


def main():
    print("Loading bge-reranker-base...")
    t0 = time.time()
    from sentence_transformers import CrossEncoder
    model = CrossEncoder("BAAI/bge-reranker-base")
    print(f"  loaded in {time.time() - t0:.1f}s\n")

    chunks = fetch_chunks()
    print(f"Query: {QUERY}\n")
    print(f"Loaded {len(chunks)} target chunks\n")

    # 一次性算 4 个 chunk × 4 个 variant = 16 个 pair
    pairs = []
    pair_meta = []
    for anchor, _label in TARGETS:
        c = chunks.get(anchor)
        if c is None:
            continue
        for variant_name, fn in [("A 原始", variant_a), ("B +title", variant_b),
                                  ("C 去英文", variant_c), ("D 去英文+title", variant_d)]:
            text = fn(c)
            pairs.append([QUERY, text])
            pair_meta.append((anchor, variant_name, len(text)))

    scores = model.predict(pairs)

    # 按 chunk 分组打印
    print(f"{'Anchor':<8s}{'Label':<50s}{'Variant':<22s}{'Len':<6s}{'Score':<10s}")
    print("-" * 120)
    for i, (anchor, variant, length) in enumerate(pair_meta):
        label = next(L for a, L in TARGETS if a == anchor)
        is_target = anchor in {"#4631", "#5623"}
        marker = " ★" if is_target else ""
        print(f"{anchor:<8s}{label[:48]:<50s}{variant:<22s}{length:<6d}{scores[i]:<10.4f}{marker}")
        if variant == "D 去英文+title":
            print()  # blank line between chunks

    # 汇总：6 步 chunks 在 4 个 variant 下的分数变化
    print("\n=== 6 步 chunks 分数变化总结 ===")
    for anchor in ["#4631", "#5623"]:
        scores_for_anchor = []
        for i, (a, v, _) in enumerate(pair_meta):
            if a == anchor:
                scores_for_anchor.append((v, scores[i]))
        print(f"\n{anchor}:")
        for v, s in scores_for_anchor:
            print(f"  {v:<22s} {s:.4f}")
        a_score = scores_for_anchor[0][1]
        d_score = scores_for_anchor[3][1]
        delta = d_score - a_score
        print(f"  ↑↓ A → D 变化: {delta:+.4f}  (>0.3 = ingestion 能救; <0.1 = reranker 本身的事)")


if __name__ == "__main__":
    main()
