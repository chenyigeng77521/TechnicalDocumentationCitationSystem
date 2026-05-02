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
    monkeypatch.setattr("backend.ingestion.sync.gc.STORAGE_DIR", tmp_raw_dir)

    # _walk_raw 只扫 STORAGE_DIR/docs/，文件必须放进 docs/ 子目录才能被发现
    target = tmp_raw_dir / "docs" / "test" / "new.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# T\n\nbody")

    indexed = []

    async def fake_index(p):
        indexed.append(p)

    async def fake_delete(p):
        pass

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    # 相对 STORAGE_DIR 的路径自带 docs/<domain>/ 前缀
    assert indexed == ["docs/test/new.md"]


@pytest.mark.asyncio
async def test_initial_scan_deletes_missing_files(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.STORAGE_DIR", tmp_raw_dir)

    # 确保 docs/ 子目录存在（否则 _walk_raw 返回 set()）
    (tmp_raw_dir / "docs").mkdir(parents=True, exist_ok=True)

    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="docs/test/ghost.md", file_name="ghost.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=_utcnow())
    conn.close()

    deleted = []

    async def fake_index(p):
        pass

    async def fake_delete(p):
        deleted.append(p)

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    assert deleted == ["docs/test/ghost.md"]


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
