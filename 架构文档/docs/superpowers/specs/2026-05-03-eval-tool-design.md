# Eval Tool — RAG 系统离线评分工具设计文档

| | |
|---|---|
| 日期 | 2026-05-03 |
| 作者 | 涂祎豪（chenyigeng77521） |
| 状态 | Draft (待用户 review) |
| 关联 | 200 题 batch 测试（[Public_Test_Set.jsonl](../../../docs/Public_Test_Set.jsonl)）|

---

## 一、背景与目标

### 1.1 解决什么问题
现在系统跑完 200 题后，输出的是裸 JSONL（5 个字段：id、answer、citations、is_refusal、confidence），无法直接看出"系统好不好"。需要一个**离线评分工具**：
- 拿系统输出 vs 黄金集（Public_Test_Set.jsonl，含 gold_sources/answer/is_answerable）
- 自动算出"答对率 / 检索命中率 / 拒答正确率 / 幻觉率"等核心指标
- 出一份 .md 人类阅读 + .json 机器读 的报告

### 1.2 不做什么（YAGNI）
- ❌ 不自动跑 X0 baseline 对比（接口保留，本期不实现）
- ❌ 不做 web UI / 实时 dashboard
- ❌ 不做多轮判分投票（一次判一次过）
- ❌ 不做答案翻译/格式归一

### 1.3 成功标准
- 输入 200 题黄金集 + 200 题系统输出，5 分钟内出报告
- 报告含 5 个口袋分类、6 个顶层指标、按 domain/difficulty 分组、bad case 列表
- 单测覆盖率 ≥80%（不含 LLM 调用部分）
- 可重复运行：同样输入 → 缓存命中 → 0 LLM 调用 → 秒级出报告

---

## 二、架构总览

### 2.1 数据流

```
┌── 输入 ──────────────────────────────────────┐
│ docs/Public_Test_Set.jsonl                  │  200 题黄金集，含 gold_answer + gold_sources
│ src/.../result_<run_id>.jsonl               │  RAG 系统输出（5 字段）
└─────┬───────────────────────────────────────┘
      ↓
┌── eval/ 工具（5 阶段流水线）──────────────────┐
│ 1. load    按 id 配对，识别异常数据             │
│ 2. judge   调 DeepSeek 判答案对错（带缓存）     │
│ 3. recall  算检索 hit@K（严格 + 宽松两套）      │
│ 4. refuse  按 5 个口袋分类                     │
│ 5. render  → md + json 报告                    │
└─────┬───────────────────────────────────────┘
      ↓
eval/reports/<run_id>.md       ← 给人看
eval/reports/<run_id>.json     ← 机器读，未来回归对比
eval/cache/judge_<hash>.json   ← 判分缓存
```

### 2.2 项目目录

```
eval/                            ← 项目根新建
├── README.md                    一页快速开始
├── score.py                     主入口（async main）
├── judges/
│   ├── __init__.py
│   ├── deepseek.py              判分逻辑（含缓存 + 重试 + 并发）
│   └── prompts.py               judge prompt 模板（含 few-shot 例子）
├── metrics/
│   ├── __init__.py
│   ├── retrieval.py             recall@K（strict + loose）+ citation precision
│   ├── refusal.py               5 口袋分类
│   └── aggregate.py             按 domain/difficulty/answer_type 分组
├── render/
│   ├── __init__.py
│   ├── markdown.py              md 报告渲染
│   └── json_report.py           json 报告渲染
├── cache/                       ← .gitignore
├── reports/                     ← .gitignore
└── tests/
    ├── fixtures/
    │   ├── sample_gold_10.jsonl     从 Public_Test_Set 抽 10 题
    │   └── sample_results_10.jsonl  我们 smoke run 的真实输出
    ├── test_metrics_retrieval.py
    ├── test_metrics_refusal.py
    ├── test_render_markdown.py
    └── test_e2e.py              （integration，真调 AIGW）
```

---

## 三、CLI 设计

### 3.1 调用方式

```bash
cd eval
python score.py \
  --gold ../docs/Public_Test_Set.jsonl \
  --results ../src/backend/reasoning/storage/result/result_react_001.jsonl \
  --out reports/2026-05-03-batch200
```

输出：
- `eval/reports/2026-05-03-batch200.md`
- `eval/reports/2026-05-03-batch200.json`

