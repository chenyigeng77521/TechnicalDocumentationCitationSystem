

以下是详细的使用说明文档：

```
# 混合检索系统使用文档

## 概述

本系统实现了一个完整的混合检索管道，支持向量检索、BM25关键词检索、混合检索、自适应TopK和重排序功能。系统通过HTTP API远程访问向量数据库，支持高效的语义搜索。

## 系统架构
```

┌─────────────────────────────────────────────────────────────┐  
│ 用户查询 │  
└─────────────────────────────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 查询扩展 (Query Expansion) │  
│ 生成多个相关查询变体 │  
└─────────────────────────────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 多路检索 │  
├─────────────────────┬───────────────────────────────────────┤  
│ 向量检索 (API) │ BM25检索 (本地) │  
│ 语义相似度搜索 │ 关键词匹配 │  
└─────────────────────┴───────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 混合检索 (Ensemble) │  
│ 加权融合两种结果 │  
└─────────────────────────────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 自适应 TopK │  
│ 根据查询特征动态调整返回数量 │  
└─────────────────────────────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 重排序 (Reranker) │  
│ CrossEncoder精细打分排序 │  
└─────────────────────────────────────────────────────────────┘  
↓  
┌─────────────────────────────────────────────────────────────┐  
│ 最终结果 │  
└─────────────────────────────────────────────────────────────┘

```
## 功能特性

### 1. 向量检索
- 通过HTTP API访问远程向量数据库
- 支持语义相似度搜索
- 返回带相似度分数的结果

### 2. BM25检索
- 本地关键词匹配检索
- 基于词频和文档频率的排序
- 适合精确关键词查询

### 3. 混合检索
- 加权融合向量检索和BM25检索结果
- 平衡语义匹配和关键词匹配
- 可配置权重（默认各50%）

### 4. 查询扩展
- 自动生成查询变体
- 提高召回率
- 支持多角度检索

### 5. 自适应TopK
- 根据查询长度动态调整
- 根据查询复杂度调整
- 支持技术文档特殊处理

### 6. 重排序
- 使用CrossEncoder精细打分
- 提高结果准确性
- 支持自定义排序数量

## 安装配置

### 1. 环境要求

\`\`\`bash
Python >= 3.8
内存 >= 8GB (推荐16GB)
磁盘空间 >= 10GB
```

### 2\. 安装依赖

```
pip install langchain-community langchain-huggingface langchain-core
pip install sentence-transformers
pip install requests
pip install numpy
pip install sqlite-vec
```

或使用requirements.txt：

```
langchain-community>=0.2.0
langchain-huggingface>=0.1.0
langchain-core>=0.2.0
sentence-transformers>=2.2.0
requests>=2.31.0
numpy>=1.24.0
sqlite-vec>=0.1.0
```

### 3\. 环境变量配置

创建 `.env` 文件：

```
# 向量库API地址
VECTOR_API_URL=http://localhost:8001

# API密钥（可选）
VECTOR_API_KEY=your-api-key-here
```

或在命令行设置：

```
export VECTOR_API_URL=http://localhost:8001
export VECTOR_API_KEY=your-api-key-here
```

## 使用方法

### 基础使用

```
from query_engine import pipeline, init_retrieval_system

# 方式1：单次查询（自动加载资源）
results = pipeline("如何提高混合检索召回率")

# 方式2：多次查询（预加载资源，性能更好）
system = init_retrieval_system()
results = pipeline(
    "如何提高混合检索召回率",
    vectorstore=system['vectorstore'],
    all_documents=system['documents'],
    ensemble_retriever=system['ensemble_retriever']
)

# 输出结果
for i, doc in enumerate(results):
    print(f"{i+1}. {doc.page_content[:200]}")
    print(f"   元数据: {doc.metadata}")
```

### 高级用法

#### 1\. 直接使用检索器

```
from query_engine import load_vectorstore, load_documents
from query_engine import SQLiteVecRetriever, create_bm25_retriever

# 加载资源
vectorstore = load_vectorstore()
documents = load_documents()

# 创建检索器
vector_retriever = SQLiteVecRetriever(vectorstore, k=20)
bm25_retriever = create_bm25_retriever(documents)

# 单独使用向量检索
vec_results = vector_retriever.get_relevant_documents("查询内容")

# 单独使用BM25检索
bm25_results = bm25_retriever.get_relevant_documents("查询内容")
```

#### 2\. 自定义TopK

```
from query_engine import adaptive_topk_simple

# 手动指定返回数量
results = pipeline("查询内容")
results = results[:5]  # 只取前5个

# 使用自适应策略
k = adaptive_topk_simple("长查询内容，包含多个关键词，需要更多上下文")
```

#### 3\. 只使用重排序

```
from query_engine import Reranker

# 初始化重排序器
reranker = Reranker(top_n=5)

# 对已有结果重排序
docs = [...]  # 已有的文档列表
reranked_docs = reranker.rerank("查询内容", docs)
```

### 批量查询示例

