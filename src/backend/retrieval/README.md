# 技术文档引用系统 - 检索模块 (Retrieval)

基于 API 的双路混合检索系统，支持向量检索、BM25 全文检索、查询扩展、CrossEncoder 重排序与自适应 TopK 截断。

---

## 目录

- [功能特性](#功能特性)
- [架构概览](#架构概览)
- [环境变量配置](#环境变量配置)
- [快速开始](#快速开始)
- [核心组件](#核心组件)
- [使用示例](#使用示例)

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **双路 API 检索** | 向量检索（Embedding + Cosine）+ BM25 全文检索，均通过外部向量库 API 完成 |
| **混合去重** | 自动合并向量与 BM25 结果，按 `chunk_id` 去重并保留双路分数 |
| **查询扩展** | 基于 LLM 生成语义等价查询变体，同时支持自动中译英扩展 |
| **重排序** | 支持本地 `CrossEncoder` 或外部 API 重排序器（如 bge-reranker） |
| **上下文扩展** | 重排序时自动拼接同文件前后相邻 chunk，提升排序准确性 |
| **自适应 TopK** | 根据查询长度、复杂度、技术关键词等动态调整返回数量 |
| **多 Embedding 源** | 支持本地 HuggingFace 模型或外部 OpenAI 兼容 Embedding API |

---

## 架构概览

```
用户查询
    │
    ▼
┌─────────────────┐
│   查询扩展       │  ──▶  LLM 生成变体 + 自动英译
└─────────────────┘
    │
    ▼
┌─────────────────┐     ┌─────────────────┐
│   向量检索 API   │     │   BM25 检索 API  │
│  /chunks/vector-search│  /chunks/text-search│
└─────────────────┘     └─────────────────┘
    │                           │
    └───────────┬───────────────┘
                ▼
        ┌───────────────┐
        │   混合去重     │  ──▶  按 chunk_id 合并，保留 score / bm25_score
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │   重排序       │  ──▶  CrossEncoder / API Reranker + 上下文扩展
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │  自适应 TopK   │  ──▶  动态截断返回最终文档列表
        └───────────────┘
```

---

## 环境变量配置

在 `src/backend/retrieval/.env` 或系统环境中配置以下变量：

### 1. 向量库 API 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_API_URL` | `https://equivalent-handling-heritage-hat.trycloudflare.com/` | 向量库服务地址 |
| `VECTOR_API_KEY` | `None` | 向量库 API 密钥（可选） |

### 2. 模型配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_MODEL` | `BAAI/bge-m3` | 本地向量嵌入模型 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 本地重排序模型 |
| `EMBEDDING_DIMENSION_RETRIEVAL` | `1024` | Embedding 输出维度 |

### 3. 检索阈值

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_SCORE_THRESHOLD` | `0.55` | 向量检索最低 cosine score，低于此值过滤 |
| `BM25_SCORE_THRESHOLD` | `-999.0` | BM25 检索最低 score（默认不过滤） |
| `RETRIEVAL_SCORE_THRESHOLD` | - | **已废弃**，兼容旧配置，仅作用于向量检索 |

### 4. 查询扩展配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QUERY_EXPANSION_ENABLED` | `false` | 是否启用查询扩展 |
| `QUERY_EXPANSION_MODEL` | `aliyun/deepseek-v3.2` | 查询扩展所用 LLM |
| `QUERY_EXPANSION_NUM` | `3` | 扩展变体数量（最大 5） |
| `OPENAI_API_KEY` | `sk-` | 查询扩展 API Key |
| `OPENAI_API_BASE` | `` | 查询扩展 API 基础地址，默认 `https://aigw.asiainfo.com/v1` |

### 5. 重排序配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANK_TOP_N` | `5` | 重排序后返回的文档数量 |
| `RERANK_CONTEXT_WINDOW` | `1` | 重排序上下文扩展窗口（前后各取 N 个相邻 chunk） |
| `RERANK_API_URL` | `` | 外部重排序 API 地址，置空则回退本地 CrossEncoder |
| `RERANK_API_KEY` | `sk-` | 外部重排序 API 密钥 |
| `RERANK_API_MODEL` | `10086/bge-reranker-v2-m3` | 外部重排序模型名 |

### 6. 外部 Embedding API 配置（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_API_URL` | `` | 外部 Embedding API 地址，置空则回退本地模型 |
| `EMBEDDING_API_KEY` | `sk-` | 外部 Embedding API 密钥 |
| `EMBEDDING_API_MODEL` | `10086/bge-m3` | 外部 Embedding 模型名 |

### 7. 超时与自适应边界

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SEARCH_TIMEOUT` | `30` | 向量/BM25 检索 API 超时（秒） |
| `HEALTH_TIMEOUT` | `5` | 健康检查 API 超时（秒） |
| `ADAPTIVE_TOPK_MIN` | `5` | 自适应 TopK 最小返回数量 |
| `ADAPTIVE_TOPK_MAX` | `25` | 自适应 TopK 最大返回数量 |

---

## 快速开始

### 安装依赖

```bash
pip install numpy requests python-dotenv langchain-core sentence-transformers translators langchain-huggingface
```

### 最小启动示例

```python
from src.backend.retrieval.retrieval import pipeline, init_retrieval_system

# 方式1：直接使用检索管道
results = pipeline("如何提高混合检索召回率", top_k=20)
for doc in results:
    print(doc.page_content[:200])

# 方式2：初始化后复用组件
system = init_retrieval_system()
client = system['client']
docs = client.search("Kubernetes 调度策略", top_k=10)
```

---

## 核心组件

### 1. VectorAPIClient

向量库 API 客户端，封装了与向量库服务的通信：

- `search(query, top_k, filters)` — 向量检索（本地计算 embedding → 调用 `/chunks/vector-search`）
- `text_search(query, top_k, filters)` — BM25 全文检索（调用 `/chunks/text-search`）
- `search_with_score(query, top_k, filters)` — 向量检索并返回 `(Document, score)` 元组
- `health_check()` — 检查向量库服务可用性

### 2. 重排序器

支持两种模式，优先使用外部 API：

- **APIReranker**：调用外部 Rerank API，支持上下文扩展
- **Reranker**：本地 `CrossEncoder` 模型，通过 Sigmoid 将 logits 映射到 `(0, 1)`

### 3. 查询扩展 (expand_query)

基于配置的 LLM 生成语义等价查询变体，异常时自动降级为原查询。Pipeline 中还会额外尝试将中文查询翻译为英文进行扩展。

### 4. 自适应 TopK (adaptive_topk_simple)

根据查询特征动态调整返回数量：

- 查询长度 > 30：+5
- 空格数 > 8（复杂查询）：+5
- 包含数字（版本号/代码）：+3
- 疑问/比较类关键词（如何、为什么、对比、区别）：+2
- 技术关键词（算法、实现、架构、原理、优化）：+3

最终限制在 `[ADAPTIVE_TOPK_MIN, ADAPTIVE_TOPK_MAX]` 范围内。

### 5. 检索管道 (pipeline)

完整检索流程入口：

```python
def pipeline(
    query: str,
    top_k: int = 10,
    use_bm25: bool = True,
    use_rerank: bool = True,
    use_query_expansion: bool = False
) -> List[Document]
```

参数说明：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `str` | - | 查询字符串 |
| `top_k` | `int` | `10` | 每路检索返回数量 |
| `use_bm25` | `bool` | `True` | 是否启用 BM25 API 检索 |
| `use_rerank` | `bool` | `True` | 是否启用重排序 |
| `use_query_expansion` | `bool` | `False` | 是否启用查询扩展 |

---

## 使用示例

### 仅向量检索（不走 BM25）

```python
results = pipeline("React Hooks 原理", top_k=15, use_bm25=False)
```

### 启用查询扩展

```python
results = pipeline(
    "Spring AOP 实现机制",
    top_k=20,
    use_query_expansion=True
)
```

### 使用底层 API 客户端

```python
from src.backend.retrieval.retrieval import get_api_client

client = get_api_client()

# 向量检索
vec_docs = client.search("Docker 容器网络", top_k=10)

# BM25 检索
bm25_docs = client.text_search("Docker 容器网络", top_k=10)

# 带过滤器的检索
filtered_docs = client.search(
    "Kubernetes",
    top_k=10,
    filters={"file_path": {"$contains": "调度"}}
)
```

---

## 注意事项

1. **向量库服务依赖**：本模块不再直接连接本地向量数据库，所有检索均通过 `VECTOR_API_URL` 指定的 API 服务完成，请确保服务可达。
2. **Embedding 源切换**：若配置了 `EMBEDDING_API_URL`，则优先使用外部 API 计算 embedding；否则自动回退到本地 `HuggingFaceEmbeddings`。
3. **重排序器切换**：若配置了 `RERANK_API_URL`，则优先使用外部 API 重排序；否则回退到本地 `CrossEncoder`。
4. **查询扩展降级**：未配置 `OPENAI_API_KEY` 或 LLM 调用失败时，查询扩展自动降级为原查询，不影响主流程。
5. **英文翻译降级**：中英文扩展失败时静默忽略，不影响主检索流程。
