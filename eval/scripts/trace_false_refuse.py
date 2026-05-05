"""P0 trace 实验：54 误拒题逐层 dump，定位 gold chunk 在哪层被丢。

层次：
  1. RAW_VEC      — 向量检索原始 top-20（绕开 0.55 阈值，直接调 ingestion /chunks/vector-search）
  2. FILTERED_VEC — 应用 VECTOR_SCORE_THRESHOLD=0.55 后保留的
  3. RAW_BM25     — BM25 原始 top-20（直接调 /chunks/text-search）
  4. MERGED       — _merge_results 合并去重后
  5. RERANKED     — reranker 打分后，全部排序
  6. FINAL_TOPK   — adaptive_topk 截断后

输出：
  - eval/reports/trace_false_refuse.json — 每题完整 trace 数据
  - eval/reports/trace_false_refuse.md — 人类可读 summary（每题 gold 命中所在层）

用法：
  cd eval && python scripts/trace_false_refuse.py
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# 让脚本可以 import 项目代码
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
# 把 retrieval 模块所在目录也加到 path（pipeline 内部 from retrieval import ... 这种）
sys.path.insert(0, str(PROJECT_ROOT / "src" / "backend" / "retrieval"))

from dotenv import dotenv_values, load_dotenv
# retrieval/.env 是模板（key 占位符 sk-），先从 .env.aigw 提取真 key 注入环境
# 必须在 import retrieval 之前完成（retrieval 模块在 import 时读 env）
aigw = dotenv_values(PROJECT_ROOT / "src" / ".env.aigw")
real_key = aigw.get("AIGW_API_KEY")
if real_key:
    os.environ.setdefault("EMBEDDING_API_KEY", real_key)
    os.environ.setdefault("RERANK_API_KEY", real_key)
    os.environ.setdefault("OPENAI_API_KEY", real_key)
load_dotenv(PROJECT_ROOT / "src" / "backend" / "retrieval" / ".env")

import requests  # noqa: E402

GOLD_PATH = PROJECT_ROOT / "docs" / "Public_Test_Set.jsonl"
EVAL_REPORT_PATH = PROJECT_ROOT / "eval" / "reports" / "2026-05-03-batch200.json"
TRACE_OUT_DIR = PROJECT_ROOT / "eval" / "reports"
TRACE_OUT_DIR.mkdir(parents=True, exist_ok=True)


def gold_anchor_match(gold_sources: list[dict], cand: dict) -> tuple[bool, bool]:
    """判断候选 chunk 是否命中 gold (strict: doc+anchor 都对 / loose: 只看 doc)."""
    cand_doc = cand.get("file_path") or cand.get("doc_path") or ""
    cand_anchor = cand.get("markdown_anchor") or cand.get("anchor") or ""
    for g in gold_sources:
        gd, ga = g.get("doc_path", ""), g.get("anchor", "")
        # doc_path 匹配（容忍前缀路径如 docs/）
        doc_eq = cand_doc.endswith(gd) or gd.endswith(cand_doc) or cand_doc == gd
        if doc_eq:
            anchor_eq = cand_anchor == ga or (
                # 容忍 chunk 的 anchor 为英文版而 gold 含中文前缀
                ga.endswith(cand_anchor) and cand_anchor.startswith("#")
            )
            if anchor_eq:
                return True, True
            return False, True  # loose hit only
    return False, False


def dump_one_question(qid: str, question: str, gold_sources: list[dict]) -> dict:
    """对单题 dump 所有层。"""
    # 注意：retrieval.pipeline() 内部用的是 retrieval 模块的 client，会带 0.55 过滤
    # 我们要拿 raw vec，绕过过滤直接调 ingestion endpoint
    from retrieval import (
        get_api_client, get_reranker, _merge_results, adaptive_topk_simple,
        VECTOR_SCORE_THRESHOLD,
    )

    client = get_api_client()
    reranker = get_reranker()

    # ===== Layer 1+2: vector =====
    # client.search() 已经应用了 0.55 过滤，结果是 FILTERED_VEC
    filtered_vec_docs = client.search(question, top_k=20)

    # 拿 RAW vec：绕开 client，直接走 embedding API + ingestion 的 vector-search
    # 简化：用 client.search 但临时把 threshold 设为 0
    import retrieval as rmod
    orig_thr = rmod.VECTOR_SCORE_THRESHOLD
    rmod.VECTOR_SCORE_THRESHOLD = 0.0
    try:
        raw_vec_docs = client.search(question, top_k=20)
    finally:
        rmod.VECTOR_SCORE_THRESHOLD = orig_thr

    # ===== Layer 3: BM25 =====
    raw_bm25_docs = client.text_search(question, top_k=20)

    # ===== Layer 4: merged (用 filtered_vec 进 merge，跟生产链路一致) =====
    merged_docs = _merge_results(filtered_vec_docs, raw_bm25_docs)

    # ===== Layer 5: reranked =====
    reranked_docs = reranker.rerank(question, merged_docs) if merged_docs else []

    # ===== Layer 6: adaptive_topk =====
    k = adaptive_topk_simple(question, reranked_docs) if reranked_docs else 0
    final_docs = reranked_docs[:k]

    def _doc_to_dict(d, layer):
        m = d.metadata if hasattr(d, "metadata") else {}
        # reasoning 实际用的 score：reranker_score 优先，降级 vec score
        eff_score = float(m.get("reranker_score") or m.get("score") or 0.0)
        return {
            "file_path": m.get("file_path") or m.get("doc_path", ""),
            "anchor": m.get("markdown_anchor") or m.get("anchor", ""),
            "score": eff_score,
            "vec_score": float(m.get("score", 0.0)),
            "reranker_score": float(m.get("reranker_score", 0.0)) if m.get("reranker_score") else None,
            "chunk_id": m.get("chunk_id", ""),
            "layer": layer,
        }

    layers = {
        "RAW_VEC": [_doc_to_dict(d, "RAW_VEC") for d in raw_vec_docs],
        "FILTERED_VEC": [_doc_to_dict(d, "FILTERED_VEC") for d in filtered_vec_docs],
        "RAW_BM25": [_doc_to_dict(d, "RAW_BM25") for d in raw_bm25_docs],
        "MERGED": [_doc_to_dict(d, "MERGED") for d in merged_docs],
        "RERANKED": [_doc_to_dict(d, "RERANKED") for d in reranked_docs],
        "FINAL_TOPK": [_doc_to_dict(d, "FINAL_TOPK") for d in final_docs],
    }

    # 找 gold 在每层的命中位置
    gold_status: dict = {}
    for layer_name, candidates in layers.items():
        strict_idx = -1
        loose_idx = -1
        for i, c in enumerate(candidates):
            s, l = gold_anchor_match(gold_sources, c)
            if s and strict_idx == -1:
                strict_idx = i
            if l and loose_idx == -1:
                loose_idx = i
        gold_status[layer_name] = {
            "strict_rank": strict_idx,  # -1 表示未命中
            "loose_rank": loose_idx,
            "size": len(candidates),
            "max_score": max((c["score"] for c in candidates), default=0.0),
        }

    return {
        "id": qid,
        "question": question,
        "gold_sources": gold_sources,
        "layers": layers,
        "gold_status": gold_status,
    }


def main():
    # 读 200 题评测，挑出 54 误拒题
    with open(EVAL_REPORT_PATH, encoding="utf-8") as f:
        report = json.load(f)
    fr_ids = [q["id"] for q in report["per_question"] if q["bucket"] == "refuse_false"]
    print(f"误拒题数: {len(fr_ids)}")

    # 读 gold
    gold_by_id = {}
    with open(GOLD_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["id"] in fr_ids:
                gold_by_id[r["id"]] = r

    # 跑 trace
    traces = []
    for i, qid in enumerate(fr_ids, 1):
        gold = gold_by_id[qid]
        print(f"[{i}/{len(fr_ids)}] {qid}: {gold['question'][:50]}")
        try:
            t = dump_one_question(qid, gold["question"], gold["gold_sources"])
            traces.append(t)
        except Exception as e:
            print(f"  ERROR: {e}")
            traces.append({"id": qid, "error": str(e)})

    # 汇总输出
    out_json = TRACE_OUT_DIR / "trace_false_refuse.json"
    out_json.write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out_json}")

    # 生成 .md summary
    write_md_summary(traces, TRACE_OUT_DIR / "trace_false_refuse.md")


def write_md_summary(traces: list[dict], path: Path):
    lines = [
        "# False-Refuse Trace 实验报告",
        "",
        f"对 {len(traces)} 题误拒做了逐层 dump，看 gold chunk 在哪层被丢。",
        "",
        "## 每层命中统计",
        "",
        "| 层 | 严格命中数 | 宽松命中数 |",
        "|---|---|---|",
    ]
    layer_stats: dict = {}
    for layer in ["RAW_VEC", "FILTERED_VEC", "RAW_BM25", "MERGED", "RERANKED", "FINAL_TOPK"]:
        strict = sum(1 for t in traces if "gold_status" in t and t["gold_status"][layer]["strict_rank"] >= 0)
        loose = sum(1 for t in traces if "gold_status" in t and t["gold_status"][layer]["loose_rank"] >= 0)
        layer_stats[layer] = (strict, loose)
        lines.append(f"| {layer} | {strict}/{len(traces)} | {loose}/{len(traces)} |")

    lines.append("")
    lines.append("## Gold chunk 卡在哪层（严格命中视角）")
    lines.append("")
    drops: dict = {"never_in_vec": 0, "vec_threshold": 0, "lost_in_merge": 0,
                   "rerank_drop": 0, "topk_cut": 0, "in_final": 0,
                   "loose_only": 0, "fully_lost": 0}
    for t in traces:
        if "gold_status" not in t:
            continue
        gs = t["gold_status"]
        if gs["FINAL_TOPK"]["strict_rank"] >= 0:
            drops["in_final"] += 1
        elif gs["RERANKED"]["strict_rank"] >= 0:
            drops["topk_cut"] += 1
        elif gs["MERGED"]["strict_rank"] >= 0:
            drops["rerank_drop"] += 1
        elif gs["FILTERED_VEC"]["strict_rank"] >= 0 or gs["RAW_BM25"]["strict_rank"] >= 0:
            drops["lost_in_merge"] += 1
        elif gs["RAW_VEC"]["strict_rank"] >= 0:
            drops["vec_threshold"] += 1
        elif gs["RAW_VEC"]["loose_rank"] >= 0 or gs["RAW_BM25"]["loose_rank"] >= 0:
            drops["loose_only"] += 1
        else:
            drops["fully_lost"] += 1

    lines.append("| 状态 | 题数 | 含义 |")
    lines.append("|---|---|---|")
    lines.append(f"| ✅ 进入 FINAL_TOPK | {drops['in_final']} | 已喂给 LLM，但 reasoning 拒答（阈值问题）|")
    lines.append(f"| ❌ TopK 截掉 | {drops['topk_cut']} | reranker 排序 OK 但被 adaptive_topk 砍掉 |")
    lines.append(f"| ❌ Reranker 排掉 | {drops['rerank_drop']} | 进了 merged 但 reranker 给低分 |")
    lines.append(f"| ❌ 合并丢失 | {drops['lost_in_merge']} | 进了 vec 或 bm25 但合并后丢了（不应发生）|")
    lines.append(f"| ❌ Vec 阈值过滤 | {drops['vec_threshold']} | RAW_VEC 有但 0.55 阈值过滤掉 |")
    lines.append(f"| ⚠️ 仅宽松命中 | {drops['loose_only']} | doc 找对了 anchor 错（可能 ingestion anchor 提取问题）|")
    lines.append(f"| ❌ 完全没召回 | {drops['fully_lost']} | gold doc 在 vec 和 bm25 都没出现 |")

    lines.append("")
    lines.append("## 逐题明细")
    lines.append("")
    for t in traces:
        if "error" in t:
            lines.append(f"### {t['id']} — ERROR: {t['error']}")
            lines.append("")
            continue
        gs = t["gold_status"]
        gs_str = " / ".join(
            f"{layer}: 严{gs[layer]['strict_rank']}/{gs[layer]['size']} 宽{gs[layer]['loose_rank']}"
            for layer in ["RAW_VEC", "FILTERED_VEC", "RAW_BM25", "MERGED", "RERANKED", "FINAL_TOPK"]
        )
        gold_str = ", ".join(f"{g['doc_path']}{g['anchor']}" for g in t["gold_sources"])
        lines.append(f"### {t['id']}")
        lines.append(f"- Q: {t['question']}")
        lines.append(f"- Gold: {gold_str}")
        lines.append(f"- 各层命中（rank=-1 表示未命中）: {gs_str}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
