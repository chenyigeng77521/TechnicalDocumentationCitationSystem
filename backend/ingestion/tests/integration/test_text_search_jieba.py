"""集成测试：text_search 端到端行为

spec §3.2 + §5 T6/T7/T8/T9
"""
import pytest
from pathlib import Path

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, text_search


@pytest.fixture
def empty_db(tmp_path):
    """全新 DB，无任何 chunk。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


def _insert_doc_and_chunk(conn, file_path, chunk_id, content):
    """测试辅助：插一个 document + 一个 chunk。"""
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES (?, ?, 'h', 1, 'md', 'v1', '2026-04-28')
    """, (file_path, Path(file_path).name))
    insert_chunks(conn, [{
        "chunk_id": chunk_id,
        "file_path": file_path,
        "file_hash": "h",
        "index_version": "v1",
        "content": content,
        "anchor_id": "a",
        "char_offset_start": 0,
        "char_offset_end": len(content),
        "char_count": len(content),
        "chunk_index": 0,
    }])


def test_search_empty_query_returns_empty(empty_db):
    """T8: 空 / 全标点 query → text_search 返 []，不打 FTS5。"""
    conn = get_connection(empty_db)
    try:
        assert text_search(conn, "") == []
        assert text_search(conn, "   ") == []
        assert text_search(conn, "...") == []
        assert text_search(conn, "！？。") == []
    finally:
        conn.close()
