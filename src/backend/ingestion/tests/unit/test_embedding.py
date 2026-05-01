"""测试 embedding 包装器（mock httpx 避免真打网关）。

迁移记录：原本 mock SentenceTransformer 本地模型，
迁移到统一 AI 网关后改为 mock httpx 验证 HTTP 调用契约。
"""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.ingestion.common.embedding import (
    batch_embed,
    embed_single,
    EMBEDDING_DIM,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """所有测试自动设 API key 环境变量。"""
    monkeypatch.setenv("AIGW_API_KEY", "sk-test-fake-key")
    yield


def _make_mock_response(embeddings: list[list[float]]) -> MagicMock:
    """造一个 OpenAI 兼容的 embedding 响应 mock。"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "object": "list",
        "model": "10086/bge-m3",
        "data": [
            {"object": "embedding", "embedding": emb, "index": i}
            for i, emb in enumerate(embeddings)
        ],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    })
    return resp


def _mock_async_client(post_response):
    """造一个 mock httpx.AsyncClient。"""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=post_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# 测什么行为：dim 常量是 1024（bge-m3 标准），跟 DB schema 对齐
def test_embedding_dim_constant():
    assert EMBEDDING_DIM == 1024


# 测什么行为：默认 base_url + model 跟飞书文档约定一致
def test_default_config():
    assert DEFAULT_BASE_URL == "https://aigw.asiainfo.com/v1"
    assert DEFAULT_MODEL == "10086/bge-m3"


# 测什么行为：AIGW_API_KEY 未设置时 raise，明确报错
# 输入：删 env var 后调 batch_embed
# 期望：RuntimeError 含 AIGW_API_KEY 字样
# 为什么必须测：生产配置错时第一时间暴露
@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("AIGW_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AIGW_API_KEY"):
        await batch_embed(["hello"])


# 测什么行为：空输入直接返回 []，不发任何 HTTP 请求
# 输入：[]
# 期望：返回 []，httpx 不被实例化
# 为什么必须测：避免空 batch 浪费网关 quota
@pytest.mark.asyncio
async def test_empty_input_returns_empty():
    with patch("backend.ingestion.common.embedding.httpx.AsyncClient") as mock_cls:
        result = await batch_embed([])
    assert result == []
    mock_cls.assert_not_called()


# 测什么行为：正常 batch 请求，POST schema 符合飞书文档约定
# 输入：3 条文本
# 期望：返回 3 个 1024-d embedding；POST body 含 model + input；header 含 Bearer key
# 为什么必须测：核心契约，schema 错全链路崩
@pytest.mark.asyncio
async def test_batch_embed_normal():
    fake_embs = [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]
    mock_resp = _make_mock_response(fake_embs)
    mock_client = _mock_async_client(mock_resp)

    with patch("backend.ingestion.common.embedding.httpx.AsyncClient", return_value=mock_client):
        result = await batch_embed(["a", "b", "c"], concurrency=4)

    assert len(result) == 3
    assert len(result[0]) == 1024

    call = mock_client.post.call_args
    url = call.args[0]
    body = call.kwargs["json"]
    headers = call.kwargs["headers"]
    assert "/embeddings" in url
    assert body["model"] == "10086/bge-m3"
    assert body["input"] == ["a", "b", "c"]
    assert headers["Authorization"] == "Bearer sk-test-fake-key"


# 测什么行为：网关返回 data 乱序时按 index 排序
# 输入：3 条文本，网关返回 [index=2, index=0, index=1]
# 期望：输出严格跟输入对应
# 为什么必须测：OpenAI 标准允许 data 乱序，不排序会让 chunks 跟 embedding 错位
@pytest.mark.asyncio
async def test_response_sorted_by_index():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "object": "list",
        "data": [
            {"embedding": [0.3] * 1024, "index": 2},
            {"embedding": [0.1] * 1024, "index": 0},
            {"embedding": [0.2] * 1024, "index": 1},
        ],
    })
    mock_client = _mock_async_client(resp)

    with patch("backend.ingestion.common.embedding.httpx.AsyncClient", return_value=mock_client):
        result = await batch_embed(["a", "b", "c"])

    assert result[0][0] == 0.1
    assert result[1][0] == 0.2
    assert result[2][0] == 0.3


# 测什么行为：embed_single 是 batch_embed 的简化包装
# 输入：单条 text
# 期望：返回 1024-d embedding
# 为什么必须测：便利接口，确保跟 batch 路径一致
@pytest.mark.asyncio
async def test_embed_single():
    fake_emb = [0.5] * 1024
    mock_resp = _make_mock_response([fake_emb])
    mock_client = _mock_async_client(mock_resp)

    with patch("backend.ingestion.common.embedding.httpx.AsyncClient", return_value=mock_client):
        result = await embed_single("hello")

    assert len(result) == 1024
    assert result[0] == 0.5
