"""SLA 性能基线（用 mock embedding，只测自身处理速度）。

Spec: §13 - 100 页 PDF 端到端 < 30s
"""
import time
from unittest.mock import patch
import pytest
from backend.ingestion.db.connection import init_db
from backend.ingestion.sync.pipeline import index_pipeline


@pytest.fixture
def setup(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.RAW_DIR", tmp_raw_dir)
    return tmp_db_path, tmp_raw_dir


@pytest.mark.asyncio
async def test_small_md_under_5s(setup):
    """10KB markdown < 5s（不含真实 embedding）。"""
    _, raw = setup
    f = raw / "small.md"
    f.write_text("# T\n\n" + ("body sentence. " * 500))

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        t0 = time.time()
        await index_pipeline("small.md")
        elapsed = time.time() - t0

    assert elapsed < 5.0, f"小文件超时: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_medium_md_under_30s(setup):
    """100KB markdown < 30s。"""
    _, raw = setup
    f = raw / "medium.md"
    f.write_text("# T\n\n" + ("paragraph content " * 5000))

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        t0 = time.time()
        await index_pipeline("medium.md")
        elapsed = time.time() - t0

    assert elapsed < 30.0, f"中文件超时: {elapsed:.2f}s"
