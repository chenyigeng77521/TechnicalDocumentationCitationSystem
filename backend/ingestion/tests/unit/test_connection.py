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


def test_fts_uses_trigram_tokenizer(tmp_db_path):
    """新建 DB 的 chunks_fts 应该是 trigram 分词器。"""
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    assert row is not None
    assert "trigram" in row[0], f"chunks_fts 应使用 trigram 分词器，实际 SQL: {row[0]}"


def test_fts_can_match_chinese_substring(tmp_db_path):
    """trigram 分词器应能搜到中文子串（unicode61 做不到）。

    注意：trigram 要求 query 至少 3 字符（按 3-gram 切词），
    所以这里用 '你好世界' (4 字)，不是 '你好' (2 字会失败)。
    """
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('cn.md', 'cn.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'cn.md', 'h1', 'v1',
                '中文测试：你好世界', 'cn.md#0', 0, 9, 9, 0)
    """)
    conn.commit()
    rows = conn.execute(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH '你好世界'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 'c1'


def test_init_db_migrates_old_unicode61_to_trigram(tmp_db_path):
    """老 DB 用 unicode61，启动 init_db 应自动迁移到 trigram，且数据保留。"""
    # 1. 手工建一个老 schema 的 DB（unicode61 分词器 + 灌一些中文数据）
    conn = sqlite3.connect(tmp_db_path)
    conn.executescript("""
        CREATE TABLE documents (
            file_path TEXT PRIMARY KEY, file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL, file_size INTEGER NOT NULL,
            format TEXT NOT NULL, language TEXT,
            index_version TEXT NOT NULL,
            index_status TEXT DEFAULT 'pending',
            error_detail TEXT, chunk_count INTEGER DEFAULT 0,
            last_modified TIMESTAMP NOT NULL,
            indexed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL, index_version TEXT NOT NULL,
            content TEXT NOT NULL, anchor_id TEXT NOT NULL,
            title_path TEXT,
            char_offset_start INTEGER NOT NULL, char_offset_end INTEGER NOT NULL,
            char_count INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
            is_truncated INTEGER DEFAULT 0,
            content_type TEXT NOT NULL DEFAULT 'document',
            language TEXT, embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_path) REFERENCES documents(file_path) ON DELETE CASCADE
        );
        -- 老 schema：unicode61
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED, content, title_path,
            tokenize = 'unicode61 remove_diacritics 2'
        );
    """)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('cn.md', 'cn.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'cn.md', 'h1', 'v1',
                '中文测试：你好世界', 'cn.md#0', 0, 9, 9, 0)
    """)
    conn.commit()
    conn.close()

    # 2. 调 init_db 应自动迁移（不是抛异常 / 数据丢失）
    init_db(tmp_db_path)

    # 3. 验证：chunks_fts 现在用 trigram，且能搜到中文子串
    conn = get_connection(tmp_db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    assert "trigram" in row[0], "迁移后 chunks_fts 应用 trigram 分词器"

    rows = conn.execute(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH '你好世界'"
    ).fetchall()
    assert len(rows) == 1, "迁移后应能搜到中文子串（≥3 字符 query）"
    assert rows[0][0] == 'c1'

    # 4. 原 chunks 表数据不应丢失
    chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert chunk_count == 1
    conn.close()
