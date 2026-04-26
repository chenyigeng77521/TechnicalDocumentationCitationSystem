import os
from typing import List
import numpy as np
import requests

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

# ==================== 配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 向量库 API 配置
VECTOR_API_URL = os.getenv("VECTOR_API_URL", "http://localhost:18082")
VECTOR_API_KEY = os.getenv("VECTOR_API_KEY", None)

# 模型配置
VECTOR_MODEL = "BAAI/bge-m3"  # 向量嵌入模型
RERANKER_MODEL = "BAAI/bge-reranker-base"  # 重排序模型

# Score 阈值配置（低于此值的检索结果会被过滤，0.0 表示不过滤）
MAX_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.0"))

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
                timeout=30
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
                timeout=30
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
            response = self.session.get(f"{self.api_url}/health", timeout=5)
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
    return min(max(k, 5), 25)


# ==================== Reranker（保持不变）====================
class Reranker:
    def __init__(self, model_name=RERANKER_MODEL, top_n=3):
        print(f"正在加载重排序模型: {model_name}...")
        self.model = CrossEncoder(model_name)
        self.top_n = top_n
        print("重排序模型加载完成")

    def rerank(self, query: str, docs: List[Document]):
        if not docs:
            return []

        pairs = [[query, d.page_content] for d in docs]
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


# ==================== Pipeline（API 向量 + API BM25 + 重排序）====================
def pipeline(query: str, top_k: int = 20, use_bm25: bool = True, use_rerank: bool = True):
    """
    检索管道（双路 API 检索 + 重排序）

    Args:
        query: 查询字符串
        top_k: 每路检索返回数量
        use_bm25: 是否启用 BM25 API 检索
        use_rerank: 是否启用 CrossEncoder 重排序
    """
    print("原始查询:", query)

    client = get_api_client()

    # 1. 向量 API 检索
    vec_docs = client.search(query, top_k=top_k)
    print(f"向量召回: {len(vec_docs)}")

    docs = vec_docs

    # 2. BM25 API 检索（可选）
    if use_bm25:
        bm25_docs = client.text_search(query, top_k=top_k)
        print(f"BM25 召回: {len(bm25_docs)}")
        docs = _merge_results(vec_docs, bm25_docs)
        print(f"合并去重后: {len(docs)}")

    if not docs:
        return []

    # 3. 自适应 TopK 截断
    k = adaptive_topk_simple(query, docs)
    docs = docs[:k]

    # 4. CrossEncoder 重排序（可选）
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