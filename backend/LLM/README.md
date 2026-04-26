

以下是详细的使用说明文档：

```
# 混合检索系统使用文档

## 概述

本系统实现了一个完整的混合检索管道，支持**向量语义检索**、**BM25全文检索**、**查询扩展**、**自适应TopK**和**CrossEncoder重排序**。所有检索均通过 HTTP API 访问远程向量库，本地仅负责计算 embedding 和编排检索流程，无需维护本地文档索引。

## 系统架构
```

┌─────────────────────────────────────────────────────────────┐
│ 用户查询                                                    │
└─────────────────────────────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 查询扩展 (Query Expansion, 可选)                            │
│ LLM 生成多个语义相关查询变体                                 │
└─────────────────────────────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 双路 API 检索                                               │
├──────────────────────────┬──────────────────────────────────┤
│ 向量检索 /chunks/vector-search │ BM25检索 /chunks/text-search   │
│ 本地 bge-m3 计算 embedding    │ 直接传 query 字符串             │
│ 远程向量库 cosine similarity  │ 远程 SQLite FTS5 全文匹配        │
└──────────────────────────┴──────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 结果合并去重 (按 chunk_id)                                   │
└─────────────────────────────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 自适应 TopK 截断                                             │
│ 根据查询长度/复杂度/技术特征动态调整返回数量                    │
└─────────────────────────────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 重排序 (Reranker)                                            │
│ CrossEncoder 精细打分排序                                    │
└─────────────────────────────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ 最终结果                                                    │
└─────────────────────────────────────────────────────────────┘

```
## 功能特性

### 1. 向量检索 (Vector Search)
- 本地使用 `bge-m3` 计算 query embedding（1024 维，normalized）
- 通过 HTTP API 调用远程向量库 `/chunks/vector-search`
- 返回带 cosine similarity score 的语义搜索结果
- 支持 `filters` 过滤（按文件路径、时间戳等）

### 2. BM25 全文检索 (Text Search)
- 通过 HTTP API 调用远程向量库 `/chunks/text-search`
- 底层由远程 SQLite FTS5 实现关键词匹配
- 无需本地计算 embedding，直接传 query 字符串
- 返回带 `bm25_rank` 的全文匹配结果

### 3. 双路混合检索 (Hybrid Retrieval)
- 同时调用向量检索和 BM25 检索 API
- 按 `chunk_id` 合并去重（同一文档片段只保留一次）
- 无需本地维护 BM25 索引或 doc_chunks.pkl

### 4. 查询扩展 (Query Expansion)
- 基于 LLM（OpenAI API）自动生成语义相关查询变体
- 对每个变体分别进行双路检索，扩大召回范围
- 未配置 LLM 时自动降级，仅使用原查询
- 通过环境变量 `QUERY_EXPANSION_ENABLED` 控制开关

### 5. Score 阈值过滤
- 通过 `RETRIEVAL_SCORE_THRESHOLD` 环境变量配置最低 score
- 低于阈值的检索结果会被自动过滤
- 默认 `0.0`（不过滤）

### 6. 自适应 TopK
- 根据查询长度、关键词数量、数字含量、疑问句模式等动态调整返回数量
- 针对技术文档场景优化（识别 "算法"/"架构"/"原理" 等关键词）
- 返回数量范围：5 ~ 25

### 7. CrossEncoder 重排序
- 使用 `bge-reranker-base` 对候选结果精细打分
- 支持惰性加载，首次使用时才初始化模型
- 可通过 `use_rerank=False` 禁用，提升速度

## 安装配置

### 1. 环境要求

\`\`\`bash
Python >= 3.8
内存 >= 8GB (推荐16GB)
磁盘空间 >= 10GB
```

### 2. 安装依赖

```bash
pip install langchain-community langchain-huggingface langchain-core
pip install sentence-transformers
pip install requests
pip install numpy
# openai 仅在启用查询扩展时需要
pip install openai
```

或使用 `requirements.txt`：

```
langchain-community>=0.2.0
langchain-huggingface>=0.1.0
langchain-core>=0.2.0
sentence-transformers>=2.2.0
requests>=2.31.0
numpy>=1.24.0
openai>=1.0.0
```

### 3. 环境变量配置

创建 `.env` 文件：