### 3.2 全部参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--gold` | （必填）| 黄金集 JSONL 路径 |
| `--results` | （必填）| RAG 输出 JSONL 路径 |
| `--out` | （必填）| 输出报告前缀（不带扩展名）|
| `--judge-model` | `aliyun/deepseek-v3.2` | 裁判模型（AIGW 路径）|
| `--judge-strictness` | `medium` | strict / medium / loose |
| `--judge-timeout` | `90` | 单次 API 超时秒数 |
| `--top-k` | `5` | recall@K 的 K |
| `--concurrency` | `4` | 并发判分数 |
| `--no-cache` | off | 强制重判 |
| `--log-level` | `INFO` | DEBUG / INFO / WARNING |

---

## 四、Judge 模块详细设计

### 4.1 模型选择

- **裁判**：`aliyun/deepseek-v3.2`（赛事方提供，跟系统用的 GLM-5 训练路线不同，避免近亲打分）
- **被评对象**：系统输出的 5 字段 JSON（`answer` 字段是核心）

### 4.2 严格度

只实现 **medium**（中等严格度）。CLI 参数 `--judge-strictness` 接受 strict/medium/loose，但 strict/loose 当前抛 `NotImplementedError`，提示用户后续版本支持。

中等严格度规则：
- 模型答案核心意思跟标准答案一致 → correct
- 措辞不同、多说了不冲突的细节 → correct
- 漏掉关键事实 → wrong
- 跟标准答案/原文冲突 → wrong（即使模型"听起来对"）
- 答非所问 → wrong

### 4.3 Judge prompt（最终版）

```
你是一个严谨的技术问答评分裁判。

【评分依据的优先级】
- 第 1 优先：【标准答案】是最终判分的"对错"标准
- 第 2 参考：【原文出处】帮你理解标准答案的覆盖范围
- 不允许：用你自己的世界知识自由发挥（即使模型答案在你看来"事实正确"，
  但偏离标准答案 + 原文出处的范围，仍判 wrong）

【判分规则——中等严格度】
- 模型答案核心意思跟标准答案一致 → correct
- 措辞不同、多说了不冲突的细节 → correct
- 漏掉标准答案/原文中的关键事实 → wrong
- 跟标准答案/原文冲突 → wrong（即使模型答案"听起来对"）
- 答非所问 → wrong

【参考例子】

例子 1（correct）：
问题：React Compiler 的增量采用是什么意思？
标准答案：React Compiler 可以增量采用，允许先在代码库的特定部分试用编译器。
原文出处：React Compiler can be adopted incrementally, allowing you to try
         it on specific parts of your codebase first.
模型答案：React Compiler 的增量采用是指允许你先在代码库的特定部分尝试
         编译器，在现有项目中逐步推出，让你控制推出节奏。
判定：correct
原因：覆盖标准答案两个核心点——"增量采用" + "代码库特定部分"。
     "逐步推出 + 控制节奏"是对原文的合理延伸，没有冲突。

例子 2（wrong）：
问题：Spring 中 prototype 作用域的 Bean 行为是？
标准答案：prototype Bean 每次被请求时都会创建新实例。
原文出处：A prototype-scoped bean creates a new instance every time it is requested.
模型答案：prototype Bean 是单例的，全局共享同一个实例。
判定：wrong
原因：跟标准答案完全相反——标准答案明确"每次新建"，模型答的"单例"
     是 singleton 的行为，属于事实冲突。

---

现在请判分以下样本：

【问题】{question}
【标准答案】{gold_answer}
【原文出处】
1. {gold_evidence_1}
2. {gold_evidence_2}
（无原文出处则跳过此段）
【模型答案】{model_answer}

只返回 JSON，不要其他文字：
{
  "verdict": "correct" 或 "wrong",
  "reason": "一句话说明，引用标准答案或原文的具体点"
}
```

### 4.4 缓存策略

- **缓存 key**：`SHA256(question_id || model_answer || gold_answer || judge_model || judge_prompt_version)`
  - 加 `gold_answer` 是为了：以后黄金集修订（比如评委更新答案），同一 model_answer 也会重新判
  - `judge_prompt_version` 是 prompts.py 里的常量字符串（如 `"v1.0"`），prompt 任何改动都要 bump 这个版本号，老缓存随之自动失效
- **缓存值**：`{verdict, reason, judged_at, latency_ms}`
- **存储**：每个 cache key 一个文件 `eval/cache/<sha>.json`（避免单文件并发写冲突）
- **命中行为**：直接读，不调 LLM，日志打印 `[CACHE HIT] <id>`

### 4.5 失败处理

| 失败场景 | 重试策略 | 兜底 |
|---|---|---|
| 单次 API 超时（默认 90s）| 重试 2 次（按 AIGW 截图）| 标 `judge_failed` |
| 429 限流 | 指数退避 5s/10s/20s | 跑完所有题再补判 |
| 500 InternalServerError | 重试 2 次 | 标 `judge_failed` |
| 401/400 | 重试 2 次（按 AIGW 截图）| 标 `judge_failed` |
| 裁判返回非合法 JSON | 重试 3 次（每次重新调）| 标 `judge_failed` |
| `judge_failed` 题 | 单独列出，不算分子也不算分母 | 报告专门一节展示 |

