import os
from typing import List
import numpy as np
import requests

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

# ==================== 配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# 环境变量说明（请在 .env 或系统环境中配置）
# ------------------------------------------------------------------
# VECTOR_API_URL           向量库 API 地址，默认 http://localhost:18082
# VECTOR_API_KEY           向量库 API 密钥（可选）
# RETRIEVAL_SCORE_THRESHOLD  检索结果最低 score，低于此值过滤，默认 0.0
# QUERY_EXPANSION_ENABLED  是否启用查询扩展，默认 false
# QUERY_EXPANSION_MODEL    查询扩展用 LLM 模型，默认 gpt-3.5-turbo
# QUERY_EXPANSION_NUM      扩展变体数量，默认 3
# OPENAI_API_KEY           查询扩展用 LLM API Key（启用查询扩展时必需）
# OPENAI_API_BASE          查询扩展用 LLM API 基础地址，默认 https://api.openai.com/v1
# RERANK_TOP_N             重排序后返回的文档数量，默认 3
# RERANK_CONTEXT_WINDOW    重排序上下文扩展窗口，前后各取 N 个相邻 chunk，默认 1
# SEARCH_TIMEOUT           向量/BM25 检索 API 超时时间（秒），默认 30
# HEALTH_TIMEOUT           健康检查 API 超时时间（秒），默认 5
# ADAPTIVE_TOPK_MIN        自适应 TopK 最小返回数量，默认 5
# ADAPTIVE_TOPK_MAX        自适应 TopK 最大返回数量，默认 25
# ------------------------------------------------------------------

# 向量库 API 配置
VECTOR_API_URL = os.getenv("VECTOR_API_URL", "http://localhost:18082")
VECTOR_API_KEY = os.getenv("VECTOR_API_KEY", None)

# 模型配置
VECTOR_MODEL = "BAAI/bge-m3"  # 向量嵌入模型
RERANKER_MODEL = "BAAI/bge-reranker-base"  # 重排序模型

# Score 阈值配置（低于此值的检索结果会被过滤，0.0 表示不过滤）
MAX_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.0"))

# 查询扩展配置
QUERY_EXPANSION_ENABLED = os.getenv("QUERY_EXPANSION_ENABLED", "false").lower() == "true"
QUERY_EXPANSION_MODEL = os.getenv("QUERY_EXPANSION_MODEL", "gpt-3.5-turbo")
QUERY_EXPANSION_NUM = int(os.getenv("QUERY_EXPANSION_NUM", "3"))

# LLM API 配置（查询扩展用）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# 重排序配置
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "3"))
RERANK_CONTEXT_WINDOW = int(os.getenv("RERANK_CONTEXT_WINDOW", "1"))

# API 超时配置（秒）
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))
HEALTH_TIMEOUT = int(os.getenv("HEALTH_TIMEOUT", "5"))

# 自适应 TopK 边界
ADAPTIVE_TOPK_MIN = int(os.getenv("ADAPTIVE_TOPK_MIN", "5"))
ADAPTIVE_TOPK_MAX = int(os.getenv("ADAPTIVE_TOPK_MAX", "25"))

# ==================== 惰性加载嵌入模型 ====================
_embedding_model = None


