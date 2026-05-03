"""Eval tool main entry: load → bucket → judge_batch → metrics → render."""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

from loader import load_pair, Pair
from judges.deepseek import AIGWConfig
from judges.batch import judge_batch_async, BatchResult
from judges.cache import JudgeCache
from judges.prompts import PROMPT_VERSION
from metrics.refusal import classify_buckets
from metrics.retrieval import score_retrieval
from metrics.aggregate import aggregate_totals, group_by
from render.markdown import render_full
from render.json_report import render_json


def _load_aigw_config(timeout: float, model: str) -> AIGWConfig:
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / "src" / ".env.aigw")
    api_key = os.environ.get("AIGW_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        # Fallback: try reading from src/backend/reasoning/.env (used at runtime)
        reasoning_env = project_root / "src" / "backend" / "reasoning" / ".env"
        if reasoning_env.exists():
            for line in reasoning_env.read_text().splitlines():
                if line.startswith("LLM_API_KEY=sk-"):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        raise SystemExit(
            "AIGW API key not found. Set AIGW_API_KEY or LLM_API_KEY env var, "
            "or place it in src/.env.aigw or src/backend/reasoning/.env"
        )
    return AIGWConfig(api_key=api_key, model=model, timeout=timeout)


def _build_per_question(
    matched: list[Pair],
    buckets: dict[str, list[Pair]],
    batch_results: list[BatchResult],
    top_k: int,
) -> list[dict]:
    """Combine bucket assignment + judge verdict + retrieval score → per_question list."""
    verdict_by_id = {r.pair.id: r for r in batch_results}

    per_q = []
    for p in matched:
        gold = p.gold
        result = p.result

        if p in buckets["answered_answerable"]:
            br = verdict_by_id.get(p.id)
            if br is None or br.error or br.verdict is None:
                bucket = "judge_failed"
            else:
                bucket = (
                    "answer_correct" if br.verdict.verdict == "correct" else "answer_wrong"
                )
        elif p in buckets["refused_unanswerable"]:
            bucket = "refuse_correct"
        elif p in buckets["answered_unanswerable"]:
            bucket = "refuse_missed"
        elif p in buckets["refused_answerable"]:
            bucket = "refuse_false"
        else:
            bucket = "unknown"

        if bucket in ("answer_correct", "answer_wrong"):
            rs = score_retrieval(
                gold.get("gold_sources", []),
                result.get("citations", []),
                top_k=top_k,
            )
            retrieval = {
                "hit_strict_at_5": rs.hit_strict,
                "hit_loose_at_5": rs.hit_loose,
                "strict_hits": rs.strict_hit_count,
                "loose_hits": rs.loose_hit_count,
                "citation_precision": rs.citation_precision_strict,
                "gold_sources_count": len(gold.get("gold_sources", [])),
            }
        else:
            retrieval = None

        br = verdict_by_id.get(p.id)
        judge = None
        if br:
            if br.verdict:
                judge = {
                    "verdict": br.verdict.verdict,
                    "reason": br.verdict.reason,
                    "cache_hit": br.cache_hit,
                }
            elif br.error:
                judge = {"error": br.error}

        per_q.append({
            "id": p.id,
            "domain": gold.get("domain"),
            "difficulty": gold.get("difficulty"),
            "answer_type": gold.get("answer_type"),
            "question": gold.get("question"),
            "gold_answer": gold.get("answer"),
            "gold_sources": gold.get("gold_sources", []),
            "model_answer": result.get("answer"),
            "citations": result.get("citations", []),
            "bucket": bucket,
            "model": {
                "is_refusal": bool(result.get("is_refusal", False)),
                "confidence": float(result.get("confidence", 0.0)),
                "citations_count": len(result.get("citations", [])),
            },
            "judge": judge,
            "retrieval": retrieval,
        })
    return per_q


def _collect_bad_cases(per_q: list[dict]) -> dict:
    halluc = [q for q in per_q if q["bucket"] == "refuse_missed"]
    false_ref = [q for q in per_q if q["bucket"] == "refuse_false"]
    j_fail = [q for q in per_q if q["bucket"] == "judge_failed"]
    wrong = [q for q in per_q if q["bucket"] == "answer_wrong"]
    wrong_sorted = sorted(wrong, key=lambda q: q["model"]["confidence"], reverse=True)
    miss = [
        q for q in wrong
        if q.get("retrieval") and not q["retrieval"]["hit_strict_at_5"]
    ]
    miss_sorted = sorted(miss, key=lambda q: q["model"]["confidence"], reverse=True)
    return {
        "hallucination": halluc,
        "wrong_answer_top10": wrong_sorted[:10],
        "retrieval_miss_top10": miss_sorted[:10],
        "false_refuse": false_ref,
        "judge_failed": j_fail,
    }


async def run_eval(args) -> dict:
    cfg = _load_aigw_config(args.judge_timeout, args.judge_model)
    t0 = time.time()

    # 1. Load
    lr = load_pair(args.gold, args.results)
    print(
        f"[load] matched={len(lr.matched)} "
        f"gold_only={len(lr.gold_only)} results_only={len(lr.results_only)}"
    )

    # 2. 4-bucket pre-classification
    buckets = classify_buckets(lr.matched)
    print(
        f"[bucket] answered_answerable={len(buckets['answered_answerable'])} "
        f"refused_unanswerable={len(buckets['refused_unanswerable'])} "
        f"answered_unanswerable={len(buckets['answered_unanswerable'])} "
        f"refused_answerable={len(buckets['refused_answerable'])}"
    )

    # 3. Judge batch (only on answered_answerable)
    cache = None if args.no_cache else JudgeCache(Path(__file__).parent / "cache")
    batch_results = await judge_batch_async(
        buckets["answered_answerable"],
        cfg,
        cache=cache,
        concurrency=args.concurrency,
    )
    cache_hits = sum(1 for r in batch_results if r.cache_hit)
    judge_failed = [r for r in batch_results if r.error]
    print(
        f"[judge] total={len(batch_results)} cache_hit={cache_hits} "
        f"failed={len(judge_failed)}"
    )

    # 4. Build per_question
    per_q = _build_per_question(lr.matched, buckets, batch_results, args.top_k)

    # 5. Aggregate
    overall = aggregate_totals(per_q)
    by_domain = group_by(per_q, "domain")
    by_difficulty = group_by(per_q, "difficulty")
    by_answer_type = group_by(per_q, "answer_type")
    bad_cases = _collect_bad_cases(per_q)

    # 6. Build report data
    out_prefix = Path(args.out)
    duration = int(time.time() - t0)
    report_data = {
        "meta": {
            "run_id": out_prefix.stem,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_seconds": duration,
            "input": {
                "gold_path": str(args.gold),
                "results_path": str(args.results),
                "matched": len(lr.matched),
                "gold_only": len(lr.gold_only),
                "results_only": len(lr.results_only),
            },
            "params": {
                "judge_model": cfg.model,
                "judge_strictness": args.judge_strictness,
                "judge_timeout": args.judge_timeout,
                "top_k": args.top_k,
                "concurrency": args.concurrency,
                "judge_prompt_version": PROMPT_VERSION,
            },
        },
        "totals": overall["totals"],
        "summary": overall["summary"],
        "by_domain": by_domain,
        "by_difficulty": by_difficulty,
        "by_answer_type": by_answer_type,
        "per_question": per_q,
        "bad_cases": bad_cases,
    }

    # 7. Render
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    md = render_full(report_data)
    js = render_json(report_data)
    out_prefix.with_suffix(".md").write_text(md, encoding="utf-8")
    out_prefix.with_suffix(".json").write_text(js, encoding="utf-8")
    print(f"[render] wrote {out_prefix}.md + {out_prefix}.json")
    print(
        f"[done] total={overall['totals']['total']} "
        f"score={overall['summary']['score']:.2%} duration={duration}s"
    )
    return report_data


def main():
    ap = argparse.ArgumentParser(description="RAG eval tool")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True, help="Output prefix without extension")
    ap.add_argument("--judge-model", default="aliyun/deepseek-v3.2")
    ap.add_argument(
        "--judge-strictness", default="medium", choices=["medium", "strict", "loose"]
    )
    ap.add_argument("--judge-timeout", type=float, default=90.0)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    if args.judge_strictness != "medium":
        raise NotImplementedError(
            f"--judge-strictness={args.judge_strictness} not implemented yet. "
            "Only 'medium' supported in current version."
        )

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
