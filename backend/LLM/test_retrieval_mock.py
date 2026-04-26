#!/usr/bin/env python3
"""
retrieval.py 向量检索功能模拟测试程序

启动一个 Mock HTTP Server 模拟向量库 /chunks/vector-search 接口，
对 VectorAPIClient 进行端到端测试，覆盖正常/异常/边界场景。

使用方法：
    cd /Users/lenghaijun/PycharmProjects/TechnicalDocumentationCitationSystem/backend/LLM
    python test_retrieval_mock.py
"""
import json
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch, MagicMock
from pathlib import Path


# ==================== 阻止模型下载：在导入 retrieval 前 mock HuggingFaceEmbeddings ====================
class MockHuggingFaceEmbeddings:
    """模拟 HuggingFaceEmbeddings，避免加载真实模型"""
    def __init__(self, *args, **kwargs):
        pass
    def embed_query(self, text: str) -> list:
        return [0.01] * 1024
    def embed_documents(self, texts: list) -> list:
        return [[0.01] * 1024 for _ in texts]


# 注入 mock，使 retrieval.py 在模块级别初始化 embedding_model 时不下载模型
_mock_hf_module = MagicMock()
_mock_hf_module.HuggingFaceEmbeddings = MockHuggingFaceEmbeddings
sys.modules['langchain_huggingface'] = _mock_hf_module
sys.modules['langchain_community.embeddings'] = _mock_hf_module

# 确保 retrieval.py 在路径中
sys.path.insert(0, str(Path(__file__).parent))

from retrieval import VectorAPIClient

# ==================== Mock 数据 ====================
MOCK_CHUNKS = [
    {
        "chunk_id": "81e76ae62a95a1b2c3d4e5f678901234567890ab12cd34ef56gh78ij90kl12mn34op",
        "content": "OAuth2 token refresh requires the `Authorization: Bearer {refresh_token}` header.\nToken has a 7-day default expiry.",
        "score": 0.85,
        "metadata": {
            "file_path": "api/auth.md",
            "anchor_id": "api/auth.md#38",
            "title_path": "Sample Document > Authentication",
            "char_offset_start": 38,
            "char_offset_end": 153,
            "is_truncated": False,
            "content_type": "document",
            "language": "en",
            "last_modified": "2026-04-20T10:30:00Z"
        }
    },
    {
        "chunk_id": "aabbccdd11223344556677889900aabbccddeeff00112233445566778899aabbcc",
        "content": "向量检索通过计算 query 与文档片段的 cosine similarity 来找出语义最相近的内容。",
        "score": 0.78,
        "metadata": {
            "file_path": "docs/retrieval.md",
            "anchor_id": "docs/retrieval.md#120",
            "title_path": "技术文档 > 检索系统",
            "char_offset_start": 120,
            "char_offset_end": 280,
            "is_truncated": False,
            "content_type": "document",
            "language": "zh",
            "last_modified": None
        }
    },
    {
        "chunk_id": "99887766554433221100ffeeddccbbaa0099887766554433221100ffeeddccbbaa",
        "content": "BM25 是一种基于概率检索框架的排序函数，广泛用于搜索引擎的关键词匹配阶段。",
        "score": 0.62,
        "metadata": {
            "file_path": "docs/bm25.md",
            "anchor_id": "docs/bm25.md#0",
            "title_path": None,
            "char_offset_start": 0,
            "char_offset_end": 95,
            "is_truncated": True,
            "content_type": "document",
            "language": "zh",
            "last_modified": None
        }
    },
    {
        "chunk_id": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        "content": "CrossEncoder 通过将 query 和 document 拼接后输入模型，输出相关性分数，精度高于双塔模型。",
        "score": 0.55,
        "metadata": {
            "file_path": "docs/reranker.md",
            "anchor_id": "docs/reranker.md#56",
            "title_path": "技术文档 > 重排序",
            "char_offset_start": 56,
            "char_offset_end": 198,
            "is_truncated": False,
            "content_type": "document",
            "language": "zh",
            "last_modified": "2026-04-22T08:15:00Z"
        }
    },
]


