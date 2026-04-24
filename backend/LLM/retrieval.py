import sqlite3
import os
from typing import List
import pickle
import numpy as np
import requests
import json

"""
用户查询："如何提高混合检索召回率"
    ↓
【步骤1】查询扩展
    → 生成3个相关查询变体
    ↓
【步骤2】多路检索
    → 向量检索：找到语义相似的文档
    → BM25检索：找到关键词匹配的文档
    → 混合检索：合并两者结果
    ↓
【步骤3】自适应TopK
    → 查询长度=12字符，返回8个候选
    ↓
【步骤4】重排序
    → CrossEncoder对8个文档精细打分
    → 返回最相关的3个文档
    ↓
【输出】排好序的最相关文档片段
"""
from langchain_community.vectorstores import SQLiteVec

# 使用新的 langchain-huggingface 包（推荐）
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    # 如果未安装新包，回退到旧版本（会显示警告）
    from langchain_community.embeddings import HuggingFaceEmbeddings
# BM25Retriever - 从 langchain_community 导入
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
# FakeListLLM - 从 langchain_community 导入
from langchain_community.llms import FakeListLLM

# 尝试导入 EnsembleRetriever 和 MultiQueryRetriever
# 在新版 LangChain (1.x) 中，统一从 langchain_community 导入
try:
    from langchain_community.retrievers import EnsembleRetriever
except ImportError:
    EnsembleRetriever = None

try:
    from langchain_community.retrievers.multi_query import MultiQueryRetriever
except ImportError:
    try:
        # 某些版本可能在根目录
        from langchain_community.retrievers import MultiQueryRetriever
    except ImportError:
        MultiQueryRetriever = None

from sentence_transformers import CrossEncoder

# ==================== 配置 ====================
# 获取脚本所在目录，确保路径正确
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "your_vector_db.sqlite")
TABLE_NAME = "your_table_name"
CHUNKS_PKL_PATH = os.path.join(BASE_DIR, "doc_chunks.pkl")

# 向量库 API 配置（新增）
VECTOR_API_URL = os.getenv("VECTOR_API_URL", "http://localhost:8001")
VECTOR_API_KEY = os.getenv("VECTOR_API_KEY", None)

# 模型配置
VECTOR_MODEL = "BAAI/bge-m3"  # 向量嵌入模型：支持100+语言的多语言嵌入模型
RERANKER_MODEL = "BAAI/bge-reranker-base"  # 重排序模型

# ==================== 初始化嵌入模型（全局只加载一次） ====================
embedding_model = HuggingFaceEmbeddings(
    model_name=VECTOR_MODEL,
    model_kwargs={'device': 'cpu'},  # 可根据需要改为 'cuda' 使用GPU
    encode_kwargs={'normalize_embeddings': True}  # BGE模型需要归一化
)

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

    def search(self, query: str, top_k: int = 20, use_hybrid: bool = True) -> List[Document]:
        """通过 API 调用向量检索"""
        try:
            response = self.session.post(
                f"{self.api_url}/api/search",
                json={
                    "query": query,
                    "top_k": top_k,
                    "use_hybrid": use_hybrid,
                    "return_scores": True
                },
                timeout=30
            )
            response.raise_for_status()
            result = response.json()

            # 转换为 Document 对象
            documents = []
            for item in result.get("results", []):
                doc = Document(
                    page_content=item.get("text", ""),
                    metadata={
                        "id": item.get("id", ""),
                        "score": item.get("score", 0.0),
                        **item.get("metadata", {})
                    }
                )
                documents.append(doc)

            return documents

        except requests.exceptions.RequestException as e:
            print(f"API 调用失败: {e}")
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
            return self.client.search(query, top_k=k, use_hybrid=False)

        def similarity_search_with_score(self, query: str, k: int = 20):
            """带分数的向量检索"""
            try:
                response = self.client.session.post(
                    f"{self.client.api_url}/api/search",
                    json={
                        "query": query,
                        "top_k": k,
                        "use_hybrid": False,
                        "return_scores": True
                    },
                    timeout=30
                )
                response.raise_for_status()
                result = response.json()

                docs_with_scores = []
                for item in result.get("results", []):
                    doc = Document(
                        page_content=item.get("text", ""),
                        metadata={
                            "id": item.get("id", ""),
                            **item.get("metadata", {})
                        }
                    )
                    docs_with_scores.append((doc, item.get("score", 0.0)))

                return docs_with_scores

            except Exception as e:
                print(f"API 调用失败: {e}")
                return []

    return VectorStoreAPIWrapper(api_client)


# ==================== 加载文档（保持不变）====================
def load_documents():
    """加载文档块"""
    if not os.path.exists(CHUNKS_PKL_PATH):
        raise FileNotFoundError(f"文档文件不存在: {CHUNKS_PKL_PATH}")

    with open(CHUNKS_PKL_PATH, "rb") as f:
        return pickle.load(f)


# ==================== 向量检索包装（保持不变）====================
class SQLiteVecRetriever(BaseRetriever):
    def __init__(self, vectorstore, k=20):
        self.vectorstore = vectorstore
        self.k = k

    def _get_relevant_documents(self, query: str) -> List[Document]:
        return self.vectorstore.similarity_search(query, k=self.k)

    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        return await self.vectorstore.asimilarity_search(query, k=self.k)