```bash
# ==================== 向量库 API 配置 ====================
VECTOR_API_URL=http://localhost:18082
VECTOR_API_KEY=your-api-key-here      # 可选

# ==================== 模型配置 ====================
# 向量嵌入模型（首次使用会自动下载，约 2GB）
# VECTOR_MODEL=BAAI/bge-m3
# 重排序模型（首次使用会自动下载，约 1GB）
# RERANKER_MODEL=BAAI/bge-reranker-base

# ==================== Score 阈值过滤 ====================
# 低于此值的检索结果会被过滤，0.0 表示不过滤
RETRIEVAL_SCORE_THRESHOLD=0.0

# ==================== 查询扩展配置（可选）====================
# 全局默认开关
QUERY_EXPANSION_ENABLED=false
QUERY_EXPANSION_MODEL=gpt-3.5-turbo
QUERY_EXPANSION_NUM=3

# LLM API 配置（查询扩展必需）
OPENAI_API_KEY=sk-xxx
# OPENAI_API_BASE=https://api.openai.com/v1   # 可选，用于代理
```

或在命令行设置：

```bash
export VECTOR_API_URL=http://localhost:18082
export RETRIEVAL_SCORE_THRESHOLD=0.5
export QUERY_EXPANSION_ENABLED=true
export OPENAI_API_KEY=sk-xxx
```

## 使用方法

### 基础使用

```python
from retrieval import pipeline, init_retrieval_system

# 单次查询（自动初始化 API 客户端和模型）
results = pipeline("如何提高混合检索召回率")

# 输出结果
for i, doc in enumerate(results):
    print(f"{i+1}. {doc.page_content[:200]}")
    print(f"   元数据: {doc.metadata}")
```

### 高级用法

#### 1. 直接使用 API 客户端

```python
from retrieval import VectorAPIClient, get_api_client

# 方式 A：使用全局单例客户端
client = get_api_client()

# 方式 B：创建独立客户端
client = VectorAPIClient(api_url="http://localhost:18082")

# 向量检索（本地计算 embedding → 远程向量库）
vec_docs = client.search("查询内容", top_k=20)

# BM25 全文检索（直接传 query 字符串）
bm25_docs = client.text_search("查询内容", top_k=20)

# 带分数返回
vec_docs_with_score = client.search_with_score("查询内容", top_k=20)
# 返回 [(Document, score), ...]

# 健康检查
if client.health_check():
    print("向量库服务正常")
```

#### 2. 启用查询扩展

```python
from retrieval import pipeline

# 方式 A：单次调用启用
results = pipeline(
    "如何提高混合检索召回率",
    use_query_expansion=True
)

# 方式 B：通过环境变量全局启用
# export QUERY_EXPANSION_ENABLED=true
# export OPENAI_API_KEY=sk-xxx
results = pipeline("如何提高混合检索召回率")
```

#### 3. 自定义检索开关

```python
from retrieval import pipeline

# 只使用向量检索（禁用 BM25 和重排序，速度最快）
results = pipeline("查询", use_bm25=False, use_rerank=False)

# 启用 BM25 但禁用重排序
results = pipeline("查询", use_bm25=True, use_rerank=False)

# 启用查询扩展 + 双路检索 + 重排序（召回率最高，成本最高）
results = pipeline("查询", use_query_expansion=True, use_bm25=True, use_rerank=True)
```

#### 4. 使用自适应 TopK

```python
from retrieval import adaptive_topk_simple

# 手动查看自适应策略推荐的 K 值
k = adaptive_topk_simple("长查询内容，包含多个关键词和版本号 v2.0")
print(f"推荐返回数量: {k}")

# pipeline 内部会自动调用 adaptive_topk_simple，无需手动处理
```

#### 5. 只使用重排序

```python
from retrieval import get_reranker

# 获取重排序器（惰性加载，首次调用时才初始化）
reranker = get_reranker()

# 对已有结果重排序
docs = [...]  # 已有的 Document 列表
reranked_docs = reranker.rerank("查询内容", docs)
```

### 批量查询示例

```python
from retrieval import pipeline

queries = [
    "向量检索原理",
    "BM25 算法实现",
    "混合检索优化方法"
]

for query in queries:
    results = pipeline(query)
    print(f"\n查询: {query}")
    for i, doc in enumerate(results[:3]):
        print(f"  {i+1}. {doc.page_content[:100]}...")
```

## 配置说明

### 模型配置

