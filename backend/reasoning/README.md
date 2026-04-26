# 推理与引用层（Reasoning Layer）

**Layer 3：上下文注入 → LLM 推理 → 引用验证 Pipeline**

> 直接调用 `backend/LLM/retrieval.py`，**不修改任何 TS 数据处理层代码**。

---

## 目录

- [模块职责](#模块职责)
  
- [文件结构](#文件结构)
  
- [架构关系](#架构关系)
  
- [核心流程](#核心流程)
  
- [组件说明](#组件说明)
  
- [配置系统](#配置系统)
  
- [API 端点](#api-端点)
  
- [安装与启动](#安装与启动)
  
- [代码使用示例](#代码使用示例)
  
- [测试](#测试)
  
- [预留接口（待补齐）](#预留接口待补齐)
  

---

## 模块职责

推理层实现五大核心能力：

| **#** | **能力** | **负责组件** | **说明** |
| --- | --- | --- | --- |
| **1** | **精准注入** | `ContextInjector` | 将检索结果转换为带编号的上下文块，严格控制 Token 上限。 |
| **2** | **双重溯源** | `CitationVerifier` | 执行同步 ID 验证（< 10ms）与后台 Token 级匹配的双重验证逻辑。 |
| **3** | **动态治理** | `ContextGovernor` | 负责上下文去重、逻辑冲突解决以及检索片段的低分过滤。 |
| **4** | **边界严控** | `RejectionGuard` | 针对空查询、无结果或低分场景执行拒答策略，杜绝系统幻觉。 |
| **5** | **效能平衡** | `ReasoningPipeline` | 通过异步验证机制确保响应不被阻塞，利用分级策略最优化吞吐性能。 |

---

## 文件结构

```
backend/reasoning/
├── prompts/
│   └── prompts.yaml          # 所有提示词模板（集中维护，支持热重载）
├── .env                      # LLM API KEY + 多模型配置（⚠️ 含敏感信息，已加入 .gitignore）
├── __init__.py               # 包入口，统一导出所有公开符号
├── main.py                   # Flask 服务启动入口（CLI 参数解析）
├── interfaces.py             # 检索层接口（WebRequest/WebResponse/search_test）
├── config_loader.py          # 配置加载器（prompts.yaml + .env，带 lru_cache）
├── reasoning_pipeline.py     # 推理管道（编排全流程）          ★ 核心
├── context_injector.py       # 上下文注入器                   [核心1]
├── citation_verifier.py      # 引用验证器                     [核心2]
├── context_governance.py     # 动态治理器                     [核心3]
├── rejection_guard.py        # 拒答守卫                       [核心4]
├── prompt_builder.py         # 提示词构建器（从 prompts.yaml 懒加载）
├── webui.py                  # Flask HTTP + WebSocket 接口层
├── mock_test.py              # 单元测试（47 个用例）
├── requirements.txt          # 依赖清单
└── README.md                 # 本文档
```

---

## 架构关系

```
frontend (Next.js)
      ↕  HTTP / WebSocket
backend/reasoning/           ← 本层（Python）
      ↕  import
backend/LLM/retrieval.py     ← 检索层（Python，不修改）
      ↕
backend/chunking-rag/        ← TS 数据处理层（不修改）
```

- Python 推理层**只调用 retrieval.py，不修改**任何 TS 层代码
  
- TS 层负责文档解析、向量化建库、TS 端 API 路由
  
- `interfaces.py` 封装对 `retrieval.py` 的所有调用，提供稳定的内部接口
  

---

## 核心流程

```
用户问题（query）
      │
      ▼
interfaces.search_test()
  ├─ Query Expansion（关键词扩展）
  ├─ 自适应 TopK（综合型=8 / 事实型=3 / 默认=5）
  └─ retrieval.py pipeline()（BM25 + 向量混合检索 + CrossEncoder 重排）
      │  返回 (docs, reranker_scores)
      ▼
ReasoningPipeline.retrieve_chunks()
  └─ 转换 LangChain Document → RetrievedChunk（补充 chunk_id / anchor_id 等字段）
      │
      ▼
RejectionGuard.evaluate()
  ├─ 空查询 → 拒答（EMPTY_QUERY）
  ├─ 无结果 → 拒答（NO_CHUNKS）
  └─ max(reranker_score) < 0.4 → 拒答（LOW_SCORE）
      │ 通过
      ▼
ContextGovernor.govern()
  ├─ 按 reranker_score 降序排列
  ├─ Jaccard 相似度去重（阈值 0.95）
  ├─ 同文件相邻冲突解决（keep_higher_score / keep_both / merge）
  └─ 过滤 score < 0.1 的低质量块
      │
      ▼
ContextInjector.inject()
  ├─ 余弦相似度去重（阈值 0.95）
  ├─ Token 预算控制（1 token ≈ 4 chars，默认上限 6000 tokens）
  └─ 分配从 1 开始的连续 ID → ContextBlock 列表
      │
      ▼
LLM 推理（prompts/prompts.yaml 中的严格引用 Prompt）
  ├─ 同步模式：_generate_with_llm()
  └─ 流式模式：_stream_generate() → yield StreamEventToken
      │
      ▼
CitationVerifier.sync_verify()            （< 10ms，O(1) dict 查找）
  ├─ 提取回答中的 [n] 引用 ID
  ├─ 验证 ID 是否真实存在于 ContextBlock 列表
  └─ 清理无效引用（替换为 [n❓]）
      │
      ▼
CitationVerifier.async_verify()           （后台执行，不阻塞响应）
  ├─ 提取引用上下文（前后各 50 字符）
  ├─ 提取关键 Token（版本号 / 数字+单位 / 专有名词 / 配置项 / 关键词）
  └─ Token 级匹配：≥0.8 → VERIFIED，>0 → UNCERTAIN，0 → FAILED
      │
      ▼
WebResponse（含 citations 引用溯源 + verification_report）
```

---

## 组件说明

### `ReasoningPipeline`（`reasoning_pipeline.py`）

推理主控，编排全部阶段。

```python
from reasoning import ReasoningPipeline, ReasoningPipelineConfig, LLMConfig

# 方式 1：从 .env 自动加载（推荐）
pipeline = ReasoningPipeline()

# 方式 2：显式指定配置
cfg = ReasoningPipelineConfig(
    llm=LLMConfig(api_key='sk-xxx', model='glm-4-flash', provider='glm5',
                  base_url='https://open.bigmodel.cn/api/paas/v4'),
    score_threshold=0.4,
    enable_async_verification=True,
    enable_governance=True,
)
pipeline = ReasoningPipeline(cfg)

# 同步推理
from reasoning import ReasoningRequest
req = ReasoningRequest(query='如何配置 OAuth2？', chunks=chunks)
resp = pipeline.reason(req)

# 流式推理
async for event in pipeline.stream_reason(req):
    print(type(event).__name__, event)

# 运行时切换 provider
pipeline.switch_provider('kimi')
```

**`LLMConfig.from_file()`** 加载优先级（从高到低）：

| **优先级** | **配置来源** | **详细描述** | **适用场景** |
| --- | --- | --- | --- |
| **P0 (最高)** | **系统环境变量** | 直接在 shell 或容器中设置的 `LLM_API_KEY` 等变量。 | 生产环境、Docker 部署、CI/CD 流水线。 |
| **P1** | **`.env` 配置文件** | `.env` 中受 `LLM_ACTIVE_PROVIDER` 指定的特定供应商配置块。 | 本地开发、个性化调试。 |
| **P2 (最低)** | **内置默认值** | 代码中 hard-coded 的默认项（如 `openai / gpt-4-turbo`）。 | 项目初始化、未配置任何参数时。 |

---

### `ContextInjector`（`context_injector.py`）

将 `RetrievedChunk` 列表转换为模型可消费的 `ContextBlock` 列表。

- **去重**：余弦相似度（TF 向量），阈值 0.95
  
- **截断**：按 token 预算裁剪（`max_tokens * 4` chars），最后一块标 `is_truncated=True`
  
- **ID 分配**：从 1 开始的连续整数，与回答中的 `[n]` 一一对应
  

```python
injector = ContextInjector()
blocks, was_truncated, total_chars = injector.inject(chunks, max_tokens=6000)
formatted = injector.format_for_prompt(blocks)  # 生成可读字符串
```

---

### `CitationVerifier`（`citation_verifier.py`）

双重验证机制：

| **阶段** | **执行方法** | **典型延迟** | **逻辑说明** |
| --- | --- | --- | --- |
| **1. 同步验证** | `sync_verify()` | **< 10ms** | 基于 Dict 索引的 $O(1)$ 查找，仅确认 ID 是否在合法库中。 |
| **2. 异步验证** | `async_verify()` | **后台** | 执行 Token 级模糊匹配，完成后更新 `verification_status` 字段。 |

---

### `ContextGovernor`（`context_governance.py`）

三阶段治理：

1. **去重**：Jaccard 相似度（分词后），阈值 0.95，高分优先保留
  
2. **冲突解决**：同文件 + 偏移差 < 500 字符 + Jaccard > 0.7 → 视为冲突
  

   - `keep_higher_score`（默认）：保留分数较高者

   - `keep_both`：两者保留

   - `merge`：合并内容

3. **低分过滤**：`reranker_score < 0.1` 直接丢弃

---

### `RejectionGuard`（`rejection_guard.py`）

四项拒答检查（按顺序）：

| **检查项** | **错误代码 (reason_code)** | **触发条件** | **处理策略** |
| --- | --- | --- | --- |
| **空查询** | `empty_query` | `query.strip() == ""` | 拦截请求，返回 400 错误 |
| **无结果** | `no_chunks` | `len(chunks) == 0` | 返回空列表，不进入重排阶段 |
| **低分过滤** | `low_score` | `max_score < threshold` (0.4) | 判定为无关内容，不召回上下文 |
| **合法请求** | —   | 上述均不满足 | **PASSED**：进入后续生成阶段 |

---

### `PromptBuilder`（`prompt_builder.py`）

从 `prompts/prompts.yaml` 懒加载提示词模板，支持：

- `build()` → `(system_prompt, user_prompt)` 元组
  
- `build_stream_message()` → 流式生成单条消息
  
- `extract_citation_ids()` → 从回答中提取 `[n]` ID 列表（保序去重）
  

---

### `config_loader.py`

统一配置加载，所有读取均带 `lru_cache`：

```python
from reasoning.config_loader import (
    load_prompts_config,    # → PromptsConfig（prompts.yaml）
    load_llm_config,        # → LLMConfig（.env 环境变量）
    get_active_llm_config,  # → LLMProviderConfig（当前激活 provider）
    reload_configs,         # 清除缓存，触发热重载
)

# 查看当前 provider 是否已正确配置
cfg = get_active_llm_config()
print(cfg.is_configured())  # api_key 非占位符 → True
```

---

## 配置系统

### `.env` — LLM 配置（主要配置文件）

LLM 配置

### `prompts/prompts.yaml` — 提示词模板

```yaml
system_prompt: |
  你是一个严格的技术文档问答助手。
  回答必须严格基于提供的 Context，每个事实陈述后标注 [引用ID]。
user_prompt_template: |
  【Context】
  {context}
  ---
  【问题】
  {query}
rejection_prompt: "根据现有文档无法回答此问题。得分：{max_score}"
stream_message_template: |
  【Context】
  {context}
  {truncation_warning}【问题】{query}
  请严格基于 Context 回答，每个事实陈述后标注 [引用ID]。
```

修改 `prompts.yaml` 后调用 `reload_configs()` 即可热生效，无需重启服务。

---

## API 端点

> 所有端点由 `webui.py` 注册到 Flask Blueprint，前缀 `/api/reasoning`。

| **接口分类** | **端点 (Endpoint)** | **方法** | **功能说明** | **响应模式** |
| --- | --- | --- | --- | --- |
| **核心推理** | `/api/reasoning/ask` | `POST` | 标准同步推理问答 | `application/json` |
| **实时交互** | `/api/reasoning/ask-stream` | `POST` | 基于 SSE 的流式增量推理 | `text/event-stream` |
| **双工通信** | `/ws/reasoning` | `WS` | 全双工 WebSocket 推理（需 `flask-sock`） | `Binary / Text` |
| **运维监控** | `/api/reasoning/health` | `GET` | 检查服务存活状态及依赖项 | `application/json` |
| **运维监控** | `/api/reasoning/stats` | `GET` | 统计 QPS、Token 消耗及延迟 | `application/json` |

### 请求体（`/ask`）

```json
{
  "user_query": "如何配置 OAuth2 认证？",
  "stream": false,
  "session_id": "sess_001",
  "config": {
    "temperature": 0.0,
    "language": "zh-CN"
  }
}
```

### 成功响应（`answer_status: "resolved"`）

```json
{
  "answer": "根据文档[1]，OAuth2 认证需要先申请 client_id...",
  "answer_status": "resolved",
  "citations": [
    {
      "citation_handle": "[1]",
      "source_id": "src_idx_001",
      "snippet": "OAuth2 认证流程：1. 申请 client_id...",
      "location": {
        "file_path": "docs/auth.md",
        "anchor_id": "docs/auth.md#4821",
        "title_path": "Authentication > OAuth2 > Token Refresh"
      }
    }
  ],
  "source_library": {
    "src_idx_001": {
      "title": "Auth Guide",
      "url": "docs/auth.md",
      "display_url": "docs/auth.md#step-oauth",
      "update_time": "2026-04-24 14:50"
    }
  },
  "verification_report": {
    "hallucination_check": "passed",
    "citation_validation": "sync_verified",
    "is_truncated_context": false
  },
  "debug_info": {
    "max_reranker_score": 0.92,
    "refuse_reason": null
  }
}
```

### 拒答响应（`answer_status: "refused"`）

```json
{
  "answer": "根据现有文档无法回答此问题。\n\n提示：当前检索得分（0.31）低于系统阈值（0.40）。",
  "answer_status": "refused",
  "citations": [],
  "verification_report": {
    "hallucination_check": "skipped",
    "citation_validation": "skipped",
    "is_truncated_context": false
  },
  "debug_info": {
    "max_reranker_score": 0.31,
    "refuse_reason": "low_score"
  }
}
```

---

## 安装与启动

```bash
cd backend/reasoning
pip install -r requirements.txt

# ── Fake LLM 模式（不调用真实 API，测试检索 + 拒答逻辑）
python -m reasoning.main --fake-llm
# ── 从 .env 加载模型（先填写 api_key）
python -m reasoning.main
# ── 命令行覆盖 provider（优先级高于 .env）
python -m reasoning.main --provider kimi
# ── 运行内置测试查询后退出
python -m reasoning.main --test --fake-llm
# ── 自定义端口和拒答阈值
python -m reasoning.main --port 5051 --score-threshold 0.3
# ── 环境变量方式（优先级最高）
LLM_API_KEY=sk-xxx LLM_MODEL=glm-4-flash python -m reasoning.main
```

### 命令行参数

| **分类** | **参数** | **默认值** | **功能说明** |
| --- | --- | --- | --- |
| **网络配置** | `--host` | `0.0.0.0` | 绑定的监听地址。设置为 `0.0.0.0` 以允许外部访问。 |
|     | `--port` | `5050` | 服务监听端口。 |
| **业务逻辑** | `--provider` | `.env` 指定值 | 指定 LLM 供应商。**注意：** 此参数将覆盖 `.env` 文件中的配置。 |
|     | `--score-threshold` | `0.4` | **拒答阈值**。Reranker 分数低于此值时将触发 `low_score` 逻辑。 |
| **调试测试** | `--fake-llm` | `False` | **模拟模式**。开启后不调用真实 API，仅返回固定模拟文本，节省成本。 |
|     | `--test` | `False` | **冒烟测试**。启动并运行一次测试查询，验证全链路联通后自动退出。 |

### 检查当前配置

```bash
python reasoning/config_loader.py
```

---

## 代码使用示例

### 最简调用（从外部模块使用）

```python
from reasoning import ReasoningPipeline, ReasoningRequest
pipeline = ReasoningPipeline()  # 自动从 .env 加载配置
# 检索 + 推理（两步合一）
chunks = pipeline.search_test_chunks("如何配置环境变量")[0]
req = ReasoningRequest(query="如何配置环境变量", chunks=chunks)
resp = pipeline.reason(req)
print(resp.answer)
print(resp.citations)
print(resp.confidence)
```

### 使用 retrieval.py（原始检索接口）

```python
# retrieve_chunks() 内部调用 retrieval.py，仅在 backend/LLM 可访问时可用
chunks = pipeline.retrieve_chunks("BM25 检索原理", top_k=5)
```

### 流式推理

```python
import asyncio
from reasoning import ReasoningPipeline, ReasoningRequest
async def stream():
    pipeline = ReasoningPipeline()
    chunks = pipeline.search_test_chunks("OAuth2 刷新 Token")[0]
    req = ReasoningRequest(query="OAuth2 刷新 Token", chunks=chunks)
    async for event in pipeline.stream_reason(req):
        if event.type == 'token':
            print(event.content, end='', flush=True)
        elif event.type == 'citation':
            print(f'\n[引用] {event.citation.anchor_id}')
        elif event.type == 'done':
            print(f'\n完成，置信度: {event.response.confidence}')
asyncio.run(stream())
```

### 运行时切换 Provider

```python
pipeline.switch_provider('minimax')   # 从 .env 重新加载 minimax 配置
pipeline.switch_provider('qwen')
pipeline.set_score_threshold(0.3)     # 调整拒答阈值
```

### 单独使用各组件

```python
from reasoning import (
    ContextGovernor, ContextInjector,
    CitationVerifier, RejectionGuard,
)
# 治理
governor = ContextGovernor()
result = governor.govern(chunks)
print(result.stats)  # {'original_count': 10, 'final_count': 6, 'removal_ratio': 0.4}
# 验证
verifier = CitationVerifier()
sync_result = verifier.sync_verify(claimed_ids=[1, 2, 5], context_blocks=blocks)
print(sync_result.invalid_citations)  # [5]
# 提取关键 Token
tokens = verifier.extract_key_tokens("使用 JWT Token 认证，版本 v2.0.1 以上")
# → ['v2.0.1', 'JWT', 'Token']
```

---

## 测试

```bash
# 运行全部 47 个测试用例
python mock_test.py

# 指定套件（详细模式）
python -m unittest mock_test.TestMockReasoningPipeline -v
# 运行配置检查
python reasoning/config_loader.py
```

### 测试套件覆盖

| **测试套件 (Suite Name)** | **用例数** | **核心验证范围** | **验证属性** |
| --- | --- | --- | --- |
| **TestInterfaceDataclasses** | 10  | 基础模型：字段类型校验、`display_url` 解析、`embedding_meta` 结构及 `content_type_source` 映射。 | 单元测试 |
| **TestHelperFunctions** | 6   | 辅助逻辑：`_expand_query` 扩充效果、`_get_adaptive_topk` 动态分配策略、`_parse_document_chunk` 结构化解析。 | 算法逻辑 |
| **TestMockSearchTest** | 10  | 检索 Mock 层：模拟数据注入、检索行为拦截、调用日志 (`call_log`) 审计。 | Mock/桩测试 |
| **TestMockReasoningPipeline** | 17  | 推理管线：覆盖 **正常回答**、**低分拒答**、**流式 SSE 输出** 三条关键业务路径。 | 集成测试 |
| **TestSearchTestIntegration** | 4   | 系统集成：端到端验证，在不依赖真实向量库的情况下模拟全流程闭环。 | 端到端 (E2E) |

---

## 预留接口（待补齐）

以下字段当前由推理层以估算值填充，待检索层完善后对齐：

### `anchor_id` — 精确字符偏移锚点

| **维度** | **内容说明** |
| --- | --- |
| **现状 (Status)** | `retrieval.py` 输出的 `Document.metadata` 中缺少 `char_offset_start` 字段。 |
| **过渡方案 (Temporary)** | 采用**逻辑估算**：格式为 `file_path#{rank * 1000}`。 |
| **补齐方式 (Resolution)** | **数据入库阶段**：在 `Ingestion` 切片时，记录每个 Chunk 在原文件中的 `char_offset_start` 并写入 Metadata。 |
| **业务影响 (Impact)** | 实现前端 UI 渲染时，点击引用链接可直接**高亮并跳转**到原文的精确位置。 |

### `file_hash` — 文件哈希

| **维度** | **内容说明** |
| --- | --- |
| **现状 (Status)** | `retrieval.py` 接口目前不返回文件指纹信息。 |
| **过渡方案 (Temporary)** | 硬编码为空字符串 `''`。 |
| **补齐方式 (Resolution)** | **建库阶段**：计算原始文件的 `SHA-256` 或 `MD5` 值，并持久化到 `Document.metadata`。 |
| **业务影响 (Impact)** | 支持**文件完整性校验**、**增量更新检测**以及避免重复文档造成的冗余检索。 |

### `title_path` — 可读标题路径

| **维度** | **内容说明** |
| --- | --- |
| **现状 (Status)** | 尝试从 `title_path` 或 `heading` 读取，若字段不存在则返回 `None`。 |
| **补齐方式 (Resolution)** | **解析阶段**：利用文档解析器（如 Markdown Parser）提取 `H1->H2->H3` 的**标题树路径**。 |
| **业务影响 (Impact)** | 引用来源将以**面包屑导航**形式显示（例如：`Authentication > OAuth2 > Token Refresh`）。 |

### `reranker_score` — ✅ 已补齐

已于 2026-04-24 补齐：修改 `Reranker.rerank()` 返回 `(doc, score)` 元组，`pipeline()` 返回 `(docs, reranker_scores)`，推理层直接消费 CrossEncoder 真实分数。