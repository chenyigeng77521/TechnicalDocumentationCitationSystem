"""测试启动扫描 + 孤儿 chunk GC。"""
from datetime import datetime, timezone
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import insert_chunks, count_chunks
from backend.ingestion.sync.gc import initial_scan, gc_orphan_chunks


def _utcnow():
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_initial_scan_indexes_new_files(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.RAW_DIR", tmp_raw_dir)

    (tmp_raw_dir / "new.md").write_text("# T\n\nbody")

    indexed = []

    async def fake_index(p):
        indexed.append(p)

    async def fake_delete(p):
        pass

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    assert indexed == ["new.md"]


@pytest.mark.asyncio
async def test_initial_scan_deletes_missing_files(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.RAW_DIR", tmp_raw_dir)

    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="ghost.md", file_name="ghost.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=_utcnow())
    conn.close()

    deleted = []

    async def fake_index(p):
        pass

    async def fake_delete(p):
        deleted.append(p)

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    assert deleted == ["ghost.md"]


def test_gc_orphan_chunks_removes_chunks_without_doc(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="a.md", file_name="a.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=_utcnow())
    insert_chunks(conn, [{
        "chunk_id": "c1", "file_path": "a.md", "file_hash": "h",
        "index_version": "v1", "content": "x", "anchor_id": "a.md#0",
        "title_path": None, "char_offset_start": 0, "char_offset_end": 1,
        "char_count": 1, "chunk_index": 0,
    }])
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM documents WHERE file_path='a.md'")
    conn.commit()
    assert count_chunks(conn) == 1
    conn.close()

    gc_orphan_chunks(tmp_db_path)

    conn = get_connection(tmp_db_path)
    assert count_chunks(conn) == 0
    conn.close()