### 4.6 并发

- 默认 `--concurrency=4`
- 用 `asyncio` + `aiohttp`
- 估时：200 题 / 4 并发 × 3-5s/题 = **2-4 分钟**（缓存全冷）
- 缓存全热：< 5 秒

---

## 五、指标定义

### 5.1 5 个口袋分类

每题落进且仅落进一个口袋：

|  | **模型作答** | **模型拒答** |
|---|---|---|
| **gold 标"可答"** | 答对 ✅ / 答错 ❌（看裁判）| 不该拒拒了（漏题）|
| **gold 标"不可答"** | **该拒没拒（幻觉）** ⚠️ | 拒答正确 ✅ |

5 个口袋之和 = 总题数（200）。

### 5.2 顶层 6 个数

| 指标 | 公式 | 说明 |
|---|---|---|
| `score` | `(答对 + 拒答正确) / 总数` | 总分（比赛核心数字）|
| `answer_acc` | `答对 / (答对+答错)` | 答对率（仅作答题）|
| `refuse_precision` | `拒答正确 / (拒答正确+该拒没拒)` | 拒答正确率 |
| `hallucination_rate` | `该拒没拒 / (拒答正确+该拒没拒)` | 幻觉率（最危险指标）⚠️ |
| `false_refuse_rate` | `不该拒拒了 / (答对+答错+不该拒拒了)` | 误拒率 |
| `avg_confidence` | `mean(model.confidence)` | 仅作答题平均置信度 |

### 5.3 检索指标

每题对照 gold_sources：
- **严格命中**：(doc_path, anchor) 完全相等
- **宽松命中**：仅 doc_path 相等

聚合：
- `hit_rate_strict_at_k` = % of 题 where ≥1 严格命中（在 top-K citations 内）
- `hit_rate_loose_at_k` = % of 题 where ≥1 宽松命中
- `citation_precision_strict` = mean over 题 of `(citations 中严格命中数 / citations 总数)`

> 检索指标只算**模型作答的题**（答对+答错），分母为这两类之和。
> "不该拒拒了"虽然是 gold 可答的题，但模型选择了拒答 → 没产出 citations → 无法算 hit/precision，跳过。
> "拒答题"（拒答正确 + 该拒没拒）同样无 citations，跳过。

### 5.4 分组维度

- 按 domain：React / Kubernetes / Spring Framework
- 按 difficulty：easy / medium
- 按 answer_type：concept / usage / config / ...（从 gold 读，自动分组）

每组都给出 5 口袋数 + 顶层 6 个数（核心 4 个：score/answer_acc/refuse_precision/hit_rate）。

---

## 六、报告格式

### 6.1 .md 报告骨架

```markdown
# RAG 评分报告 — <run_id>

## 一、元信息
- 时间：YYYY-MM-DD HH:MM:SS
- 总耗时：N 分 M 秒
- git commit：<hash>
- 输入文件：gold + results 文件路径
- 参数：judge_model / strictness / top_k / concurrency / X1.5_enabled
- 题数：200（msg ID match 200，gold-only 0，results-only 0）

## 二、总分（一屏看完）
[6 个核心数大表]
[5 个口袋数：答对 X / 答错 Y / 拒答正确 Z / 该拒没拒 P / 不该拒拒了 Q]
[检索 3 个数：hit@5 严格 / hit@5 宽松 / citation_precision]

## 三、按 domain 分组
| Domain | 题数 | 总分 | 答对率 | hit@5严 | hit@5宽 | 拒答正确率 | 幻觉率 |
| React | 50 | ... | ... | ... | ... | ... | ... |
| Kubernetes | 75 | ... | ... | ... | ... | ... | ... |
| Spring Framework | 75 | ... | ... | ... | ... | ... | ... |

## 四、按难度分组
| | 题数 | 总分 | 答对率 | hit@5严 |
| easy | 110 | ... | ... | ... |
| medium | 90 | ... | ... | ... |

## 五、Bad Cases（人工 review 用）

### 5.1 该拒没拒（幻觉）— N 题 ⚠️
为每题列：
- id / domain / difficulty
- question
- gold.answer（如果是 trap 题，标注"标准答案：不可答"）
- model.answer（系统瞎编的内容）
- citations（系统引用了什么）

### 5.2 答错 Top 10（按 model.confidence 倒序——置信度越高错得越离谱）
为每题列：
- id / domain / difficulty
- question
- gold.answer
- model.answer
- judge.reason（裁判的判定理由）
- gold_sources vs model.citations 对比

### 5.3 检索 miss Top 10（答错且 hit@5 严格也没中，按 confidence 倒序）
为每题列：
- id / question
- gold_sources（标准答案在哪）
- model.citations（系统找了哪）

### 5.4 不该拒拒了（漏题）— N 题
为每题列：
- id / question
- gold.answer
- model 拒答时的 confidence

### 5.5 Judge Failed — N 题（如有）
为每题列：
- id / question / 失败原因（timeout/InvalidJSON/...）

## 六、附录
- per_question 全量数据 → 见 .json 报告
```

