"""Full markdown report rendering."""
from __future__ import annotations


def _pct(x: float | None) -> str:
    """Format a 0..1 metric as percent. None means N/A (denominator was 0)."""
    if x is None:
        return "—"
    return f"{x:.2%}"


def _conf_str(x):
    return "—" if x is None else f"{x:.3f}"


def _render_top6(s: dict) -> str:
    return f"""
| 指标 | 值 | 解释 |
|---|---|---|
| **总分** | {_pct(s['score'])} | (答对 + 拒答正确) / 总数 |
| **答对率（作答题）** | {_pct(s['answer_acc'])} | 答对 / (答对+答错) |
| **拒答 Recall（覆盖率）** | {_pct(s['refuse_recall'])} | 应拒题里拒了多少（高 = 不漏 trap）|
| **拒答 Precision（精准率）** | {_pct(s['refuse_precision'])} | 拒答里真该拒的比例（高 = 不乱拒）|
| **幻觉率 ⚠️** | {_pct(s['hallucination_rate'])} | 应拒题里模型瞎答的比例（= 1 - Recall）|
| **误拒率** | {_pct(s['false_refuse_rate'])} | 应答题里模型拒了的比例 |
| **平均置信度** | {_conf_str(s['avg_confidence'])} | 仅作答题 |
| Hit@5 严格 | {_pct(s['hit_rate_strict_at_5'])} | (doc_path, anchor) 完全命中 |
| Hit@5 宽松 | {_pct(s['hit_rate_loose_at_5'])} | 仅 doc_path 命中（anchor 错也算）|
| 引用精度（严格）| {_pct(s['citation_precision_strict'])} | 模型 citations 严格命中比例 |
"""


def _render_buckets(t: dict) -> str:
    s = (t['answer_correct'] + t['answer_wrong'] + t['refuse_correct']
         + t['refuse_missed'] + t['refuse_false'] + t['judge_failed'])
    return f"""
| 口袋 | 题数 |
|---|---|
| 答对 | {t['answer_correct']} |
| 答错 | {t['answer_wrong']} |
| 拒答正确 | {t['refuse_correct']} |
| 该拒没拒（幻觉⚠️）| {t['refuse_missed']} |
| 不该拒拒了（漏题）| {t['refuse_false']} |
| Judge Failed | {t['judge_failed']} |
| **合计** | **{s}** |
"""


def _render_group_table(group: dict, label: str) -> str:
    if not group:
        return f"\n（暂无 {label} 数据）\n"
    lines = [
        f"\n| {label} | 题数 | 总分 | 答对率 | Hit@5严 | Hit@5宽 | 拒答Recall | 拒答Precision | 误拒率 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, agg in group.items():
        t = agg["totals"]
        s = agg["summary"]
        lines.append(
            f"| {key} | {t['total']} | {_pct(s['score'])} | {_pct(s['answer_acc'])} | "
            f"{_pct(s['hit_rate_strict_at_5'])} | {_pct(s['hit_rate_loose_at_5'])} | "
            f"{_pct(s['refuse_recall'])} | {_pct(s['refuse_precision'])} | "
            f"{_pct(s['false_refuse_rate'])} |"
        )
    return "\n".join(lines) + "\n"


def _render_bad_case_section(
    title: str, cases: list[dict], with_judge_reason: bool = True
) -> str:
    if not cases:
        return f"\n### {title}\n\n（无）\n"
    out = [f"\n### {title}（{len(cases)} 题）\n"]
    for c in cases:
        out.append(
            f"\n**[{c['id']}]** domain={c.get('domain', '?')} "
            f"difficulty={c.get('difficulty', '?')} "
            f"confidence={c.get('model', {}).get('confidence', 0):.3f}"
        )
        out.append(f"- 问题：{c['question']}")
        out.append(f"- 标准答案：{c.get('gold_answer') or '（不可答）'}")
        out.append(f"- 模型答案：{c.get('model_answer') or '（拒答）'}")
        if with_judge_reason and c.get("judge") and c["judge"].get("reason"):
            out.append(f"- 裁判理由：{c['judge']['reason']}")
        if c.get("citations"):
            cit_str = ", ".join(
                f"{ct.get('doc_path', '?')}{ct.get('anchor', '')}"
                for ct in c["citations"]
            )
            out.append(f"- 模型引用：{cit_str}")
        if c.get("gold_sources"):
            gs_str = ", ".join(
                f"{g.get('doc_path', '?')}{g.get('anchor', '')}"
                for g in c["gold_sources"]
            )
            out.append(f"- 黄金引用：{gs_str}")
    return "\n".join(out) + "\n"


def render_full(data: dict) -> str:
    meta = data["meta"]
    totals = data["totals"]
    summary = data["summary"]
    bad = data.get("bad_cases", {})
    by_domain = data.get("by_domain", {})
    by_difficulty = data.get("by_difficulty", {})

    parts = [f"# RAG 评分报告 — {meta['run_id']}\n"]
    parts.append("## 一、元信息\n")
    parts.append(f"- 时间：{meta['timestamp']}")
    parts.append(f"- 总耗时：{meta.get('duration_seconds', 0)} 秒")
    inp = meta.get("input", {})
    parts.append(f"- 输入：gold={inp.get('gold_path')} / results={inp.get('results_path')}")
    parts.append(
        f"- 题数：matched={inp.get('matched', 0)} "
        f"gold_only={inp.get('gold_only', 0)} "
        f"results_only={inp.get('results_only', 0)}"
    )
    params = meta.get("params", {})
    parts.append(
        f"- 参数：judge_model={params.get('judge_model')} "
        f"strictness={params.get('judge_strictness')} "
        f"top_k={params.get('top_k')} concurrency={params.get('concurrency')}"
    )

    parts.append("\n## 二、总分\n")
    parts.append(_render_top6(summary))
    parts.append("\n### 5 个口袋分布\n")
    parts.append(_render_buckets(totals))

    if by_domain:
        parts.append("\n## 三、按 Domain 分组")
        parts.append(_render_group_table(by_domain, "Domain"))
    if by_difficulty:
        parts.append("\n## 四、按难度分组")
        parts.append(_render_group_table(by_difficulty, "难度"))

    parts.append("\n## 五、Bad Cases（人工 review）")
    parts.append(_render_bad_case_section(
        "5.1 该拒没拒（幻觉 ⚠️）", bad.get("hallucination", []), with_judge_reason=False
    ))
    parts.append(_render_bad_case_section(
        "5.2 答错 Top 10（按 confidence 倒序）", bad.get("wrong_answer_top10", [])
    ))
    parts.append(_render_bad_case_section(
        "5.3 检索 miss Top 10（答错且 hit@5 严格也没中）",
        bad.get("retrieval_miss_top10", [])
    ))
    parts.append(_render_bad_case_section(
        "5.4 不该拒拒了（漏题）", bad.get("false_refuse", []), with_judge_reason=False
    ))
    parts.append(_render_bad_case_section(
        "5.5 Judge Failed", bad.get("judge_failed", []), with_judge_reason=False
    ))

    parts.append("\n## 六、附录\n")
    parts.append("- per_question 全量数据 → 见 .json 报告\n")
    return "\n".join(parts)
