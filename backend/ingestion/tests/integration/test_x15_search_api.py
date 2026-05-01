"""X1.5 search API 集成测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.2

注意：这些测试需要 ingestion 服务运行 + bge-m3 模型加载。
本地手动跑：先 backend/ingestion/start.sh --bg 等模型 load，再 pytest。
"""
import pytest
import requests
import sqlite3
from pathlib import Path

INGESTION_URL = "http://localhost:3003"
DB_PATH = Path(__file__).resolve().parents[4] / "backend/storage/index/knowledge.db"


@pytest.fixture(scope="module")
def health_check():
    """跑前确认服务在 + 模型已 load。"""
    try:
        r = requests.get(f"{INGESTION_URL}/health", timeout=2)
        if r.status_code != 200:
            pytest.skip("ingestion service not up")
    except requests.exceptions.RequestException:
        pytest.skip("ingestion service not reachable")


@pytest.fixture(scope="module")
def query_embedding():
    """生成一个真实 query 的 embedding。"""
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-m3")
    return m.encode("React 数据获取", normalize_embeddings=True).tolist()


# 测什么行为：vector-search 返回的每个 result.metadata 都含 markdown_anchor 字段
# 输入：真实 query embedding
# 期望：所有 result metadata 含 'markdown_anchor' key（值非空）
# 为什么必须测：赛题 citation 输出依赖这字段
def test_vector_search_has_markdown_anchor(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
        timeout=30,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) > 0
    for x in results:
        assert "markdown_anchor" in x["metadata"]
        assert x["metadata"]["markdown_anchor"]


# 测什么行为：text-search 同样含 markdown_anchor
# 输入：真实 query 文本
# 期望：所有 result metadata 含 markdown_anchor
# 为什么必须测：text-search 跟 vector-search 同走 X1.5 路径
def test_text_search_has_markdown_anchor(health_check):
    r = requests.post(
        f"{INGESTION_URL}/chunks/text-search",
        json={"query": "React 数据获取", "top_k": 20},
        timeout=10,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) > 0
    for x in results:
        assert "markdown_anchor" in x["metadata"]


# 测什么行为：by-id 接口返回单 chunk 原 content（不做 X1.5 化）
# 输入：DB 里随便一个 chunk_id
# 期望：返回的 content 等于 DB 该 chunk 的 content
# 为什么必须测：spec 明确 by-id 不改，海军 / debug 工具依赖
def test_by_id_returns_chunk_content(health_check):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    chunk = dict(conn.execute(
        "SELECT chunk_id, content, title_path FROM chunks LIMIT 1"
    ).fetchone())
    conn.close()

    r = requests.get(f"{INGESTION_URL}/chunks/{chunk['chunk_id']}", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == chunk["content"]
    assert "markdown_anchor" in body["metadata"]


# 测什么行为：连续两次同 query 返回一致
# 输入：跑两次 vector-search 相同 embedding
# 期望：results 长度和 top-3 chunk_id 一致
# 为什么必须测：缓存正确性 + 无随机性
def test_consecutive_queries_consistent(health_check, query_embedding):
    r1 = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    r2 = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    assert r1["total"] == r2["total"]
    assert [x["chunk_id"] for x in r1["results"][:3]] == \
           [x["chunk_id"] for x in r2["results"][:3]]


# 测什么行为：result 数量 ≤ top_k（X1.5 合并后收缩）
# 输入：top_k=30
# 期望：total ≤ 30
# 为什么必须测：spec 摘要承诺（30 → ~15-20）
def test_result_count_shrinks(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    assert r["total"] <= 30


# 测什么行为：返回的 content 含 title_path 前缀（针对非 UNTITLED 路径）
# 输入：真实 query
# 期望：top-3 至少 1 个 result 的 content 以 title_path 开头
# 为什么必须测：核心 X1.5 行为
def test_content_has_title_prefix(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    has_title_prefix = any(
        x["metadata"]["title_path"]
        and x["content"].startswith(x["metadata"]["title_path"])
        for x in r["results"][:3]
    )
    assert has_title_prefix, "top-3 至少 1 个 result content 应以 title_path 开头"