# ==================== Mock HTTP Server ====================
class MockVectorAPIHandler(BaseHTTPRequestHandler):
    """模拟向量库 API 服务"""

    def log_message(self, format, *args):
        # 静默服务器日志，避免干扰测试输出
        pass

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/chunks/vector-search":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                req = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return

            # 校验必填字段
            embedding = req.get("embedding")
            if embedding is None:
                self._send_json(400, {"error": "embedding is required"})
                return

            # 校验维度
            if len(embedding) != 1024:
                self._send_json(400, {"error": f"embedding dimension must be 1024, got {len(embedding)}"})
                return

            top_k = req.get("top_k", 50)
            filters = req.get("filters")

            # 模拟过滤（MVP 暂不实现，仅记录日志用于测试验证）
            if filters is not None:
                print(f"    [MockServer] 收到 filters: {filters}")

            # 返回前 top_k 个结果（模拟按 score 降序）
            results = MOCK_CHUNKS[:top_k]
            self._send_json(200, {
                "results": results,
                "total": len(results)
            })

        elif self.path == "/chunks/text-search":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                req = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return

            query = req.get("query", "")
            top_k = req.get("top_k", 50)
            filters = req.get("filters")

            if filters is not None:
                print(f"    [MockServer] BM25 收到 filters: {filters}")

            # 模拟 BM25 结果：返回包含 query 关键词的 chunk（简化：固定返回 chunk 0 和 chunk 2）
            bm25_results = [MOCK_CHUNKS[0], MOCK_CHUNKS[2]]
            # 添加 bm25_rank 字段
            for r in bm25_results:
                r["bm25_rank"] = -0.467

            self._send_json(200, {
                "results": bm25_results[:top_k],
                "total": len(bm25_results[:top_k])
            })
        else:
            self._send_json(404, {"error": "not found"})


