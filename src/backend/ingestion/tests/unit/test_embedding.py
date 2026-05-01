"""测试 bge-m3 embedding 包装器（mock 模型避免下载）。"""
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
from backend.ingestion.common.embedding import batch_embed, EMBEDDING_DIM


def test_embedding_dim_constant():
    assert EMBEDDING_DIM == 1024


@pytest.mark.asyncio
async def test_batch_embed_calls_model_with_normalize():
    fake_vecs = np.array([[0.1] * 1024, [0.2] * 1024], dtype=np.float32)
    fake_model = MagicMock()
    fake_model.encode.return_value = fake_vecs
    with patch("backend.ingestion.common.embedding.get_model", return_value=fake_model):
        result = await batch_embed(["text1", "text2"], concurrency=2)
    assert len(result) == 2
    assert len(result[0]) == 1024
    assert isinstance(result[0], list)
    assert isinstance(result[0][0], float)
    fake_model.encode.assert_called()
    call_kwargs = fake_model.encode.call_args.kwargs
    assert call_kwargs["normalize_embeddings"] is True


@pytest.mark.asyncio
async def test_batch_embed_empty_input():
    with patch("backend.ingestion.common.embedding.get_model"):
        result = await batch_embed([], concurrency=8)
    assert result == []