### 6.2 .json schema

```json
{
  "meta": {
    "run_id": "2026-05-03-batch200",
    "timestamp": "2026-05-03T17:30:00Z",
    "duration_seconds": 187,
    "git_commit": "abc1234",
    "params": {
      "judge_model": "aliyun/deepseek-v3.2",
      "judge_strictness": "medium",
      "judge_timeout": 90,
      "top_k": 5,
      "concurrency": 4,
      "judge_prompt_version": "v1.0"
    },
    "input": {
      "gold_path": "...", "gold_count": 200,
      "results_path": "...", "results_count": 200,
      "matched": 200, "gold_only": 0, "results_only": 0
    }
  },
  "totals": {
    "total": 200,
    "answer_correct": 130, "answer_wrong": 30,
    "refuse_correct": 18, "refuse_missed": 4, "refuse_false": 18,
    "judge_failed": 0,
    "data_error": 0, "missing": 0
  },
  "summary": {
    "score": 0.74,
    "answer_acc": 0.81,
    "refuse_precision": 0.82,
    "hallucination_rate": 0.18,
    "false_refuse_rate": 0.10,
    "avg_confidence": 0.81,
    "hit_rate_strict_at_5": 0.62,
    "hit_rate_loose_at_5": 0.84,
    "citation_precision_strict": 0.71
  },
  "by_domain": {
    "React": { /* totals + summary 同顶层结构 */ },
    "Kubernetes": { /* ... */ },
    "Spring Framework": { /* ... */ }
  },
  "by_difficulty": {
    "easy": { /* ... */ },
    "medium": { /* ... */ }
  },
  "by_answer_type": { /* concept / usage / config / ... */ },
  "per_question": [
    {
      "id": "react_001",
      "domain": "React",
      "difficulty": "easy",
      "answer_type": "concept",
      "bucket": "answer_correct",
      "judge": {
        "verdict": "correct",
        "reason": "覆盖了标准答案的核心点 + 增量采用",
        "latency_ms": 3420,
        "cache_hit": false
      },
      "retrieval": {
        "hit_strict_at_5": true,
        "hit_loose_at_5": true,
        "gold_sources_count": 1,
        "strict_hits": 1,
        "loose_hits": 1,
        "citation_precision": 1.0
      },
      "model": {
        "is_refusal": false,
        "confidence": 0.9975,
        "citations_count": 3
      }
    }
    // ...
  ],
  "bad_cases": {
    "wrong_answer_top10": [/* per_question entries */],
    "retrieval_miss_top10": [/* ... */],
    "hallucination": [/* ... */],
    "false_refuse": [/* ... */],
    "judge_failed": [/* ... */]
  }
}
```

---

## 七、配置

- **API key**：复用 `src/.env.aigw`（已 gitignored）
- **base_url**：`https://aigw.asiainfo.com/v1`（默认）
- 不新建 .env 文件

---

## 八、测试策略

| 类型 | 内容 | 速度 |
|---|---|---|
| unit | metrics（recall/refusal/aggregate）算法纯函数测试 | 毫秒级 |
| unit | judge 模块用 mock LLM 响应（不真调 AIGW）| 毫秒级 |
| unit | render（md/json）输出格式校验 | 毫秒级 |
| integration | 用 `tests/fixtures/sample_*` 跑全流程，断言报告字段存在 | 真调 AIGW，几秒 |

测试 fixture：从今天 smoke run 的 10 题真实输出取，固化到 `eval/tests/fixtures/`。

覆盖率目标：unit ≥80%（不含 LLM 调用部分）。

---

## 九、明确不做的（YAGNI 清单）

- ❌ X0 baseline 自动对比（接口保留，未来扩展）
- ❌ Web UI / 实时 dashboard
- ❌ 多轮判分投票
- ❌ 答案翻译/格式归一
- ❌ strict/loose 严格度（接口保留，仅 medium 实现）
- ❌ 自动按答案 hash 检测系统改动（用户手动指定 run_id 即可）

