"""X1.5 痛点 query 回归测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.2

这两题在 X0 路径下 top-3 不含答案；X1.5 必须救回 top-3。
"""
import pytest
import requests
from sentence_transformers import SentenceTransformer

INGESTION_URL = "http://localhost:3003"


@pytest.fixture(scope="module")
def health_check():
    try:
        r = requests.get(f"{INGESTION_URL}/health", timeout=2)
        if r.status_code != 200:
            pytest.skip("ingestion not up")
    except requests.exceptions.RequestException:
        pytest.skip("ingestion not reachable")


@pytest.fixture(scope="module")
def embed_model():
    return SentenceTransformer("BAAI/bge-m3")


def _retrieve_top3(model, query):
    emb = model.encode(query, normalize_embeddings=True).tolist()
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": emb, "top_k": 30},
        timeout=30,
    )
    return r.json()["results"][:3]


# 测什么行为：K8s "API 发起驱逐" query 在 X1.5 下 top-3 含 kubelet/宽限期/EndpointSlice 任一关键词
# 输入：真实 query
# 期望：top-3 至少 1 个 result content 含答案关键词
# 为什么必须测：X1.5 设计的核心痛点，回归测试防退化
def test_k8s_eviction_painpoint(health_check, embed_model):
    top3 = _retrieve_top3(embed_model, "API 发起驱逐的工作原理是什么")
    keywords = ["kubelet", "宽限期", "EndpointSlice"]
    hit = any(any(kw in r["content"] for kw in keywords) for r in top3)
    assert hit, f"top-3 不含 {keywords} 任一关键词，X1.5 退化！"


# 测什么行为：React 数据获取库 query 在 X1.5 下 top-3 含 TanStack Query/SWR/RTK Query 任一
# 输入：真实 query
# 期望：top-3 至少 1 个 result content 含关键词
# 为什么必须测：第二个痛点，回归测试
def test_react_data_fetching_painpoint(health_check, embed_model):
    top3 = _retrieve_top3(
        embed_model,
        "从大多数后端或 REST 风格 API 获取数据时，React 建议使用哪些库？",
    )
    keywords = ["TanStack Query", "SWR", "RTK Query"]
    hit = any(any(kw in r["content"] for kw in keywords) for r in top3)
    assert hit, f"top-3 不含 {keywords} 任一关键词，X1.5 退化！"
