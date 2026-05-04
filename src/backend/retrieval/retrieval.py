import os
from typing import List
import numpy as np
import requests
from cffi.backend_ctypes import long
from dotenv import load_dotenv

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

# ==================== 配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# 环境变量说明（请在 retrieval/.env 或系统环境中配置）
# ------------------------------------------------------------------
# VECTOR_API_URL           向量库 API 地址，默认 https://equivalent-handling-heritage-hat.trycloudflare.com/
# VECTOR_API_KEY           向量库 API 密钥（可选）
# RETRIEVAL_SCORE_THRESHOLD  兼容旧配置：向量检索结果最低 score（已废弃，请用 VECTOR_SCORE_THRESHOLD）
# VECTOR_SCORE_THRESHOLD   向量检索结果最低 cosine score，低于此值过滤，默认 0.55
# BM25_SCORE_THRESHOLD     BM25 检索结果最低 score，低于此值过滤，默认 -999.0（不过滤）
# EMBEDDING_DIMENSION      Embedding 输出维度，默认 1024（bge-m3）
# QUERY_EXPANSION_ENABLED  是否启用查询扩展，默认 false
# QUERY_EXPANSION_MODEL    查询扩展用 retrieval 模型，默认 aliyun/deepseek-v3.2
# QUERY_EXPANSION_NUM      扩展变体数量，默认 3，最大 5
# OPENAI_API_KEY           查询扩展用 retrieval API Key（启用查询扩展时必需）
# OPENAI_API_BASE          查询扩展用 retrieval API 基础地址，默认 https://aigw.asiainfo.com/v1
# RERANK_TOP_N             重排序后返回的文档数量，默认 5
# RERANK_CONTEXT_WINDOW    重排序上下文扩展窗口，前后各取 N 个相邻 chunk，默认 1
# RERANK_API_URL           外部重排序 API 地址（默认 https://aigw.asiainfo.com/v1/rerank），置空则回退本地 CrossEncoder
# RERANK_API_KEY           外部重排序 API 密钥（Bearer Token）
# RERANK_API_MODEL         外部重排序 API 模型名，默认 10086/bge-reranker-v2-m3
# EMBEDDING_API_URL        外部 Embedding API 地址（默认 https://aigw.asiainfo.com/v1/embeddings），置空则回退本地模型
# EMBEDDING_API_KEY        外部 Embedding API 密钥（Bearer Token）
# EMBEDDING_API_MODEL      外部 Embedding API 模型名，默认 10086/bge-m3
# SEARCH_TIMEOUT           向量/BM25 检索 API 超时时间（秒），默认 30
# HEALTH_TIMEOUT           健康检查 API 超时时间（秒），默认 5
# ADAPTIVE_TOPK_MIN        自适应 TopK 最小返回数量，默认 5
# ADAPTIVE_TOPK_MAX        自适应 TopK 最大返回数量，默认 25
# ------------------------------------------------------------------
# 显式加载 retrieval 目录下的 .env，确保无论从哪里启动都能读取到配置
load_dotenv(os.path.join(BASE_DIR, ".env"))
# 向量库 API 配置
VECTOR_API_URL = os.getenv("VECTOR_API_URL", "https://equivalent-handling-heritage-hat.trycloudflare.com/")
VECTOR_API_KEY = os.getenv("VECTOR_API_KEY", None)

# 模型配置
VECTOR_MODEL = os.getenv("VECTOR_MODEL", "BAAI/bge-m3")  # 向量嵌入模型
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")  # 重排序模型

# Score 阈值配置（向量与 BM25 量纲不同，必须分开配置）
VECTOR_SCORE_THRESHOLD = float(os.getenv("VECTOR_SCORE_THRESHOLD", "0.55"))
BM25_SCORE_THRESHOLD = float(os.getenv("BM25_SCORE_THRESHOLD", "-999.0"))
# 兼容旧配置名 RETRIEVAL_SCORE_THRESHOLD（仅作用于向量检索）
if os.getenv("RETRIEVAL_SCORE_THRESHOLD"):
    VECTOR_SCORE_THRESHOLD = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.0"))

# Embedding 维度配置（可根据模型调整）
EMBEDDING_DIMENSION_RETRIEVAL = int(os.getenv("EMBEDDING_DIMENSION_RETRIEVAL", "1024"))

# 查询扩展配置
QUERY_EXPANSION_ENABLED = os.getenv("QUERY_EXPANSION_ENABLED", "false").lower() == "true"
QUERY_EXPANSION_MODEL = os.getenv("QUERY_EXPANSION_MODEL", "aliyun/qwen3.6-plus")
QUERY_EXPANSION_NUM = min(int(os.getenv("QUERY_EXPANSION_NUM", "3")), 5)

# retrieval API 配置（查询扩展用）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")

# 重排序配置
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "5"))
RERANK_CONTEXT_WINDOW = int(os.getenv("RERANK_CONTEXT_WINDOW", "1"))