def start_mock_server(port: int = 18082):
    """在后台线程启动 Mock Server"""
    server = HTTPServer(("127.0.0.1", port), MockVectorAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # 等待服务器就绪
    time.sleep(0.3)
    return server


# ==================== 测试用例 ====================
class TestRunner:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = VectorAPIClient(api_url=base_url, api_key=None)
        self.passed = 0
        self.failed = 0

    def _mock_embedding(self):
        """mock get_embedding_model() 返回固定 1024 维向量"""
        mock_emb = MagicMock(embed_query=lambda q: [0.01] * 1024)
        return patch("retrieval.get_embedding_model", MagicMock(return_value=mock_emb))

    def _assert(self, condition: bool, msg: str):
        if condition:
            self.passed += 1
            print(f"  ✓ {msg}")
        else:
            self.failed += 1
            print(f"  ✗ {msg}")

    # ---------- 测试 1: 正常查询 ----------
    def test_search_normal(self):
        print("\n[TEST] 正常向量检索")
        with self._mock_embedding():
            docs = self.client.search("如何提高混合检索召回率", top_k=3)

        self._assert(len(docs) == 3, f"返回文档数量应为 3，实际 {len(docs)}")

        doc = docs[0]
        self._assert(doc.page_content == MOCK_CHUNKS[0]["content"],
                     "第一个结果的 content 正确")
        self._assert(doc.metadata.get("chunk_id") == MOCK_CHUNKS[0]["chunk_id"],
                     "metadata.chunk_id 正确")
        self._assert(doc.metadata.get("score") == MOCK_CHUNKS[0]["score"],
                     "metadata.score 正确")
        self._assert(doc.metadata.get("file_path") == "api/auth.md",
                     "metadata.file_path 正确")
        self._assert(doc.metadata.get("anchor_id") == "api/auth.md#38",
                     "metadata.anchor_id 正确")
        self._assert(doc.metadata.get("title_path") == "Sample Document > Authentication",
                     "metadata.title_path 正确")
        self._assert(doc.metadata.get("char_offset_start") == 38,
                     "metadata.char_offset_start 正确")
        self._assert(doc.metadata.get("is_truncated") is False,
                     "metadata.is_truncated 正确")
        self._assert(doc.metadata.get("language") == "en",
                     "metadata.language 正确")

    # ---------- 测试 2: search_with_score ----------
    def test_search_with_score(self):
        print("\n[TEST] 带分数检索")
        with self._mock_embedding():
            docs_with_scores = self.client.search_with_score("BM25 算法原理", top_k=2)

        self._assert(len(docs_with_scores) == 2,
                     f"返回数量应为 2，实际 {len(docs_with_scores)}")

        doc, score = docs_with_scores[0]
        self._assert(isinstance(doc.page_content, str),
                     "Document.page_content 为字符串")
        self._assert(isinstance(score, float),
                     "score 为 float")
        self._assert(score == MOCK_CHUNKS[0]["score"],
                     "第一个 score 值正确")

    # ---------- 测试 3: 空结果（top_k=0）----------
    def test_empty_results(self):
        print("\n[TEST] 空结果场景")
        with self._mock_embedding():
            docs = self.client.search("不存在的查询", top_k=0)

        self._assert(len(docs) == 0, "top_k=0 时应返回空列表")

    # ---------- 测试 4: 维度错误（Mock Server 返回 400）----------
    def test_dimension_error(self):
        print("\n[TEST] Embedding 维度错误（服务端 400）")
        mock_emb = MagicMock(embed_query=lambda q: [0.01] * 512)
        with patch("retrieval.get_embedding_model", MagicMock(return_value=mock_emb)):
            docs = self.client.search("维度测试", top_k=5)

        self._assert(len(docs) == 0, "维度错误时应返回空列表（捕获异常）")

    # ---------- 测试 5: 网络异常 ----------
    def test_network_error(self):
        print("\n[TEST] 网络异常（连接不存在的服务）")
        bad_client = VectorAPIClient(api_url="http://127.0.0.1:59999", api_key=None)
        with self._mock_embedding():
            docs = bad_client.search("网络异常测试", top_k=5)

        self._assert(len(docs) == 0, "网络异常时应返回空列表")

    # ---------- 测试 6: filters 参数透传 ----------
    def test_filters_pass_through(self):
        print("\n[TEST] filters 参数透传")
        filters = {"file_paths": ["api/auth.md"], "min_timestamp": "2026-01-01T00:00:00Z"}
        with self._mock_embedding():
            docs = self.client.search("带过滤的查询", top_k=5, filters=filters)

        self._assert(len(docs) == min(5, len(MOCK_CHUNKS)), "filters 应正常透传并返回结果")

    # ---------- 测试 7: score 阈值过滤 ----------
    def test_score_threshold_filter(self):
        print("\n[TEST] Score 阈值过滤")
        # MOCK_CHUNKS score: 0.85, 0.78, 0.62, 0.55
        with patch("retrieval.MAX_SCORE_THRESHOLD", 0.6):
            with self._mock_embedding():
                docs = self.client.search("阈值测试", top_k=4)

        self._assert(len(docs) == 3,
                     f"阈值 0.6 应过滤掉 0.55，返回 3 个，实际 {len(docs)}")

    # ---------- 测试 8: health_check ----------
    def test_health_check(self):
        print("\n[TEST] 健康检查")
        ok = self.client.health_check()
        self._assert(ok is True, "health_check 应返回 True")

        bad_client = VectorAPIClient(api_url="http://127.0.0.1:59999", api_key=None)
        ok2 = bad_client.health_check()
        self._assert(ok2 is False, "不可达服务应返回 False")

    # ---------- 测试 8: BM25 全文检索 ----------
    def test_text_search_normal(self):
        print("\n[TEST] BM25 全文检索")
        docs = self.client.text_search("BM25 排序函数", top_k=2)

        self._assert(len(docs) == 2, f"返回文档数量应为 2，实际 {len(docs)}")
        self._assert(docs[0].metadata.get("bm25_rank") == -0.467,
                     "metadata.bm25_rank 正确")
        self._assert("OAuth2" in docs[0].page_content or "BM25" in docs[0].page_content,
                     "BM25 返回结果内容正确")

    # ---------- 测试 9: Pipeline 混合检索（合并去重）----------
    def test_pipeline_hybrid(self):
        print("\n[TEST] Pipeline 混合检索（API 向量 + API BM25）")
        from retrieval import pipeline, get_reranker

        # mock embedding 和 reranker，避免加载真实模型
        mock_emb = MagicMock(embed_query=lambda q: [0.01] * 1024)
        mock_reranker = MagicMock()
        mock_reranker.rerank = lambda q, docs: docs  # 不重排，直接返回

        with patch("retrieval.get_embedding_model", MagicMock(return_value=mock_emb)):
            with patch("retrieval.get_reranker", MagicMock(return_value=mock_reranker)):
                results = pipeline("测试查询", top_k=4, use_rerank=True)

        # vector-search 返回 4 个，text-search 返回 2 个（其中 1 个与 vector 重叠）
        # 合并去重后应为 4 个
        self._assert(len(results) == 4,
                     f"混合检索合并去重后应为 4 个，实际 {len(results)}")

    # ---------- 汇总 ----------
    def run_all(self):
        print("=" * 60)
        print("retrieval.py 向量检索模拟测试开始")
        print("=" * 60)

        self.test_health_check()
        self.test_search_normal()
        self.test_search_with_score()
        self.test_empty_results()
        self.test_dimension_error()
        self.test_network_error()
        self.test_filters_pass_through()
        self.test_score_threshold_filter()
        self.test_text_search_normal()
        self.test_pipeline_hybrid()

        print("\n" + "=" * 60)
        print(f"测试结果: 通过 {self.passed} 项, 失败 {self.failed} 项")
        print("=" * 60)

        if self.failed > 0:
            sys.exit(1)


# ==================== 入口 ====================
if __name__ == "__main__":
    # 启动 Mock Server
    mock_port = 18082
    print(f"[*] 启动 Mock 向量库服务: http://127.0.0.1:{mock_port}")
    server = start_mock_server(port=mock_port)

    try:
        runner = TestRunner(base_url=f"http://127.0.0.1:{mock_port}")
        runner.run_all()
    finally:
        print("[*] 关闭 Mock 服务")
        server.shutdown()