# ==================== BM25（保持不变）====================
def create_bm25_retriever(documents):
    """创建 BM25 检索器"""
    bm25_retriever = BM25Retriever.from_documents(documents)
    bm25_retriever.k = 20
    return bm25_retriever


# ==================== 混合检索（保持不变）====================
def create_ensemble_retriever(vector_retriever, bm25_retriever):
    """创建混合检索器"""
    if EnsembleRetriever:
        return EnsembleRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            weights=[0.5, 0.5],
        )
    else:
        # 手动实现简单的混合检索
        return SimpleEnsembleRetriever(vector_retriever, bm25_retriever, k=20)


class SimpleEnsembleRetriever(BaseRetriever):
    """简单的混合检索器实现"""

    def __init__(self, vector_ret, bm25_ret, k=20):
        self.vector_ret = vector_ret
        self.bm25_ret = bm25_ret
        self.k = k

    def _get_relevant_documents(self, query: str) -> List[Document]:
        vec_docs = self.vector_ret._get_relevant_documents(query)
        bm25_docs = self.bm25_ret._get_relevant_documents(query)
        # 简单合并并去重
        all_docs = {}
        for doc in vec_docs + bm25_docs:
            key = doc.page_content[:100]
            if key not in all_docs:
                all_docs[key] = doc
        return list(all_docs.values())[:self.k]

    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        return self._get_relevant_documents(query)


# ==================== Query Expansion（保持不变）====================
def build_multi_query_retriever(base_retriever):
    """构建多查询检索器"""
    if MultiQueryRetriever:
        fake_llm = FakeListLLM(
            responses=[
                "混合检索 提升召回\n双路召回 方法\nBM25 向量融合 技术"
            ]
        )
        return MultiQueryRetriever.from_llm(
            retriever=base_retriever,
            llm=fake_llm
        )
    else:
        print("⚠️ MultiQueryRetriever 不可用，使用基础检索器")
        return base_retriever


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


# ==================== Pipeline（保持不变）====================
def pipeline(query: str, vectorstore=None, all_documents=None, ensemble_retriever=None):
    """
    检索管道

    Args:
        query: 查询字符串
        vectorstore: 向量数据库（可选，首次调用时自动加载）
        all_documents: 文档列表（可选，首次调用时自动加载）
        ensemble_retriever: 混合检索器（可选，首次调用时自动创建）
    """
    print("原始查询:", query)

    # 延迟加载资源
    if vectorstore is None:
        vectorstore = load_vectorstore()
    if all_documents is None:
        all_documents = load_documents()
    if ensemble_retriever is None:
        vector_retriever = SQLiteVecRetriever(vectorstore, k=20)
        bm25_retriever = create_bm25_retriever(all_documents)
        ensemble_retriever = create_ensemble_retriever(vector_retriever, bm25_retriever)

    multi = build_multi_query_retriever(ensemble_retriever)

    docs = multi.invoke(query)
    print("召回数量:", len(docs))

    # 获取得分（如果能从检索器中获取）
    scores = None  # 实际情况可能无法获取
    if hasattr(multi, 'similarity_search_with_score'):
        docs_with_scores = multi.similarity_search_with_score(query)
        docs = [d for d, _ in docs_with_scores]
        scores = [s for _, s in docs_with_scores]

    # 自适应 TopK
    k = adaptive_topk_simple(query, docs)  # 使用简化版

    # k = adaptive_topk(query)
    docs = docs[:k]

    # 使用单例模式获取重排序器
    reranker = get_reranker()
    final_docs = reranker.rerank(query, docs)

    return final_docs


# ==================== 初始化函数（保持不变）====================
def init_retrieval_system():
    """初始化检索系统，返回可复用的组件"""
    print("正在初始化检索系统...")

    # 加载资源
    vectorstore = load_vectorstore()
    all_documents = load_documents()

    # 创建检索器
    vector_retriever = SQLiteVecRetriever(vectorstore, k=20)
    bm25_retriever = create_bm25_retriever(all_documents)
    ensemble_retriever = create_ensemble_retriever(vector_retriever, bm25_retriever)

    print("检索系统初始化完成")
    return {
        'vectorstore': vectorstore,
        'documents': all_documents,
        'ensemble_retriever': ensemble_retriever
    }


# ==================== 测试 ====================
if __name__ == "__main__":
    # 方式1：一次性初始化（推荐用于多次查询）
    system = init_retrieval_system()
    # 使用初始化好的检索系统组件执行查询
    # 通过传递已加载的资源（向量数据库、文档、混合检索器），避免重复初始化，提升查询性能
    results = pipeline(
        "如何提高混合检索召回率",
        vectorstore=system['vectorstore'],
        all_documents=system['documents'],
        ensemble_retriever=system['ensemble_retriever']
    )

    # 方式2：直接调用（适合单次查询，会自动加载资源）
    # results = pipeline("如何提高混合检索召回率")

    for i, d in enumerate(results):
        print(f"{i + 1}. {d.page_content[:100]}")