```python
# 向量模型配置（代码中修改 retrieval.py）
VECTOR_MODEL = "BAAI/bge-m3"  # 多语言向量模型，1024 维
# 其他可选模型：
# - "BAAI/bge-large-zh"  # 中文专用
# - "sentence-transformers/all-MiniLM-L6-v2"  # 轻量级
# - "intfloat/e5-large-v2"  # 英文优化

# 重排序模型配置
RERANKER_MODEL = "BAAI/bge-reranker-base"
# 其他可选：
# - "BAAI/bge-reranker-large"  # 更精确但更慢
# - "cross-encoder/ms-marco-MiniLM-L-6-v2"  # 轻量级
```

### 运行时可调参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `top_k` | int | 20 | 每路检索返回数量 |
| `use_bm25` | bool | True | 是否启用 BM25 API 检索 |
| `use_rerank` | bool | True | 是否启用 CrossEncoder 重排序 |
| `use_query_expansion` | bool | False | 是否启用查询扩展 |

```python
# 在代码中调用时传入
results = pipeline("查询", top_k=15, use_bm25=True, use_rerank=False)
```

## API 接口说明

系统需要远程向量库提供以下 API 接口：

#### 1. 健康检查

```
GET /health
Response: {"status": "ok"}
```

#### 2. 向量检索

```
POST /chunks/vector-search
Request Body:
{
    "embedding": [0.1, 0.2, ..., 0.1024],  // bge-m3, 1024 维, normalized
    "top_k": 20,
    "filters": {
        "file_paths": ["api/auth.md"],
        "min_timestamp": "2026-01-01T00:00:00Z"
    }
}

Response:
{
    "results": [
        {
            "chunk_id": "81e76ae6...",
            "content": "文档内容...",
            "score": 0.85,
            "metadata": {
                "file_path": "api/auth.md",
                "anchor_id": "api/auth.md#38",
                "title_path": "Sample Document > Authentication",
                "char_offset_start": 38,
                "char_offset_end": 153,
                "is_truncated": false,
                "content_type": "document",
                "language": "en",
                "last_modified": "2026-04-20T10:30:00Z"
            }
        }
    ],
    "total": 1
}
```

#### 3. BM25 全文检索

```
POST /chunks/text-search
Request Body:
{
    "query": "查询文本",
    "top_k": 20,
    "filters": {
        "file_paths": ["api/auth.md"]
    }
}

Response:
{
    "results": [
        {
            "chunk_id": "81e76ae6...",
            "content": "文档内容...",
            "score": 0.72,
            "bm25_rank": -0.467,
            "metadata": {...}
        }
    ],
    "total": 1
}
```

## 性能优化建议

### 1. 模型惰性加载

embedding 模型和重排序模型均为**惰性加载**，首次调用时才初始化，避免 `import retrieval` 时阻塞：

```python
from retrieval import get_embedding_model, get_reranker

# 首次调用会加载模型（约需 2-3 秒）
emb = get_embedding_model()
reranker = get_reranker()
```

### 2. 速度优化

```python
from retrieval import pipeline

# 禁用 BM25 和重排序（仅向量检索，速度最快）
results = pipeline("查询", use_bm25=False, use_rerank=False)

# 减少 TopK 值
results = pipeline("查询", top_k=10)

# 禁用查询扩展（避免 LLM 调用和额外 API 请求）
results = pipeline("查询", use_query_expansion=False)
```

### 3. 缓存机制

```python
from functools import lru_cache
from retrieval import pipeline

@lru_cache(maxsize=100)
def cached_search(query: str):
    return pipeline(query)
```

## 错误处理

### 常见错误及解决方案

#### 1. 向量库 API 连接失败

```
# 错误信息
ConnectionError: 向量库 API 服务不可用: http://localhost:18082
# 或
⚠️ 警告: 向量库 API 服务不可用: http://localhost:18082

# 解决方案
# 1. 检查向量库服务是否启动
# 2. 检查 VECTOR_API_URL 配置是否正确
# 3. 检查网络连接
```

#### 2. Embedding 维度异常

```
# 错误信息
Embedding 维度异常: 768, 期望 1024

# 原因：使用了非 bge-m3 的模型，输出维度不是 1024
# 解决方案：修改 VECTOR_MODEL 为 "BAAI/bge-m3" 或确保向量库支持当前维度
```

#### 3. 模型加载失败

```
# 错误信息
OSError: model not found

# 解决方案
# 1. 检查网络连接（首次使用需下载模型，约 2GB）
# 2. 设置 HF_ENDPOINT=https://hf-mirror.com 使用国内镜像
# 3. 手动下载模型到本地，指定本地路径
```

