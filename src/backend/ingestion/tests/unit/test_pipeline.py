"""测试 index_pipeline 主流程（mock embedding 避免真实模型）。"""
from unittest.mock import patch
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import get_document
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import index_pipeline, handle_file_delete


@pytest.fixture
def setup(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr(
        "backend.ingestion.sync.pipeline.DB_PATH", tmp_db_path
    )
    monkeypatch.setattr(
        "backend.ingestion.sync.pipeline.RAW_DIR", tmp_raw_dir
    )
    return tmp_db_path, tmp_raw_dir


@pytest.mark.asyncio
async def test_index_md_file_writes_chunks(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("# Title\n\n" + ("body text. " * 20), encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        result = await index_pipeline("test.md")

    assert result["status"] == "indexed"
    assert result["chunk_count"] >= 1

    conn = get_connection(db_path)
    assert count_chunks(conn) == result["chunk_count"]
    doc = get_document(conn, "test.md")
    assert doc["index_status"] == "indexed"
    conn.close()


@pytest.mark.asyncio
async def test_unchanged_file_returns_unchanged(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("# T\n\n" + ("hello world. " * 10), encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        await index_pipeline("test.md")
        result = await index_pipeline("test.md")

    assert result["status"] == "unchanged"


@pytest.mark.asyncio
async def test_modified_file_replaces_chunks(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("v1 content " * 30, encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        await index_pipeline("test.md")

        f.write_text("v2 different content " * 30, encoding="utf-8")
        await index_pipeline("test.md")

    conn = get_connection(db_path)
    rows = conn.execute("SELECT DISTINCT file_hash FROM chunks").fetchall()
    assert len(rows) == 1
    conn.close()


@pytest.mark.asyncio
async def test_file_not_found_raises(setup):
    with pytest.raises(FileNotFoundError):
        await index_pipeline("does_not_exist.md")


@pytest.mark.asyncio
async def test_handle_file_delete(setup):
    db_path, raw = setup
    f = raw / "del.md"
    f.write_text("# T\n\n" + ("body. " * 30))

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        await index_pipeline("del.md")

    result = await handle_file_delete("del.md")
    assert result["status"] == "deleted"
    assert result["deleted_chunks"] >= 1

    conn = get_connection(db_path)
    assert count_chunks(conn) == 0
    assert get_document(conn, "del.md") is None
    conn.close()
