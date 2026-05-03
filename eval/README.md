# eval/ — RAG 评分工具

## 一句话

读 200 题 RAG 输出 + 黄金集，调 DeepSeek 判答案对错，出 .md + .json 评分报告。

## 快速开始

```bash
# 1. 配置 AIGW key（已 gitignored）
# src/.env.aigw 里设 AIGW_API_KEY=sk-xxx
# 或在 src/backend/reasoning/.env 里有 LLM_API_KEY=sk-xxx 也会自动 fallback

# 2. 跑一次
cd eval
python score.py --gold ../docs/Public_Test_Set.jsonl \
                --results ../src/backend/reasoning/storage/result/result_react_001.jsonl \
                --out reports/2026-05-03-batch200

# 3. 看报告
open reports/2026-05-03-batch200.md
```

## 输出

- `reports/<run_id>.md` → 给人看（含 6 段：元信息 / 总分 / 按 domain / 按难度 / Bad Cases / 附录）
- `reports/<run_id>.json` → 机器读 / 回归对比
- `cache/<sha>.json` → 判分缓存（重跑命中 → 0 LLM 调用）

## 顶层指标（报告头版）

| 指标 | 含义 |
|---|---|
| 总分 | (答对 + 拒答正确) / 总数 |
| 答对率 | 答对 / (答对+答错) |
| 拒答正确率 | 拒答正确 / (gold 不可答题数) |
| 幻觉率 ⚠️ | 该拒没拒 / (gold 不可答题数) |
| 误拒率 | 不该拒拒了 / (gold 可答题数) |
| Hit@5 严格 | (doc_path, anchor) 完全命中 |
| Hit@5 宽松 | 仅 doc_path 命中（anchor 错也算）|

严格 vs 宽松对比能定位"召回问题"还是"anchor 提取问题"。

## 5 个口袋（每题归一类）

|  | 模型作答 | 模型拒答 |
|---|---|---|
| **gold 标可答** | 答对 / 答错（看裁判）| 不该拒拒了（漏题）|
| **gold 标不可答** | 该拒没拒（幻觉 ⚠️）| 拒答正确 |

## 常见问题

- **AIGW_API_KEY not found** → 检查 src/.env.aigw 或 src/backend/reasoning/.env
- **重跑想强制重判** → `--no-cache`
- **跑得慢** → 提高 `--concurrency 8`（撞 429 再降回 4）
- **想用别的裁判** → `--judge-model aliyun/qwen3.6-plus`
- **judge_strictness=strict/loose** → 暂未实现，CLI 接受但抛 NotImplementedError（设计已留接口）

## CLI 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--gold` | （必填）| 黄金集 JSONL 路径 |
| `--results` | （必填）| RAG 输出 JSONL 路径 |
| `--out` | （必填）| 输出报告前缀（不带扩展名）|
| `--judge-model` | `aliyun/deepseek-v3.2` | 裁判模型 |
| `--judge-strictness` | `medium` | strict/loose 当前抛 NotImplementedError |
| `--judge-timeout` | `90` | 单次 API 超时秒数 |
| `--top-k` | `5` | recall@K 的 K |
| `--concurrency` | `4` | 并发判分数 |
| `--no-cache` | off | 强制重判 |
| `--log-level` | `INFO` | DEBUG / INFO / WARNING |

## 跑测试

```bash
cd eval
pytest tests/ -v
# 69 passed in ~2s
```

## 设计文档

- spec：`架构文档/docs/superpowers/specs/2026-05-03-eval-tool-design.md`
- plan：`架构文档/docs/superpowers/plans/2026-05-03-eval-tool.md`
- progress：`架构文档/docs/superpowers/progress/2026-05-03-eval-tool-progress.md`
