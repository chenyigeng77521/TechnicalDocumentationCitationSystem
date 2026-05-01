"""X1.5 vs X0 召回率 baseline 对比脚本。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.3

直接调内部底层函数（不走 HTTP，无需重启服务）。
跑 200 题，分别走 X0 和 X1.5 路径，输出 JSON。

Hit 规则：
  - anchor_hit (主指标，release gate)：top-3 中至少 1 个 result 同时命中 gold doc_path + markdown_anchor
  - evidence_hit (辅助)：top-3 中至少 1 个 result content 含 gold evidence 子串（前 50 字符）
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.chunks_repo import vector_search
from backend.ingestion.api.routes_search import _format_result_legacy, _row_to_metadata
from backend.ingestion.api.x15 import (
    group_results,
    _format_result_x15,
    _read_raw_file,
    clear_section_range_cache,
)

DB_PATH = Path("backend/storage/index/knowledge.db")


def x0_retrieve(conn, embedding, top_k):
    """X0 路径：直接 _format_result_legacy 每个 row。"""
    rows = vector_search(conn, embedding, top_k=top_k)
    return [_format_result_legacy(r) for r in rows]


def x15_retrieve(conn, embedding, top_k):
    """X1.5 路径：分组 + _format_result_x15。"""
    rows = vector_search(conn, embedding, top_k=top_k)
    groups = group_results(rows)
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -kv[1][0].get("score", 0),
    )
    results = []
    for key, members in sorted_groups:
        title_path = members[0].get("title_path") or ""
        metadata_x0 = _row_to_metadata(members[0])
        results.append(
            _format_result_x15(conn, members, title_path, metadata_x0)
        )
    return results


def is_anchor_hit(top_results, gold):
    """主指标：top-3 中至少 1 个 result 同时命中 gold doc_path + anchor。"""
    gold_doc = gold["doc_path"].removeprefix("docs/")
    # 进一步去掉常见的 react/kubernetes/spring 等子目录前缀（DB 平铺）
    gold_doc_basename = Path(gold_doc).name
    gold_anchor = gold["anchor"]
    return any(
        Path(r["metadata"]["file_path"]).name == gold_doc_basename
        and r["metadata"]["markdown_anchor"] == gold_anchor
        for r in top_results
    )


def is_evidence_hit(top_results, gold):
    """辅助指标：top-3 中至少 1 个 result content 包含 gold evidence 子串（前 50 字符）。"""
    needle = gold["evidence"][:50]
    return any(needle in r["content"] for r in top_results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-set", default="docs/Public_Test_Set.jsonl")
    ap.add_argument("--output", default="/tmp/x15_baseline_result.json")
    ap.add_argument("--top-k", type=int, default=30)
    args = ap.parse_args()

    print(f"Loading bge-m3...")
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-m3")

    print(f"Loading test set: {args.test_set}")
    test_items = [json.loads(line) for line in open(args.test_set)]
    print(f"  {len(test_items)} 题")

    conn = get_connection(DB_PATH)
    _read_raw_file.cache_clear()
    clear_section_range_cache()

    summary = {
        "x0_anchor_hit": 0, "x15_anchor_hit": 0,
        "x0_evidence_hit": 0, "x15_evidence_hit": 0,
        "x0_only_anchor_hit": [], "x15_only_anchor_hit": [],
        "both_anchor_hit": [], "both_anchor_miss": [],
        "trap_skipped": 0,
    }
    per_query = []
    answerable_total = 0

    t0 = time.time()
    for i, item in enumerate(test_items, 1):
        if i % 20 == 0:
            print(f"  [{i}/{len(test_items)}] elapsed {time.time()-t0:.1f}s")

        # Trap 题（is_answerable=false / gold_sources=[]）跳过 anchor_hit 评估
        gold_sources = item.get("gold_sources", [])
        if not gold_sources:
            summary["trap_skipped"] += 1
            per_query.append({
                "id": item["id"],
                "domain": item["domain"],
                "query": item["question"],
                "is_trap": True,
            })
            continue

        answerable_total += 1
        emb = m.encode(item["question"], normalize_embeddings=True).tolist()
        x0_top3 = x0_retrieve(conn, emb, args.top_k)[:3]
        x15_top3 = x15_retrieve(conn, emb, args.top_k)[:3]

        gold = gold_sources[0]
        x0_a = is_anchor_hit(x0_top3, gold)
        x15_a = is_anchor_hit(x15_top3, gold)
        x0_e = is_evidence_hit(x0_top3, gold)
        x15_e = is_evidence_hit(x15_top3, gold)

        summary["x0_anchor_hit"] += int(x0_a)
        summary["x15_anchor_hit"] += int(x15_a)
        summary["x0_evidence_hit"] += int(x0_e)
        summary["x15_evidence_hit"] += int(x15_e)

        if x0_a and not x15_a: summary["x0_only_anchor_hit"].append(item["id"])
        if x15_a and not x0_a: summary["x15_only_anchor_hit"].append(item["id"])
        if x0_a and x15_a: summary["both_anchor_hit"].append(item["id"])
        if not x0_a and not x15_a: summary["both_anchor_miss"].append(item["id"])

        per_query.append({
            "id": item["id"],
            "domain": item["domain"],
            "query": item["question"],
            "gold_doc": gold["doc_path"],
            "gold_anchor": gold["anchor"],
            "x0_anchor_hit": x0_a, "x15_anchor_hit": x15_a,
            "x0_evidence_hit": x0_e, "x15_evidence_hit": x15_e,
            "x0_top3_anchors": [
                f"{r['metadata']['file_path']}{r['metadata']['markdown_anchor']}"
                for r in x0_top3
            ],
            "x15_top3_anchors": [
                f"{r['metadata']['file_path']}{r['metadata']['markdown_anchor']}"
                for r in x15_top3
            ],
        })

    summary["improvement_anchor"] = summary["x15_anchor_hit"] - summary["x0_anchor_hit"]
    summary["improvement_evidence"] = summary["x15_evidence_hit"] - summary["x0_evidence_hit"]
    summary["total"] = len(test_items)
    summary["answerable_total"] = answerable_total
    summary["elapsed_seconds"] = time.time() - t0

    Path(args.output).write_text(json.dumps(
        {"summary": summary, "per_query": per_query},
        ensure_ascii=False, indent=2
    ))

    print()
    print("=" * 60)
    print(f"总题数:           {len(test_items)}（其中 trap {summary['trap_skipped']} 题跳过）")
    print(f"评估题数:         {answerable_total}")
    print(f"X0  anchor_hit:   {summary['x0_anchor_hit']}/{answerable_total}")
    print(f"X15 anchor_hit:   {summary['x15_anchor_hit']}/{answerable_total}")
    print(f"提升:             {summary['improvement_anchor']:+d} 题")
    print(f"X0  evidence_hit: {summary['x0_evidence_hit']}/{answerable_total}")
    print(f"X15 evidence_hit: {summary['x15_evidence_hit']}/{answerable_total}")
    print(f"耗时:             {summary['elapsed_seconds']:.1f}s")
    print(f"详细 JSON:        {args.output}")
    print()

    if summary["x15_anchor_hit"] >= summary["x0_anchor_hit"]:
        print("✅ release gate: x15 anchor_hit >= x0 anchor_hit")
    else:
        print("❌ release gate FAIL: x15 召回率低于 x0!")
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
