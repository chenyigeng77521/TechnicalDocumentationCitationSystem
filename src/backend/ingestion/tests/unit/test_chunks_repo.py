"""测试 chunks 表 CRUD + 向量/全文检索。"""
from datetime import datetime, timezone
import json
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import (
    insert_chunks, delete_chunks_by_file, get_chunk,
    vector_search, text_search, count_chunks,
)


def _seed_doc(conn, file_path="a.md"):
    upsert_document(conn, file_path=file_path, file_name=file_path,
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.now(timezone.utc))


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def _make_chunk(chunk_id="c1", content="hello world", embedding=None,
                file_path="a.md", offset=0, title_path=None):
    return {
        "chunk_id": chunk_id, "file_path": file_path, "file_hash": "h",
        "index_version": "v1", "content": content,
        "anchor_id": f"{file_path}#{offset}", "title_path": title_path,
        "char_offset_start": offset, "char_offset_end": offset + len(content),
        "char_count": len(content), "chunk_index": 0,
        "is_truncated": False, "content_type": "document", "language": "zh",
        "embedding": embedding or [0.0] * 1024,
    }


def test_insert_chunks_and_get(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", "hello"), _make_chunk("c2", "world")])
    assert count_chunks(conn) == 2
    c = get_chunk(conn, "c1")
    assert c["content"] == "hello"
    assert json.loads(c["embedding"])[0] == 0.0


def test_delete_chunks_by_file(conn):
    _seed_doc(conn, "a.md")
    _seed_doc(conn, "b.md")
    insert_chunks(conn, [
        _make_chunk("c1", file_path="a.md"),
        _make_chunk("c2", file_path="b.md"),
    ])
    delete_chunks_by_file(conn, "a.md")
    assert count_chunks(conn) == 1
    assert get_chunk(conn, "c1") is None


def test_vector_search_returns_top_k_by_cosine(conn):
    _seed_doc(conn)
    e1 = [1.0] + [0.0] * 1023
    e2 = [0.5, 0.5] + [0.0] * 1022
    e3 = [0.0, 1.0] + [0.0] * 1022
    insert_chunks(conn, [
        _make_chunk("c1", "a", embedding=e1),
        _make_chunk("c2", "b", embedding=e2),
        _make_chunk("c3", "c", embedding=e3),
    ])
    query_emb = [1.0] + [0.0] * 1023
    results = vector_search(conn, query_emb, top_k=2)
    assert len(results) == 2
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["score"] > results[1]["score"]


def test_text_search_uses_fts(conn):
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk("c1", content="OAuth2 token refresh guide"),
        _make_chunk("c2", content="installation steps overview"),
    ])
    results = text_search(conn, "OAuth2", top_k=10)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "bm25_rank" in results[0]
    assert results[0]["score"] > 0


def test_text_search_returns_empty_on_no_match(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", content="hello world")])
    assert text_search(conn, "xyz_nonexistent", top_k=10) == []


# ============================================================
# Task 5: markdown_anchor 字段 CRUD 测试
# ============================================================

def test_insert_and_get_chunk_with_markdown_anchor(conn):
    _seed_doc(conn)
    chunk = _make_chunk("c1", "test content with markdown anchor here long enough")
    chunk["markdown_anchor"] = "#test-anchor"
    insert_chunks(conn, [chunk])
    row = get_chunk(conn, "c1")
    assert row is not None
    assert row["markdown_anchor"] == "#test-anchor"


def test_insert_chunk_without_markdown_anchor_uses_null(conn):
    """老调用方不传 markdown_anchor → DB 存 NULL（向后兼容）"""
    _seed_doc(conn)
    chunk = _make_chunk("c2", "test content for null anchor case here long enough")
    # 不设 markdown_anchor key
    insert_chunks(conn, [chunk])
    row = get_chunk(conn, "c2")
    assert row is not None
    assert row["markdown_anchor"] is None


def test_vector_search_returns_markdown_anchor(conn):
    """vector_search 结果 dict 应含 markdown_anchor 键"""
    _seed_doc(conn)
    chunk = _make_chunk("c3", "content for vector search test long enough here yes")
    chunk["markdown_anchor"] = "#vec-test"
    insert_chunks(conn, [chunk])
    results = vector_search(conn, [0.0] * 1024, top_k=5)
    assert any(r.get("markdown_anchor") == "#vec-test" for r in results)


def test_migrate_old_db_adds_column(tmp_path):
    """老 DB（无 markdown_anchor 列）经 init_db 之后应自动加列。"""
    import sqlite3 as _sqlite3
    db_path = tmp_path / "old.db"
    # 第一步：手工建一个"老 DB"（不含 markdown_anchor 列）
    raw_conn = _sqlite3.connect(db_path)
    raw_conn.executescript("""
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            index_version TEXT NOT NULL,
            content TEXT NOT NULL,
            anchor_id TEXT NOT NULL,
            title_path TEXT,
            char_offset_start INTEGER NOT NULL,
            char_offset_end INTEGER NOT NULL,
            char_count INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            is_truncated INTEGER DEFAULT 0,
            content_type TEXT NOT NULL DEFAULT 'document',
            language TEXT,
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    raw_conn.commit()
    raw_conn.close()
    # 第二步：跑 init_db 触发迁移
    init_db(db_path)
    # 第三步：检查列已加
    raw_conn = _sqlite3.connect(db_path)
    cols = [r[1] for r in raw_conn.execute("PRAGMA table_info(chunks)").fetchall()]
    raw_conn.close()
    assert "markdown_anchor" in cols