# 外部重排序 API 配置（可选，配置后替代本地 CrossEncoder）
RERANK_API_URL = os.getenv("RERANK_API_URL", "")
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "sk-")
RERANK_API_MODEL = os.getenv("RERANK_API_MODEL", "10086/bge-reranker-v2-m3")

# 外部 Embedding API 配置（可选，配置后替代本地 HuggingFaceEmbeddings）
EMBEDDING_API_URL = os.getenv("EMBEDDING_API_URL", "")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "sk-")
EMBEDDING_API_MODEL = os.getenv("EMBEDDING_API_MODEL", "10086/bge-m3")

# API 超时配置（秒）
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))
HEALTH_TIMEOUT = int(os.getenv("HEALTH_TIMEOUT", "5"))

# 自适应 TopK 边界
ADAPTIVE_TOPK_MIN = int(os.getenv("ADAPTIVE_TOPK_MIN", "5"))
ADAPTIVE_TOPK_MAX = int(os.getenv("ADAPTIVE_TOPK_MAX", "25"))

# ==================== 惰性加载嵌入模型 ====================
_embedding_model = None


class APIEmbeddingModel:
    """通过外部 API（OpenAI 兼容格式）计算 embedding"""

    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.session = requests.Session()
        print(f"正在初始化 API Embedding 模型: {api_url} (model={model})")

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """调用外部 Embedding API"""
        payload = {
            "model": self.model,
            "input": texts
        }
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=SEARCH_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Embedding API 请求失败: {e}")
        except Exception as e:
            raise RuntimeError(f"Embedding API 解析失败: {e}")

        # OpenAI 兼容格式: {"data": [{"embedding": [...], "index": 0}, ...]}
        data = result.get("data", [])
        if not data:
            raise RuntimeError("Embedding API 返回空数据")

        # 按 index 排序确保顺序一致
        data = sorted(data, key=lambda x: x.get("index", 0))
        embeddings = [item.get("embedding", []) for item in data]

        # 校验维度
        for idx, emb in enumerate(embeddings):
            if len(emb) != EMBEDDING_DIMENSION_RETRIEVAL:
                print(f"警告: Embedding 维度异常: {len(emb)}, 期望 {EMBEDDING_DIMENSION_RETRIEVAL} (index={idx})")

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """对单个查询文本计算 embedding"""
        embeddings = self._call_api([text])
        return embeddings[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """对批量文档计算 embedding"""
        return self._call_api(texts)


def get_embedding_model():
    """惰性加载 Embedding 模型（本地 HuggingFace 或远程 API）"""
    global _embedding_model
    if _embedding_model is None:
        if EMBEDDING_API_URL:
            _embedding_model = APIEmbeddingModel(
                api_url=EMBEDDING_API_URL,
                api_key=EMBEDDING_API_KEY,
                model=EMBEDDING_API_MODEL
            )
        else:
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
    """获取重排序模型实例（单例模式）

    若配置了 RERANK_API_URL，则使用外部 API 重排序；
    否则回退到本地 CrossEncoder 模型。
    """
    global reranker
    if reranker is None:
        if RERANK_API_URL:
            reranker = APIReranker(
                api_url=RERANK_API_URL,
                api_key=RERANK_API_KEY,
                model=RERANK_API_MODEL,
                top_n=RERANK_TOP_N
            )
        else:
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

        # 校验维度（默认 1024，可通过 EMBEDDING_DIMENSION 环境变量调整）
        if len(embedding) != EMBEDDING_DIMENSION_RETRIEVAL:
            print(f"Embedding 维度异常: {len(embedding)}, 期望 {EMBEDDING_DIMENSION_RETRIEVAL}")
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
                # 向量检索 Score 阈值过滤（cosine 量纲）
                if score < VECTOR_SCORE_THRESHOLD:
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
                # BM25 检索 Score 阈值过滤（BM25 分数可能为负，与向量量纲不同）
                if score < BM25_SCORE_THRESHOLD:
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


_api_client_checked = False


def get_api_client():
    """获取 API 客户端实例（延迟健康检查，避免模块导入时触发网络请求）"""
    global _api_client, _api_client_checked
    if _api_client is None:
        _api_client = VectorAPIClient()
    # 仅在第一次获取时检查一次，不阻塞模块导入
    if not _api_client_checked:
        _api_client_checked = True
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

    # 用 Python 对象 id 建立 doc -> 其在所属文件列表中索引的映射，避免 char_offset 冲突
    index_map = {}
    for fp, file_docs in by_file.items():
        for idx, d in enumerate(file_docs):
            index_map[id(d)] = idx

    expanded_texts = []
    for doc in docs:
        fp = doc.metadata.get("file_path", "")
        file_docs = by_file.get(fp, [])

        idx = index_map.get(id(doc))
        if idx is None:
            expanded_texts.append(doc.page_content)
            continue

        # 收集前后 window 个相邻 chunk
        parts = []
        for j in range(max(0, idx - window), min(len(file_docs), idx + window + 1)):
            parts.append(file_docs[j].page_content)

        expanded_texts.append("\n".join(parts))

    return expanded_texts


# ==================== Reranker（本地 CrossEncoder）====================
class Reranker:
    def __init__(self, model_name=RERANKER_MODEL, top_n=RERANK_TOP_N):
        print(f"正在加载重排序模型: {model_name}...")
        self.model = CrossEncoder(model_name, tokenizer_kwargs={'truncation': True, 'padding': True})
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
        scores = self.model.predict(pairs,batch_size=8)
        # 将原始 logits 通过 Sigmoid 映射到 (0, 1)，与 bge-reranker-base 行为对齐
        scores = 1 / (1 + np.exp(-np.array(scores)))
        # 将 reranker 分数写入 metadata，供下游阈值判断
        for idx, score in enumerate(scores):
            docs[idx].metadata["reranker_score"] = float(score)

        sorted_idx = np.argsort(scores)[::-1]
        return [docs[i] for i in sorted_idx[:self.top_n]]


# ==================== API Reranker（远程 API 调用）====================
class APIReranker:
    """通过外部 API（如 aigw.asiainfo.com）进行重排序"""

    def __init__(self, api_url: str, api_key: str, model: str, top_n: int = RERANK_TOP_N):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.top_n = top_n
        self.session = requests.Session()
        print(f"正在初始化 API 重排序器: {api_url} (model={model})")

    def rerank(self, query: str, docs: List[Document]):
        if not docs:
            return []

        # 上下文扩展：用相邻 chunk 补全后打分
        expanded_texts = _expand_rerank_context(docs)
        if RERANK_CONTEXT_WINDOW > 0:
            print(f"重排序上下文扩展: window={RERANK_CONTEXT_WINDOW}")

        payload = {
            "model": self.model,
            "return_text": True,
            "query": query,
            "documents": expanded_texts
        }

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=SEARCH_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            print(f"API 重排序请求失败: {e}")
            return docs[:self.top_n]
        except Exception as e:
            print(f"API 重排序解析失败: {e}")
            return docs[:self.top_n]

        # 解析返回结果：标准 rerank API 返回 { "results": [{"index": 0, "relevance_score": 0.9, "text": "..."}, ...] }
        results = result.get("results", [])
        if not results:
            print("API 重排序返回空结果，返回原始排序")
            return docs[:self.top_n]

        # 按 relevance_score 降序排序
        sorted_results = sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True)

        reranked_docs = []
        for item in sorted_results[:self.top_n]:
            idx = item.get("index")
            if idx is None or idx < 0 or idx >= len(docs):
                continue
            score = item.get("relevance_score", 0.0)
            docs[idx].metadata["reranker_score"] = float(score)
            reranked_docs.append(docs[idx])

        print(f"API 重排序完成: {len(reranked_docs)} 篇文档")
        return reranked_docs


