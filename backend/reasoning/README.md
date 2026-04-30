# Layer 3 — 推理与引用层

> **RAG 推理服务**：基于检索结果进行大模型推理，并输出带精确引用的结构化答案。

---

## 目录

- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [架构概览](#架构概览)
- [核心 Pipeline](#核心-pipeline)
- [接口文档](#接口文档)
- [配置说明](#配置说明)
- [错误处理与拒答机制](#错误处理与拒答机制)
- [批量处理](#批量处理)
- [依赖说明](#依赖说明)

---

## 项目结构

```
backend/reasoning/
├── main.py              # FastAPI 服务入口（单条 + 批量接口）
├── interfaces.py        # 请求 / 响应数据结构定义（Pydantic）
├── reasoning.py         # 核心推理逻辑（5 步 Pipeline）
├── config.py            # 阈值、LLM 参数、Prompt 模板
├── retrieval.py         # 检索层（Layer 2，已存在，只调用）
├── .env                 # LLM API 密钥（本地配置，不入库）
├── requirements.txt     # Python 依赖
└── eval/                # 批量处理结果落盘目录（自动创建）
```

> `retrieval.py` 由 Layer 2 提供，Layer 3 仅调用其 `pipeline(query)` 函数，不修改该文件。

---

## 快速开始

### 1. 安装依赖

```bash
cd backend/reasoning
pip install -r requirements.txt
```

### 2. 配置 LLM API

编辑 `.env` 文件，填写真实的 API 密钥：

```ini
# 必填：retrieval API 密钥
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# 可选：覆盖默认值
LLM_API_BASE=https://api.deepseek.com   # 默认 DeepSeek，可换为任何 OpenAI 兼容接口
LLM_MODEL=deepseek-chat
LLM_TIMEOUT=60
BATCH_OUTPUT_DIR=./eval
```

### 3. 启动服务

```bash
python main.py
```

服务运行在 **http://0.0.0.0:8001**

### 4. 验证服务

```bash
curl http://localhost:8001/health
# → {"status": "ok", "service": "layer3-reasoning"}
```

---

## 架构概览

```
用户请求
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                  Layer 3 推理服务                     │
│                                                      │
│  POST /api/qa          POST /api/qa/batch            │
│       │                      │                       │
│       └──────────┬───────────┘                       │
│                  ▼                                   │
│          process_single()                            │
│                  │                                   │
│          ┌───────▼────────┐                          │
│          │  retrieve_chunks()  ◄── Layer 2 pipeline  │
│          └───────┬────────┘                          │
│                  │                                   │
│          ┌───────▼────────┐                          │
│          │  run_reasoning()                          │
│          │   5 步 Pipeline                           │
│          └───────┬────────┘                          │
│                  │                                   │
│          ┌───────▼────────┐                          │
│          │  QAResponse    │                          │
│          └────────────────┘                          │
└──────────────────────────────────────────────────────┘
```

---

## 核心 Pipeline

`reasoning.py` 中的 `run_reasoning()` 函数实现完整的 5 步推理链：

### Step 1 — 可回答性判定

| 条件 | 结果 |
|------|------|
| chunks 为空 | 拒答，`refuse_reason = "empty_retrieval"` |
| 最高分 < 0.4 | 拒答，`refuse_reason = "score_below_threshold"` |
| 无 chunk 分数 > 0.5 | 拒答，`refuse_reason = "score_below_threshold"` |

> **核心原则**：在进入 LLM 之前完成可回答性判定，低质检索直接拒答，不浪费 LLM 调用。

### Step 2 — Context 构建

- 按 score **降序**注入 chunk，高质量内容优先
- 格式：`[ID: n, Source: <doc_path> | anchor: <anchor>]\n<原文内容>`
- 超出 `MAX_CONTEXT_CHARS`（9000 字符）时从**低分 chunk** 开始截断
- **严格原文注入，不摘要、不改写**

### Step 3 — LLM 推理

- 调用 OpenAI 兼容接口，`temperature=0.0`（严格模式，抑制幻觉）
- 失败自动 **retry 1 次**（间隔 1 秒）
- 解析 LLM 输出：
  - 输出 `REFUSE` → `refuse_reason = "llm_refuse"`
  - 输出合法 JSON → 提取 `answer` 和 `citation_ids`
  - 解析失败 → `refuse_reason = "json_parse_error"`

### Step 4 — 引用校验（硬一致性验证）

- 校验 `citation_ids` 全部在合法范围（1 ~ used_chunks 数量）内
- 非法 ID 直接剔除
- 若**所有引用均为非法**（LLM 编造） → 拒答，`refuse_reason = "invalid_citation"`

### Step 5 — 语义一致性验证（防幻觉）

- 计算 answer 与每个被引用 chunk 的字符级 bigram 相似度
- 任意一个 chunk 相似度超过阈值 → 通过
- 内置**降阈值二次验证**（应对短答案场景）
- 全部不匹配 → 拒答，`refuse_reason = "semantic_mismatch"`

---

## 接口文档

服务启动后访问 **http://localhost:8001/docs** 查看完整 Swagger 文档。

### GET /health

健康检查。

```json
// 响应
{"status": "ok", "service": "layer3-reasoning"}
```

---

### POST /api/qa — 单条问答

**请求体**

```json
{
  "id": "q001",
  "question": "React 中 useEffect 的清理函数何时执行？"
}
```

> `question` 字段别名为 `query`，两者均可。

**响应体**

```json
{
  "id": "q001",
  "answer": "清理函数在组件卸载前以及下次 effect 执行前调用。",
  "citations": [
    {
      "doc_path": "docs/react/hooks-effect.md",
      "anchor": "#cleaning-up-an-effect"
    }
  ],
  "is_refusal": false,
  "confidence": 0.8731
}
```

**拒答响应示例**

```json
{
  "id": "q001",
  "answer": "抱歉，我无法从提供的文档中找到答案。",
  "citations": [],
  "is_refusal": true,
  "confidence": 0.0
}
```

---

### POST /api/qa/batch — 批量问答

**请求体**

```json
{
  "items": [
    {"id": "q001", "question": "问题一"},
    {"id": "q002", "question": "问题二"},
    {"id": "q003", "question": "问题三"}
  ]
}
```

**响应体**

```json
{
  "status": "success",
  "file_path": "./eval/result_q001.jsonl",
  "total": 3,
  "succeeded": 3,
  "failed": 0
}
```

结果文件为 **JSONL** 格式（每行一条完整 JSON），路径示例：`./eval/result_q001.jsonl`

---

## 配置说明

所有配置集中在 `config.py`，通过 `.env` 可覆盖运行时参数：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SCORE_THRESHOLD` | `0.4` | Reranker 最高分低于此值直接拒答 |
| `SIMILARITY_THRESHOLD` | `0.75` | 语义验证相似度阈值 |
| `MAX_CONTEXT_TOKENS` | `6000` | 上下文最大 token 数（约 9000 字符）|
| `LLM_API_KEY` | `.env` 读取 | LLM API 密钥（必填）|
| `LLM_API_BASE` | `https://api.deepseek.com` | 支持任何 OpenAI 兼容接口 |
| `LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `LLM_TEMPERATURE` | `0.0` | 严格模式，最大程度抑制幻觉 |
| `LLM_TIMEOUT` | `60` | LLM 请求超时（秒）|
| `BATCH_MAX_WORKERS` | `8` | 批量处理线程数 |
| `BATCH_OUTPUT_DIR` | `./eval` | 批量结果落盘目录 |
| `REFUSAL_TEXT` | `"抱歉，我无法从提供的文档中找到答案。"` | 拒答固定文本（对齐赛题格式）|

---

## 错误处理与拒答机制

所有异常均走 **Fail Fast → 拒答** 策略，不向上抛异常，保证服务健壮性。

| 场景 | `refuse_reason` | 处理方式 |
|------|----------------|---------|
| 检索结果为空 | `empty_retrieval` | 直接拒答，不进 LLM |
| 检索分数过低 | `score_below_threshold` | 直接拒答，不进 LLM |
| LLM 调用失败 | `llm_error` | retry 1 次，仍失败则拒答 |
| LLM 主动拒答 | `llm_refuse` | 透传拒答 |
| JSON 解析失败 | `json_parse_error` | 拒答，不输出不可信内容 |
| answer 为空字符串 | `empty_answer` | 拒答 |
| 引用 ID 全部非法 | `invalid_citation` | 拒答，禁止伪造引用 |
| 语义验证不通过 | `semantic_mismatch` | 拒答，防止幻觉输出 |

---

## 批量处理

批量接口的并发实现细节：

```
POST /api/qa/batch
        │
        ▼
ThreadPoolExecutor(max_workers=8)
        │
        ├── 线程 1: process_single(item_0)
        ├── 线程 2: process_single(item_1)
        ├── ...
        └── 线程 n: process_single(item_n)
                │
                ▼
        write_jsonl_line()
                │
        全局文件写锁（threading.Lock per file）
                │
                ▼
        ./eval/result_{first_id}.jsonl  ← JSONL 逐行追加
```

**容错策略**：
- 每条任务独立 `try/except` 包裹，**单条失败不影响整体**
- 失败条目自动写入占位拒答记录（含 `_error` 字段便于排查）
- 文件写入使用**文件级写锁**，保证多线程并发安全

---

## 依赖说明

```
fastapi>=0.111.0      # Web 框架
uvicorn[standard]     # ASGI 服务器
pydantic>=2.7.0       # 数据验证
python-dotenv>=1.0.0  # 环境变量加载
openai>=1.30.0        # LLM 调用（支持任何 OpenAI 兼容接口）
```

> Layer 2 的依赖（如 `langchain`、向量数据库等）由 `retrieval.py` 自行管理，Layer 3 不引入额外检索相关依赖。

---

## 注意事项

1. **不使用外部知识**：Prompt 已明确要求 LLM 仅基于 Context 回答，代码层还通过引用校验和语义验证双重保障。
2. **anchor 格式**：响应中 `anchor` 均以 `#` 开头（如 `#top`、`#hook-rules`），与 HTML 锚点格式一致。
3. **评测提交**：批量接口生成的 JSONL 文件可直接用于评测提交，格式与赛题要求对齐。
4. **更换 LLM**：只需修改 `.env` 中的 `LLM_API_BASE` 和 `LLM_MODEL`，无需改代码（任何 OpenAI 兼容接口均可）。
