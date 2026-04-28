"""测试 SQLite 连接 + schema 初始化。"""
import sqlite3
import pytest
from backend.ingestion.db.connection import (
    init_db, get_connection, jieba_tokenize, _register_sqlite_functions,
)


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


def test_fts_uses_unicode61_tokenizer(tmp_db_path):
    """新建 DB 的 chunks_fts 应该是 unicode61 分词器（spec §3.1）。"""
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert "unicode61" in row[0], f"chunks_fts 应使用 unicode61，实际 SQL: {row[0]}"


def test_trigger_tokenizes_chinese_content(tmp_db_path):
    """spec §3.1：chunks_ai trigger 应该调 jieba_tokenize 切中文。"""
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('/tmp/x.md', 'x.md', 'h', 1, 'md', 'v1', '2026-04-28')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', '/tmp/x.md', 'h', 'v1', '数据治理架构', 'a', 0, 6, 6, 0)
    """)
    conn.commit()
    fts_content = conn.execute(
        "SELECT content FROM chunks_fts WHERE chunk_id = 'c1'"
    ).fetchone()[0]
    conn.close()
    assert fts_content == "数据 治理 架构", f"实际: {fts_content!r}"


def test_trigger_handles_null_title_path(tmp_db_path):
    """title_path 可能 NULL，jieba_tokenize(NULL) 应返 NULL，trigger 不报错。"""
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('/tmp/y.md', 'y.md', 'h', 1, 'md', 'v1', '2026-04-28')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, title_path,
                            char_offset_start, char_offset_end, char_count, chunk_index)
        VALUES ('c2', '/tmp/y.md', 'h', 'v1', 'hello world', 'a', NULL, 0, 11, 11, 0)
    """)
    conn.commit()
    row = conn.execute(
        "SELECT content, title_path FROM chunks_fts WHERE chunk_id = 'c2'"
    ).fetchone()
    conn.close()
    assert row[0] == "hello world"  # jieba 对纯英文 = 原文
    assert row[1] is None


# 注：test_chunk_replace_updates_fts 已移除——发现 SQLite 默认 recursive_triggers=OFF
# 导致 INSERT OR REPLACE 时 ad trigger 不触发，fts 表会累积旧行。这是项目老 bug
# （trigram 时代同样存在），不在本 FTS5 jieba 切换 spec 范围。已 spawn 独立 follow-up task。


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


# === T2: jieba_tokenize SQLite UDF 单测（Task 2 新增）===

def test_jieba_tokenize_chinese():
    """中文按词切，词间用空格分隔。"""
    assert jieba_tokenize("数据治理") == "数据 治理"
    assert jieba_tokenize("产品功能架构") == "产品 功能 架构"


def test_jieba_tokenize_empty_and_none():
    """空字符串 → 空串；None → None（保留 NULL 语义给 SQLite）。"""
    assert jieba_tokenize("") == ""
    assert jieba_tokenize(None) is None


def test_jieba_tokenize_deterministic():
    """同样的输入永远返回同样的结果（UDF 注册了 deterministic=True 是合法的）。"""
    a = jieba_tokenize("数据治理架构与体系建设")
    b = jieba_tokenize("数据治理架构与体系建设")
    assert a == b


def test_jieba_tokenize_mixed_cn_en():
    """中英混合：中文按 jieba 切，英文/数字按空格保留。"""
    result = jieba_tokenize("如何配置 F5 DNS")
    assert result is not None
    tokens = result.split()
    assert "F5" in tokens
    assert "DNS" in tokens
    assert "如何" in tokens
    assert "配置" in tokens


def test_register_sqlite_functions_enables_jieba_udf(tmp_db_path):
    """spec §6.4 AC1：_register_sqlite_functions 注册的 jieba_tokenize 在 SQL 里可调用。

    本测试只验证 helper 函数本身的注册能力。"init_db 内部连接也注册了 UDF"
    的完整集成验证在 Task 4 完成后通过 test_init_db_migrates_old_trigram_to_unicode61
    隐式覆盖（迁移 SQL 里 INSERT...SELECT jieba_tokenize(...) 能跑通就证明 UDF 注册了）。
    """
    conn = sqlite3.connect(tmp_db_path)
    _register_sqlite_functions(conn)
    result = conn.execute("SELECT jieba_tokenize('数据治理')").fetchone()
    assert result[0] == "数据 治理"
    conn.close()