```
from query_engine import init_retrieval_system

# 初始化系统
system = init_retrieval_system()

# 批量查询
queries = [
    "向量检索原理",
    "BM25算法实现", 
    "混合检索优化方法"
]

for query in queries:
    results = pipeline(
        query,
        vectorstore=system['vectorstore'],
        all_documents=system['documents'],
        ensemble_retriever=system['ensemble_retriever']
    )
    print(f"\n查询: {query}")
    for i, doc in enumerate(results[:3]):
        print(f"  {i+1}. {doc.page_content[:100]}...")
```

## 配置说明

### 模型配置

```
# 向量模型配置
VECTOR_MODEL = "BAAI/bge-m3"  # 多语言向量模型
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

### 可参考参数配置

```
# 在代码中修改
class Config:
    DEFAULT_TOP_K = 20          # 默认召回数量
    ENSEMBLE_WEIGHTS = [0.5, 0.5]  # 混合检索权重
    RERANK_TOP_N = 3            # 重排序返回数量
    
    # API配置
    API_TIMEOUT = 30            # API超时时间
    API_MAX_RETRIES = 3         # 最大重试次数
```

## API接口说明

### 向量库API接口要求

系统需要远程向量库提供以下API接口：

#### 1\. 健康检查

```
GET /health
Response: {"status": "ok"}
```

#### 2\. 向量检索

```
POST /api/search
Request Body:
{
    "query": "查询文本",
    "top_k": 10,
    "use_hybrid": true,
    "return_scores": true
}

Response:
{
    "results": [
        {
            "id": "doc_id",
            "text": "文档内容",
            "score": 0.95,
            "metadata": {...}
        }
    ]
}
```

## 性能优化建议

### 1\. 内存优化

```
# 使用CPU运行模型
embedding_model = HuggingFaceEmbeddings(
    model_kwargs={'device': 'cpu'}
)

# 限制文档大小
CHUNKS_PKL_PATH = "path/to/file"
MAX_DOCUMENTS = 10000
```

### 2\. 速度优化

```
# 预加载资源
system = init_retrieval_system()

# 减少TopK值
k = 10  # 而不是20

# 禁用查询扩展
# 在build_multi_query_retriever中返回base_retriever
```

### 3\. 缓存机制

```
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_search(query: str):
    return pipeline(query)
```

## 错误处理

### 常见错误及解决方案

#### 1\. 向量库API连接失败

```
# 错误信息
ConnectionError: 向量库 API 服务不可用: http://localhost:8001

# 解决方案
# 1. 检查向量库服务是否启动
# 2. 检查API地址配置是否正确
# 3. 检查网络连接
```

#### 3\. 模型加载失败

```
# 错误信息
OSError: model not found

# 解决方案
# 1. 检查网络连接
# 2. 手动下载模型到本地
# 3. 指定本地模型路径
```

## 测试示例

### 完整测试脚本

```
# test_retrieval.py
from query_engine import pipeline, init_retrieval_system, get_api_client

def test_health_check():
    """测试API健康检查"""
    client = get_api_client()
    if client.health_check():
        print("✓ API服务正常")
    else:
        print("✗ API服务异常")

def test_single_query():
    """测试单次查询"""
    results = pipeline("向量检索原理")
    print(f"返回结果数: {len(results)}")
    for i, doc in enumerate(results):
        print(f"{i+1}. {doc.page_content[:100]}...")

def test_performance():
    """测试性能"""
    import time
    
    queries = ["查询1", "查询2", "查询3"]
    system = init_retrieval_system()
    
    start = time.time()
    for query in queries:
        pipeline(query, **system)
    elapsed = time.time() - start
    
    print(f"批量查询耗时: {elapsed:.2f}秒")
    print(f"平均每次: {elapsed/len(queries):.2f}秒")

if __name__ == "__main__":
    test_health_check()
    test_single_query()
    test_performance()
```

## 注意事项

1. **首次运行会下载模型** ：初次使用时会自动下载BAAI/bge-m3和CrossEncoder模型，需要网络连接
2. **API依赖** ：系统依赖远程向量库API，确保服务正常运行
3. **内存使用** ：重排序模型大约占用2-3GB内存，向量模型占用1-2GB
4. **并发限制** ：API客户端不是线程安全的，多线程环境需要创建独立实例
5. **数据一致性** ：确保本地doc\_chunks.pkl与远程向量库数据一致

## 故障排查

### 1\. 启用调试模式

```
import logging

logging.basicConfig(level=logging.DEBUG)
```

### 2\. 检查API响应

```
from query_engine import get_api_client

client = get_api_client()
response = client.session.post(
    f"{client.api_url}/api/search",
    json={"query": "test", "top_k": 5}
)
print(response.status_code)
print(response.text)
```

### 3\. 验证数据文件

```
import pickle

with open("doc_chunks.pkl", "rb") as f:
    chunks = pickle.load(f)
    print(f"文档数量: {len(chunks)}")
    print(f"第一个文档: {chunks[0]}")
```

## 版本历史

- v1.0.0: 初始版本，支持基础检索功能
- v1.1.0: 添加API远程访问支持
- v1.2.0: 优化自适应TopK策略
- v1.3.0: 添加批量查询支持