---

## 十、开放问题

无。设计已 6 轮迭代收敛，所有清晰度问题在 brainstorm 阶段已闭环。

---

## 十一、名词解释（5 问展开）

### 1. LLM-as-judge（用 AI 当裁判）
- **解决什么**：人工逐题判 200 题对错太慢，让另一个 AI 自动判
- **没它会怎样**：只能人工抽查 30 题，无法得到 200 题完整分数
- **流程哪一步**：第 2 阶段 judge，每题调一次 DeepSeek
- **输入输出**：输入 (问题+标准答案+原文+模型答案) → 输出 {verdict, reason}
- **本项目非要它不可吗**：是。200 题 × 200 字答案，人工要看 1-2 小时；LLM-judge 几分钟搞完

### 2. Recall@K（前 K 命中率）
- **解决什么**：判断系统的"找资料"能力——它从知识库里捞回的前 K 个文档片段，是不是包含了正确答案应该出自的位置
- **没它会怎样**：只看最终答案对不对，看不出"是检索没找对、还是 LLM 没答对"
- **流程哪一步**：第 3 阶段 recall
- **输入输出**：输入 (gold_sources, model.citations[:K]) → 输出 {hit_strict, hit_loose}
- **本项目非要它不可吗**：是。诊断"答错"的根因——检索 miss 还是 LLM 写歪

### 3. 拒答（refusal）
- **解决什么**：系统遇到答不出的题时，主动说"抱歉我不知道"，而不是瞎编一个
- **没它会怎样**：所有题都强答，幻觉率飙高
- **流程哪一步**：reasoning 模块在低置信度时返回 `is_refusal=true`
- **输入输出**：输入 (检索分数+其他信号) → 输出 bool
- **本项目非要它不可吗**：是。Public_Test_Set 含 trap 题（标 is_answerable=false），不拒答的话 trap 题全错

### 4. 幻觉（hallucination）
- **解决什么**（不是"解决"，是"识别"）：系统在不该答的题上瞎编内容
- **没它会怎样**：用户被错误信息误导，信任崩塌
- **流程哪一步**：评分阶段，"该拒没拒"口袋
- **输入输出**：输入 (gold.is_answerable=false, model.is_refusal=false) → 标记为幻觉
- **本项目非要它不可吗**：是，且**这是 RAG 系统最致命的指标**——比答错严重得多

### 5. Few-shot（少样本示范）
- **解决什么**：在 prompt 里塞 1-2 个"这种情况判 X"的例子，让 LLM 学会怎么判
- **没它会怎样**：LLM 只看抽象规则，会按自己理解发挥，判分不稳定
- **流程哪一步**：judge prompt 模板里固定写死
- **输入输出**：模板的一部分，每次调用都带上
- **本项目非要它不可吗**：是。我们专门加了 prototype/singleton 反例，避免 DeepSeek 用世界知识跑偏

### 6. AIGW（移动云统一 AI 网关）
- **解决什么**：公司内部统一的 LLM API 网关，对接多个模型（GLM、DeepSeek、Qwen 等）
- **没它会怎样**：要直接调阿里云/OpenAI，配置散乱
- **流程哪一步**：judge 模块发 HTTP POST 到 `aigw.asiainfo.com/v1/chat/completions`
- **输入输出**：输入 OpenAI 标准格式 → 输出 OpenAI 标准格式
- **本项目非要它不可吗**：是。比赛 key 仅在 AIGW 上有效

### 7. 黄金集（gold set）
- **解决什么**：人工标注的"标准答案"集合，作为评分的真理来源
- **没它会怎样**：没法量化系统好坏
- **流程哪一步**：第 1 阶段 load 时读取
- **输入输出**：输入 JSONL 文件 → 输出 dict[id → 标准答案 + 出处]
- **本项目非要它不可吗**：是。Public_Test_Set.jsonl 就是评委给的黄金集

### 8. 严格 vs 宽松匹配（strict vs loose match）
- **解决什么**：判断"系统找到的文档片段"和"标准答案的片段"是否同一处
- **没它会怎样**：只能用一种粒度评分，看不出"找对文件了但锚点错"这种半对的情况
- **流程哪一步**：retrieval 阶段
- **输入输出**：输入 (citation, gold_source) → 输出 {strict_hit, loose_hit}
- **本项目非要它不可吗**：是。我们 chunker anchor 提取偶尔有 bug，宽松命中能定位"问题在 anchor 不在召回"

---

## 十二、变更记录

- 2026-05-03 v1.0：初版（用户 6 轮 brainstorm 后落稿）