#### 4. 查询扩展 LLM 调用失败

```
# 错误信息
查询扩展失败，使用原查询: ...

# 原因：未配置 OPENAI_API_KEY 或 LLM 服务不可用
# 解决方案：
# 1. 设置 OPENAI_API_KEY 环境变量
# 2. 检查 OPENAI_API_BASE 是否正确（如使用代理）
# 3. 该错误会自动降级为原查询，不影响主流程
```

## 测试示例

### 运行模拟测试

项目已包含完整的 Mock HTTP 测试脚本，无需启动真实向量库即可验证检索逻辑：

```bash
cd /Users/lenghaijun/PycharmProjects/TechnicalDocumentationCitationSystem/backend/LLM
python3 test_retrieval_mock.py
```

测试覆盖场景：
- API 健康检查
- 正常向量检索（embedding 计算 + API 调用 + 响应解析）
- BM25 全文检索
- 带分数检索
- 空结果场景
- Embedding 维度错误（服务端 400）
- 网络异常（连接不存在的服务）
- filters 参数透传
- Score 阈值过滤
- Pipeline 混合检索（向量 + BM25 合并去重）
- 查询扩展降级（无 LLM 配置）
- Pipeline 查询扩展多路检索

### 快速测试脚本

```python
from retrieval import pipeline, get_api_client

def test_health_check():
    """测试 API 健康检查"""
    client = get_api_client()
    if client.health_check():
        print("✓ API 服务正常")
    else:
        print("✗ API 服务异常")

def test_single_query():
    """测试单次查询"""
    results = pipeline("向量检索原理")
    print(f"返回结果数: {len(results)}")
    for i, doc in enumerate(results):
        print(f"{i+1}. {doc.page_content[:100]}...")

def test_query_expansion():
    """测试查询扩展"""
    results = pipeline("如何提高混合检索召回率", use_query_expansion=True)
    print(f"查询扩展后返回结果数: {len(results)}")

if __name__ == "__main__":
    test_health_check()
    test_single_query()
    test_query_expansion()
```

## 注意事项

1. **首次运行会下载模型**：初次使用 `bge-m3` 和 `bge-reranker-base` 时会自动从 HuggingFace 下载，共需约 3GB 磁盘空间和网络连接
2. **API 依赖**：系统完全依赖远程向量库 API（默认 `http://localhost:18082`），确保向量库服务正常运行
3. **内存使用**：重排序模型约占用 2-3GB 内存，向量模型约 1-2GB，可通过 `use_rerank=False` 减少内存占用
4. **查询扩展成本**：启用查询扩展后，每个变体会增加 2 次 API 调用（向量 + BM25）和 1 次 LLM 调用，请根据实际场景权衡召回率与成本
5. **惰性加载**：`import retrieval` 时不会加载任何模型，首次调用 `get_embedding_model()` 或 `pipeline()` 时才初始化
6. **无需本地数据文件**：系统不再依赖 `doc_chunks.pkl`、本地 SQLite 或 BM25 索引，所有检索均走 API

## 故障排查

### 1. 启用调试模式

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 检查 API 响应

```python
from retrieval import get_api_client

client = get_api_client()
response = client.session.post(
    f"{client.api_url}/chunks/vector-search",
    json={"embedding": [0.01] * 1024, "top_k": 5}
)
print(response.status_code)
print(response.text)
```

### 3. 验证 embedding 计算

```python
from retrieval import get_embedding_model

emb = get_embedding_model()
vec = emb.embed_query("测试")
print(f"维度: {len(vec)}")  # 应为 1024
print(f"前5个值: {vec[:5]}")
```

## 版本历史

- **v2.0.0** (2026-04-25): 架构重构为纯 API 双路检索模式
  - 向量检索改为调用 `/chunks/vector-search` API
  - BM25 检索改为调用 `/chunks/text-search` API
  - 移除本地 `doc_chunks.pkl`、SQLite、BM25 索引依赖
  - `embedding_model` 和 `reranker` 改为惰性加载
  - 新增 Score 阈值过滤（`RETRIEVAL_SCORE_THRESHOLD`）
  - 新增查询扩展功能（基于 LLM）
  - 新增完整 Mock HTTP 测试脚本（27 项测试）
- v1.3.0: 添加批量查询支持
- v1.2.0: 优化自适应 TopK 策略
- v1.1.0: 添加 API 远程访问支持
- v1.0.0: 初始版本，支持基础检索功能