def get_embedding_model():
    """惰性加载 HuggingFaceEmbeddings（首次调用时才初始化）"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError:
            from langchain_community.embeddings import HuggingFaceEmbeddings
        _embedding_model = HuggingFaceEmbeddings(
            model_name=VECTOR_MODEL,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
    return _embedding_model

# ==================== 初始化重排序模型（全局只加载一次） ====================
reranker = None  # 延迟加载


def get_reranker():
    """获取重排序模型实例（单例模式）"""
    global reranker
    if reranker is None:
        reranker = Reranker()
    return reranker


# ==================== API 客户端（新增）====================
class VectorAPIClient:
    """向量库 API 客户端"""

    def __init__(self, api_url=VECTOR_API_URL, api_key=VECTOR_API_KEY):
        self.api_url = api_url
        self.api_key = api_key
        self.session = requests.Session()

        if self.api_key:
            self.session.headers.update({"X-API-Key": self.api_key})
        self.session.headers.update({"Content-Type": "application/json"})

    def search(self, query: str, top_k: int = 20, filters: dict = None) -> List[Document]:
        """通过 API 调用向量检索

        本地使用 bge-m3 计算 query embedding，调用向量库 /chunks/vector-search 接口。
        """
        # 1. 计算 embedding（bge-m3 + normalize）
        try:
            embedding = get_embedding_model().embed_query(query)
        except Exception as e:
            print(f"计算 embedding 失败: {e}")
            return []

        # 校验维度（bge-m3 应为 1024）
        if len(embedding) != 1024:
            print(f"Embedding 维度异常: {len(embedding)}, 期望 1024")
            return []

        # 2. 调用向量库 API
        try:
            response = self.session.post(
                f"{self.api_url}/chunks/vector-search",
                json={
                    "embedding": embedding,
                    "top_k": top_k,
                    "filters": filters
                },
                timeout=SEARCH_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()

            # 3. 解析响应（适配新字段名 chunk_id / content）
            documents = []
            for item in result.get("results", []):
                score = item.get("score", 0.0)
                # Score 阈值过滤
                if score < MAX_SCORE_THRESHOLD:
                    continue

                metadata = item.get("metadata", {})
                metadata["score"] = score
                metadata["chunk_id"] = item.get("chunk_id", "")

                doc = Document(
                    page_content=item.get("content", ""),
                    metadata=metadata
                )
                documents.append(doc)

            return documents

        except requests.exceptions.RequestException as e:
            print(f"API 调用失败: {e}")
            return []

    def search_with_score(self, query: str, top_k: int = 20, filters: dict = None):
        """向量检索并返回 (Document, score) 元组列表"""
        docs = self.search(query, top_k=top_k, filters=filters)
        return [(doc, doc.metadata.get("score", 0.0)) for doc in docs]

    def text_search(self, query: str, top_k: int = 20, filters: dict = None) -> List[Document]:
        """通过 API 调用 BM25 全文检索（SQLite FTS5）

        直接传字符串给 /chunks/text-search，不需要本地计算 embedding。
        """
        try:
            response = self.session.post(
                f"{self.api_url}/chunks/text-search",
                json={
                    "query": query,
                    "top_k": top_k,
                    "filters": filters
                },
                timeout=SEARCH_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()

            documents = []
            for item in result.get("results", []):
                score = item.get("score", 0.0)
                # Score 阈值过滤
                if score < MAX_SCORE_THRESHOLD:
                    continue

                metadata = item.get("metadata", {})
                metadata["score"] = score
                metadata["bm25_rank"] = item.get("bm25_rank", 0.0)
                metadata["chunk_id"] = item.get("chunk_id", "")

                doc = Document(
                    page_content=item.get("content", ""),
                    metadata=metadata
                )
                documents.append(doc)

            return documents

        except requests.exceptions.RequestException as e:
            print(f"BM25 API 调用失败: {e}")
            return []

    def health_check(self) -> bool:
        """健康检查"""
        try:
            response = self.session.get(f"{self.api_url}/health", timeout=HEALTH_TIMEOUT)
            return response.status_code == 200
        except:
            return False


# 全局 API 客户端
_api_client = None


def get_api_client():
    """获取 API 客户端实例"""
    global _api_client
    if _api_client is None:
        _api_client = VectorAPIClient()
        if not _api_client.health_check():
            print(f"⚠️ 警告: 向量库 API 服务不可用: {VECTOR_API_URL}")
    return _api_client


# ==================== 加载向量数据库（修改为 API 调用）====================
def load_vectorstore():
    """
    加载向量数据库
    修改为通过 API 访问，不再直接连接本地数据库
    """
    api_client = get_api_client()
    if not api_client.health_check():
        raise ConnectionError(f"向量库 API 服务不可用: {VECTOR_API_URL}")

    # 返回一个包装对象，保持与原接口兼容
    class VectorStoreAPIWrapper:
        def __init__(self, client):
            self.client = client

        def similarity_search(self, query: str, k: int = 20) -> List[Document]:
            """向量检索"""
            return self.client.search(query, top_k=k)

        def similarity_search_with_score(self, query: str, k: int = 20):
            """带分数的向量检索"""
            return self.client.search_with_score(query, top_k=k)

    return VectorStoreAPIWrapper(api_client)


# （本地 BM25、混合检索、Query Expansion 已移除，全部走 API）


# ==================== Adaptive TopK（保持不变）====================
def adaptive_topk(query: str):
    """自适应 TopK 策略"""
    if len(query) > 30:
        return 20
    if any(c.isdigit() for c in query):
        return 20
    return 8


def adaptive_topk_simple(query: str, initial_results: List = None) -> int:
    """简化版自适应策略 - 平衡性能和效果"""

    # 基础 K 值
    k = 10

    # 规则1：长查询需要更多上下文
    if len(query) > 30:
        k += 5

    # 规则2：复杂问题（包含多个关键词）
    if query.count(' ') > 8:
        k += 5

    # 规则3：包含数字（版本号、代码）
    if any(c.isdigit() for c in query):
        k += 3

    # 规则4：疑问句/比较类问题
    if any(word in query for word in ['如何', '为什么', '对比', '区别']):
        k += 2

    # 规则5：技术文档优化
    tech_patterns = ['算法', '实现', '架构', '原理', '优化']
    if any(pattern in query for pattern in tech_patterns):
        k += 3

    # 限制范围
    return min(max(k, ADAPTIVE_TOPK_MIN), ADAPTIVE_TOPK_MAX)


# ==================== 重排序上下文扩展 ====================
def _expand_rerank_context(docs: List[Document], window: int = RERANK_CONTEXT_WINDOW) -> List[str]:
    """
    为重排序构建扩展上下文。

    对每个 doc，在同文件的检索结果中查找前后相邻的 chunk，
    将它们的内容拼接作为重排序时的输入文本。

    返回与 docs 一一对应的扩展后文本列表。
    """
    if not docs or window <= 0:
        return [d.page_content for d in docs]

    # 按 file_path 分组并排序
    by_file: dict = {}
    for doc in docs:
        fp = doc.metadata.get("file_path", "")
        by_file.setdefault(fp, []).append(doc)

    for fp in by_file:
        by_file[fp].sort(key=lambda d: d.metadata.get("char_offset_start", 0))

    # 构建 (file_path, char_offset_start) -> 在排序后列表中的索引
    index_map = {}
    for fp, file_docs in by_file.items():
        for idx, d in enumerate(file_docs):
            key = (fp, d.metadata.get("char_offset_start", 0))
            index_map[key] = (fp, idx)

    expanded_texts = []
    for doc in docs:
        fp = doc.metadata.get("file_path", "")
        start = doc.metadata.get("char_offset_start", 0)
        key = (fp, start)

        if key not in index_map:
            expanded_texts.append(doc.page_content)
            continue

        _, idx = index_map[key]
        file_docs = by_file.get(fp, [])

        # 收集前后 window 个相邻 chunk
        parts = []
        for j in range(max(0, idx - window), min(len(file_docs), idx + window + 1)):
            parts.append(file_docs[j].page_content)

        expanded_texts.append("\n".join(parts))

    return expanded_texts


# ==================== Reranker（保持不变）====================
class Reranker:
    def __init__(self, model_name=RERANKER_MODEL, top_n=RERANK_TOP_N):
        print(f"正在加载重排序模型: {model_name}...")
        self.model = CrossEncoder(model_name)
        self.top_n = top_n
        print("重排序模型加载完成")

    def rerank(self, query: str, docs: List[Document]):
        if not docs:
            return []

        # 上下文扩展：用相邻 chunk 补全后打分
        expanded_texts = _expand_rerank_context(docs)
        if RERANK_CONTEXT_WINDOW > 0:
            print(f"重排序上下文扩展: window={RERANK_CONTEXT_WINDOW}")

        pairs = [[query, text] for text in expanded_texts]
        scores = self.model.predict(pairs)

        sorted_idx = np.argsort(scores)[::-1]
        return [docs[i] for i in sorted_idx[:self.top_n]]


def _merge_results(vec_docs: List[Document], bm25_docs: List[Document]) -> List[Document]:
    """合并向量检索和 BM25 检索结果，按 chunk_id 去重"""
    all_docs = {}
    for doc in vec_docs + bm25_docs:
        key = doc.metadata.get("chunk_id", doc.page_content[:100])
        if key not in all_docs:
            all_docs[key] = doc
    return list(all_docs.values())


# ==================== 查询扩展 ====================
def expand_query(query: str, num_variants: int = QUERY_EXPANSION_NUM) -> List[str]:
    """
    查询扩展：基于 LLM 生成语义相关的查询变体，提升检索召回率。

    如果未配置 OPENAI_API_KEY，则直接返回原查询（降级处理）。
    """
    if not OPENAI_API_KEY:
        return [query]

    try:
        import openai
        client = openai.OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE
        )

        system_prompt = (
            "你是一个查询扩展助手。请基于用户查询生成语义等价或相近的查询变体，"
            "用于提高文档检索召回率。只输出查询列表，每行一个，不要编号和解释。"
        )
        user_prompt = f"请为以下查询生成 {num_variants} 个查询变体：\n\n{query}"

        response = client.chat.completions.create(
            model=QUERY_EXPANSION_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )

        variants = [
            line.strip()
            for line in response.choices[0].message.content.split("\n")
            if line.strip()
        ]
        # 确保原查询在首位
        if query not in variants:
            variants.insert(0, query)
        return variants[:num_variants + 1]

    except Exception as e:
        print(f"查询扩展失败，使用原查询: {e}")
        return [query]


# ==================== Pipeline（API 向量 + API BM25 + 重排序）====================
def pipeline(query: str, top_k: int = 20, use_bm25: bool = True,
             use_rerank: bool = True, use_query_expansion: bool = False):
    """
    检索管道（双路 API 检索 + 查询扩展 + 重排序）

    Args:
        query: 查询字符串
        top_k: 每路检索返回数量
        use_bm25: 是否启用 BM25 API 检索
        use_rerank: 是否启用 CrossEncoder 重排序
        use_query_expansion: 是否启用查询扩展（会调用 LLM 生成查询变体）
    """
    print("原始查询:", query)

    client = get_api_client()

    # 查询扩展：生成多个语义相关查询变体
    should_expand = use_query_expansion or QUERY_EXPANSION_ENABLED
    queries = expand_query(query) if should_expand else [query]
    if len(queries) > 1:
        print(f"查询扩展: {len(queries)} 个变体 -> {queries}")

    all_vec_docs: List[Document] = []
    all_bm25_docs: List[Document] = []

    # 对每个查询变体分别检索
    for q in queries:
        vec_docs = client.search(q, top_k=top_k)
        all_vec_docs.extend(vec_docs)

        if use_bm25:
            bm25_docs = client.text_search(q, top_k=top_k)
            all_bm25_docs.extend(bm25_docs)

    print(f"向量召回（含扩展）: {len(all_vec_docs)}")

    # 合并去重（查询扩展时即使只有向量检索也需要去重）
    docs = _merge_results(all_vec_docs, all_bm25_docs if use_bm25 else [])
    if use_bm25:
        print(f"BM25 召回（含扩展）: {len(all_bm25_docs)}")
    print(f"合并去重后: {len(docs)}")

    if not docs:
        return []

    # 自适应 TopK 截断
    k = adaptive_topk_simple(query, docs)
    docs = docs[:k]

    # CrossEncoder 重排序（可选）
    if use_rerank:
        reranker = get_reranker()
        docs = reranker.rerank(query, docs)

    return docs


# ==================== 初始化函数 ====================
def init_retrieval_system():
    """初始化检索系统，返回可复用的组件"""
    print("正在初始化检索系统...")

    vectorstore = load_vectorstore()

    print("检索系统初始化完成")
    return {
        'vectorstore': vectorstore,
        'client': get_api_client(),
    }


# ==================== 测试 ====================
if __name__ == "__main__":
    # 直接调用检索管道（会自动初始化）
    results = pipeline("如何提高混合检索召回率", top_k=20)

    for i, d in enumerate(results):
        print(f"{i + 1}. {d.page_content[:100]}")