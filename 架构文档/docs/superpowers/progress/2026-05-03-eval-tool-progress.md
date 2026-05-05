# Eval Tool 实施进度

| | |
|---|---|
| Plan | [2026-05-03-eval-tool.md](../plans/2026-05-03-eval-tool.md) |
| Spec | [2026-05-03-eval-tool-design.md](../specs/2026-05-03-eval-tool-design.md) |
| 执行模式 | inline（当前 session 串行）|
| 开始时间 | 2026-05-03 |

---

## 进度记录

（每个 task 完成后追加在下面）

---

### ✅ Task 1: Loader（读数据 + 配对）

- 6 个测试全过（perfect_match / empty_files / single_record / missing_file / invalid_jsonl / partial_match）
- 实现 `loader.py`：`load_pair(gold_path, results_path) → LoadResult{matched, gold_only, results_only}`，按 id join 两个 JSONL
- Fixture 准备完毕：`sample_gold_10.jsonl` + `sample_results_10.jsonl`，10 题完美配对
- **额外动作**：项目根 `.gitignore` 第 99 行原有 `eval/` 整目录排除，改成 `eval/cache/` + `eval/reports/` 细粒度排除（保留代码入 git）
- Commit: `feat(eval): add JSONL loader with id-matched pairs`

### ✅ Task 2: 4 口袋分类

- 4 个测试全过（4 种组合 / 空 / 缺字段 / 真实 fixture 8+2+0+0）
- 实现 `metrics/refusal.py`：按 (gold.is_answerable, result.is_refusal) 二维分类，返回 4 桶 dict
- Commit: `feat(eval): add 4-bucket judge-independent pair classification`

### ✅ Task 3: Prompt 模板 + JSON 解析

- 10 个测试全过（render 3 + parse 6 + 版本常量 1）
- 实现 `judges/prompts.py`：`render_prompt`/`parse_verdict`/`PROMPT_VERSION="v1.0"`
- Prompt 含两个 few-shot 例子（correct/wrong），强制裁判贴标准答案不自由发挥
- Parser 容忍 markdown fence + leading text
- Commit: `feat(eval): add judge prompt template + JSON response parsing`

### ✅ Task 4: 判分缓存

- 6 个测试全过（roundtrip / 自动建目录 / 损坏当 miss / 多 key 共存 / answer 变 → key 变 / prompt_version 变 → key 变）
- 实现 `judges/cache.py`：SHA256 一题一文件，key 含 5 维（id/model_answer/gold_answer/judge_model/prompt_version）
- Commit: `feat(eval): add SHA256 file-per-key judge response cache`

### ✅ Task 5: DeepSeek 单次调用 ⚠️ 关键节点

- 9 mocked 测试全过（success / cache hit/miss / empty / 5xx retry / 429 backoff / timeout retry / invalid JSON retry / prompt 透传）
- 真打 AIGW 验证：react_001 → verdict=correct，reason 引用标准答案关键短语，证明 prompt 优先级生效
- 实现 `judges/deepseek.py`：含 `judge_one_async(pair, cfg, cache?, prompt_version?) → (verdict, cache_hit)`，重试策略覆盖 429/5xx/timeout/JSON parse fail
- 关键节点已通过用户验收
- Commit: `feat(eval): add DeepSeek judge with cache+retry+timeout`

### ✅ Task 6: 批量并发判分

- 6 测试全过（success / empty / single / partial failure / concurrency cap / concurrent cache writes）
- 实现 `judges/batch.py`：`asyncio.Semaphore` 控并发，单题失败不影响 batch
- Commit: `feat(eval): add concurrent batch judging with semaphore`

### ✅ Task 7: 检索指标

- 8 测试全过（strict hit / empty cits / empty gold / gold>K / missing fields / loose-only / precision = 1/3 / top-K 截断）
- 实现 `metrics/retrieval.py`：`score_retrieval(gold_sources, citations, top_k=5) → RetrievalScore`
- Commit: `feat(eval): add retrieval recall@K (strict+loose) and citation precision`

### ✅ Task 8: 分组聚合

- 7 测试全过（aggregate basic 5 buckets / empty / all correct / group by domain / by difficulty / missing field / 各组 totals 之和 = overall）
- 实现 `metrics/aggregate.py`：`aggregate_totals(per_q)` 出 totals+summary 9 指标；`group_by(per_q, field)` 按任意字段分组
- Commit: `feat(eval): add grouped aggregation by domain/difficulty/answer_type`

### ✅ Task 9: Markdown 报告

- 8 测试全过（6 段都在 / top-6 数值 / 5 桶标签 / bad case 含裁判 reason / 空 bad case / 0 total 不崩 / 缺字段抛错 / 5 桶合计显示）
- 实现 `render/markdown.py`：渲染元信息+总分+按 domain+按难度+5 个 bad case 段+附录
- Commit: `feat(eval): add full markdown report with bad case sections`

### ✅ Task 10: JSON 报告

- 4 测试全过（顶层 keys / 中文不转义 / roundtrip / 2 空格缩进）
- 实现 `render/json_report.py`：`render_json(data) → JSON string`
- Commit: `feat(eval): add JSON report writer`

### ✅ Task 11: score.py CLI + e2e ⚠️ 关键节点

- e2e mock test 通过；69 个单测全过
- 真打 AIGW 10 题 smoke run（22 秒，4 并发）：score=90%，7 对 + 1 错 + 2 拒答正确，0 幻觉 0 漏题
- 裁判抓出 react_021 答错的具体原因（漏关键事实"无限循环"）
- 检索 Hit@5 严格 37.5% vs 宽松 87.5% 揭示 anchor 提取/匹配问题（印证 04-29 memory 里的已知问题）
- 关键节点已通过用户验收
- Commit: `feat(eval): add CLI orchestration + e2e integration test`

### ✅ Task 12: README + .gitignore

- 写 README.md：快速开始 / 6 段输出说明 / 9 个顶层指标含义 / 5 口袋表 / 11 个 CLI 参数 / FAQ
- 写 eval/.gitignore：cache/ reports/ __pycache__/ *.pyc .pytest_cache/
- Commit: `docs(eval): add README and .gitignore`

### ✅ 后续修复 1: N/A 显示（"—" vs "0.00%"）

- React 域无 trap 题时，拒答正确率显示 "0.00%" 误导。改成 "—"。
- aggregate.py: 分母 0 时返回 None；markdown 渲染 None 显示 "—"
- Commit: `fix(eval): distinguish "no data" (—) from real "0%" in metrics`

### ✅ 后续修复 2: refuse_precision/recall 拆分（codex cross-review 发现）

- 旧字段 `refuse_precision` 用的公式实际是 recall，命名误导
- 拆成：
  - `refuse_recall` = 应拒题里拒了多少 = 100%（保留旧语义）
  - `refuse_precision` = 拒答里真该拒的比例 = 48.08%（新加，揭示"模型过度拒答"）
- 200 题报告新数据：拒答 104 题，但只有 50 题真该拒 → 52% 误拒
- Commit: `fix(eval): split refuse_precision into recall + true precision`
