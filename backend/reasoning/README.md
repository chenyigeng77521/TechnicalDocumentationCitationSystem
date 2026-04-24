# 推理与引用层（Python）

**Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline**

> Python 实现，严格对齐 TypeScript 版 `backend/chunking-rag/src/Reasoning/`，  
> 直接调用 `backend/LLM/retrieval.py` 检索层，**不修改任何 TS 数据处理层代码**。

---

## 文件结构

```
backend/reasoning/
├── __init__.py              # 模块入口（对齐 TS index.ts）
├── main.py                  # 服务启动入口
├── types.py                 # 类型定义（对齐 TS types.ts）
├── context_injector.py      # 上下文注入器  [核心1: 精准注入]
├── citation_verifier.py     # 引用验证器    [核心2: 双重溯源]
├── context_governance.py    # 动态治理器    [核心3: 动态治理]
├── rejection_guard.py       # 拒答守卫      [核心4: 边界严控]
├── reasoning_pipeline.py    # 推理管道      [核心5: 效能平衡]
├── prompt_builder.py        # 提示词构建器
├── webui.py                 # Flask HTTP + WebSocket 接口
├── requirements.txt         # 依赖清单
└── README.md                # 本文档
```

---

## 与 TS 数据处理层的关系

Python 层**只调用，不修改** TS 层的任何代码。

```
frontend (Next.js)
    ↕
backend/chunking-rag/ (TypeScript 数据处理层)   ← 不动
    ↕                                               ↕
backend/reasoning/ (Python 推理层)  ─────── backend/LLM/retrieval.py
```

- `retrieval.py` 是 Python 检索层，Python 推理层直接 import 它
- TS 数据处理层负责文档解析、存储、TS 端的 API 路由

---

## ⚠️ 预留接口

以下是 **retrieval.py 现有能力未覆盖**、但推理层需要的字段，  
目前由 Python 推理层用估算值填充，待后续完善：

### 1. `reranker_score`（真实重排序分数）- ✅ 已补齐

| 项目 | 说明 |
|------|------|
| 位置 | `reasoning_pipeline.py` → `retrieve_chunks()` |
| 补齐状态 | ✅ **已于 2026-04-24 补齐**，修改 `Reranker.rerank()` 返回 `(doc, score)` 元组，`pipeline()` 返回 `(docs, reranker_scores)` |
| 影响范围 | 拒答守卫阈值判断、上下文治理过滤、置信度计算 |

---

### 2. `anchor_id`（精确字符偏移锚点）

| 项目 | 说明 |
|------|------|
| 位置 | `reasoning_pipeline.py` → `retrieve_chunks()` |
| 现状 | `retrieval.py` 的 Document.metadata 不含 `char_offset_start` |
| 当前方案 | 估算 `file_path#{rank * 1000}` |
| 需要补齐 | 建库时在 Document.metadata 中写入 `char_offset_start`，Python 推理层读取 |
| 影响范围 | 前端跳转到原文的精确锚点 |

---

### 3. `file_hash`（文件哈希）

| 项目 | 说明 |
|------|------|
| 位置 | `reasoning_pipeline.py` → `retrieve_chunks()` |
| 现状 | retrieval.py 不提供文件哈希 |
| 当前方案 | 空字符串 `''` |
| 需要补齐 | 建库时在 Document.metadata 中写入 `file_hash` |
| 影响范围 | 文件完整性校验 |

---

### 4. `title_path`（可读标题路径）

| 项目 | 说明 |
|------|------|
| 位置 | `reasoning_pipeline.py` → `retrieve_chunks()` |
| 现状 | 从 Document.metadata 的 `title_path` / `heading` 字段读取 |
| 当前方案 | 若 metadata 无此字段则为 `None` |
| 需要补齐 | 建库时解析标题层级写入 metadata |
| 影响范围 | 引用来源的可读性（前端显示 `Authentication > OAuth2 > Token Refresh`） |

---

### 5. WebSocket（flask-sock 依赖）

| 项目 | 说明 |
|------|------|
| 位置 | `webui.py` → `register_websocket()` |
| 现状 | 依赖 `flask-sock`，若未安装则 WS 端点不可用 |
| 当前方案 | 安装 `flask-sock` 后自动激活 |
| 需要补齐 | 无（已实现，安装依赖即可） |

---

### 6. TS DatabaseManager 适配器（预留）

