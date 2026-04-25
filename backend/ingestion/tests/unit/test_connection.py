"""测试 SQLite 连接 + schema 初始化。"""
import sqlite3
import pytest
from backend.ingestion.db.connection import init_db, get_connection


def test_init_db_creates_tables(tmp_db_path):
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "documents" in tables
    assert "chunks" in tables
    assert "chunks_fts" in tables


def test_init_db_enables_wal(tmp_db_path):
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_init_db_enables_foreign_keys(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_chunks_fts_trigger_fires_on_insert(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('a.md', 'a.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'a.md', 'h1', 'v1', 'hello world', 'a.md#0',
                0, 11, 11, 0)
    """)
    conn.commit()
    fts_count = conn.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'hello'"
    ).fetchone()[0]
    assert fts_count == 1


def test_chunks_fts_trigger_fires_on_delete(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('a.md', 'a.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'a.md', 'h1', 'v1', 'hello', 'a.md#0', 0, 5, 5, 0)
    """)
    conn.execute("DELETE FROM chunks WHERE chunk_id='c1'")
    conn.commit()
    fts_count = conn.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'hello'"
    ).fetchone()[0]
    assert fts_count == 0