def _merge_results(vec_docs: List[Document], bm25_docs: List[Document]) -> List[Document]:
    """合并向量检索和 BM25 检索结果，按 chunk_id 去重，保留双路分数"""
    all_docs = {}
    # 先处理向量检索结果
    for doc in vec_docs:
        key = doc.metadata.get("chunk_id", doc.page_content[:100])
        all_docs[key] = doc

    # 再处理 BM25 结果，保留 bm25 分数信息
    for doc in bm25_docs:
        key = doc.metadata.get("chunk_id", doc.page_content[:100])
        if key in all_docs:
            # 合并分数信息：将 BM25 的分数写入已存在的文档
            all_docs[key].metadata["bm25_rank"] = doc.metadata.get("bm25_rank")
            all_docs[key].metadata["bm25_score"] = doc.metadata.get("score")
        else:
            all_docs[key] = doc

    return list(all_docs.values())


# ==================== 查询扩展 ====================
def expand_query(query: str, num_variants: int = QUERY_EXPANSION_NUM) -> List[str]:
    """
    查询扩展：基于 retrieval 生成语义相关的查询变体，提升检索召回率。

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
def pipeline(query: str, top_k: int = 10, use_bm25: bool = True,
             use_rerank: bool = True, use_query_expansion: bool = False):
    """
    检索管道（双路 API 检索 + 查询扩展 + 重排序）

    Args:
        query: 查询字符串
        top_k: 每路检索返回数量
        use_bm25: 是否启用 BM25 API 检索
        use_rerank: 是否启用 CrossEncoder 重排序
        use_query_expansion: 是否启用查询扩展（会调用 retrieval 生成查询变体）
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

    # 对每个查询变体分别检索（最多处理 3 个变体，防止 API 调用量暴增）
    for q in queries[:3]:
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

    # CrossEncoder 重排序（可选）— 先重排序，再截断，避免丢失高质量候选
    if use_rerank:
        reranker = get_reranker()
        docs = reranker.rerank(query, docs)

    # 自适应 TopK 截断
    k = adaptive_topk_simple(query, docs)
    docs = docs[:k]

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