| 项目 | 说明 |
|------|------|
| 位置 | `webui.py` 注释中标注 |
| 现状 | TS 版通过 `setDatabase(DatabaseManager)` 获取 chunks |
| Python 版 | 直接通过 `retrieve_chunks()` 调用 retrieval.py，无需 DatabaseManager |
| 需要补齐 | 若未来需要 Python 层读取 TS 层的 SQLite 数据库，在 webui.py 的 `setDatabase` 位置添加适配器 |

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reasoning/ask` | POST | 普通推理问答（对齐 TS） |
| `/api/reasoning/ask-stream` | POST | 流式推理（SSE，对齐 TS） |
| `/api/reasoning/health` | GET | 健康检查（对齐 TS） |
| `/api/reasoning/stats` | GET | 统计信息 |
| `/ws/reasoning` | WS | WebSocket 推理（对齐 TS，需 flask-sock） |

### 请求格式（/ask）

```json
{
  "question": "如何配置 OAuth2 认证？",
  "topK": 5,
  "strictMode": false,
  "enableAsyncVerification": true
}
```

### 响应格式

```json
{
  "success": true,
  "answer": "根据文档[1]，OAuth2 认证需要...",
  "citations": [
    {
      "id": 1,
      "anchorId": "docs/auth.md#1000",
      "titlePath": "Authentication > OAuth2",
      "score": 0.85,
      "verificationStatus": "verified",
      "filePath": "docs/auth.md",
      "snippet": "OAuth2 认证流程..."
    }
  ],
  "noEvidence": false,
  "maxScore": 0.85,
  "confidence": 0.92,
  "contextTruncated": false,
  "query": "如何配置 OAuth2 认证？"
}
```

---

## 安装与启动

```bash
cd backend/reasoning
pip install -r requirements.txt

# 测试模式（不需要 LLM API Key，检索使用 retrieval.py Mock）
python -m reasoning.main --fake-llm

# 测试查询
python -m reasoning.main --test --fake-llm

# 生产模式
LLM_API_KEY=sk-xxx python -m reasoning.main

# 自定义端口和拒答阈值
python -m reasoning.main --port 5051 --score-threshold 0.3
```

---

## retrieval.py 集成方式

```python
# reasoning_pipeline.py 中的集成（不修改 retrieval.py）
import sys, os
sys.path.insert(0, os.path.abspath('../LLM'))

from retrieval import pipeline as retrieval_pipeline, init_retrieval_system

# 初始化（复用资源，只做一次）
system = init_retrieval_system()

# 每次查询调用（返回 (docs, scores) 元组）
docs, reranker_scores = retrieval_pipeline(
    query,
    vectorstore=system['vectorstore'],
    all_documents=system['documents'],
    ensemble_retriever=system['ensemble_retriever'],
)
# docs: List[langchain_core.documents.Document]
# reranker_scores: List[float]（CrossEncoder 真实分数，与 docs 顺序对应）
```

---

## 核心流程

```
用户问题
    ↓
retrieve_chunks()  ← 调用 retrieval.py（BGE-m3 + BM25 + CrossEncoder）
    ↓
RejectionGuard.evaluate()   [无结果 / 低分 → 拒答]
    ↓
ContextGovernor.govern()    [去重 / 冲突解决 / 低分过滤]
    ↓
ContextInjector.inject()    [分配 ID / 截断控制]
    ↓
LLM 推理                    [严格 Context 引用]
    ↓
CitationVerifier.sync_verify()    [同步 ID 验证 < 10ms]
    ↓
CitationVerifier.async_verify()   [后台 Token 级匹配验证]
    ↓
ReasoningResponse（含 citations 引用溯源）
```

---

## 与 TS 版对比

| 功能 | TS 版 | Python 版 |
|------|-------|-----------|
| 检索层 | 调用 `DatabaseManager.searchChunks()` | 调用 `retrieval.py` pipeline() |
| LLM 调用 | `openai` npm 包 | `openai` Python 包 |
| WebSocket | `ws` npm 包 | `flask-sock` |
| 流式输出 | AsyncGenerator | AsyncGenerator（相同模式） |
| 引用验证 | 同步 + 异步双重验证 | 相同 |
| 拒答守卫 | 相同阈值逻辑 | 相同 |
| 类型系统 | TypeScript interface | Python dataclass |
