from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.client import LlmClient


@pytest.mark.asyncio
async def test_stream_answer_yields_tokens():
    async def fake_iter():
        for t in ["你", "好", "，", "世界"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock(delta=MagicMock(content=t))]
            yield chunk

    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=fake_iter())
    c = LlmClient(client=fake_openai, model="test-model")

    tokens = [t async for t in c.stream_answer("prompt")]
    assert tokens == ["你", "好", "，", "世界"]


@pytest.mark.asyncio
async def test_stream_answer_skips_empty_delta():
    async def fake_iter():
        for t in ["hi", None, "", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock(delta=MagicMock(content=t))]
            yield chunk

    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=fake_iter())
    c = LlmClient(client=fake_openai, model="m")
    assert [t async for t in c.stream_answer("p")] == ["hi", "!"]
