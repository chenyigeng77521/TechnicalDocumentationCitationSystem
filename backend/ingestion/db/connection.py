"""SQLite 连接 + WAL + 初始化建表 + FTS 分词器迁移。"""
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path("backend/storage/index/knowledge.db")

# 当前 schema 期望的 FTS 分词器（同 schema.sql 里的 tokenize 设置）
EXPECTED_FTS_TOKENIZER = "trigram"


def _fts_needs_migration(conn: sqlite3.Connection) -> bool:
    """检查 chunks_fts 表的 tokenize 是不是 EXPECTED_FTS_TOKENIZER。

    返回 True 表示需要迁移（DROP + 重建）。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    if row is None:
        return False  # 表都不存在，让 schema.sql 正常建即可
    create_sql = row[0] or ""
    # SQLite 把 tokenize 配置原样存在 sql 字段里
    return f"tokenize = '{EXPECTED_FTS_TOKENIZER}'" not in create_sql \
        and f"tokenize='{EXPECTED_FTS_TOKENIZER}'" not in create_sql


def _migrate_fts_tokenizer(conn: sqlite3.Connection) -> None:
    """DROP 旧 chunks_fts → 用新 tokenize 重建 → 从 chunks 表重新填数据。

    DROP TABLE 会级联删触发器，所以重建后必须把 chunks_ai/ad/au 也建回来。
    """
    conn.executescript("""
        DROP TABLE IF EXISTS chunks_fts;

        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED,
            content,
            title_path,
            tokenize = 'trigram'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(chunk_id, content, title_path)
            VALUES (new.chunk_id, new.content, new.title_path);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
            INSERT INTO chunks_fts(chunk_id, content, title_path)
            VALUES (new.chunk_id, new.content, new.title_path);
        END;
    """)
    # 从 chunks 表重新灌进新的 fts 索引
    conn.execute("""
        INSERT INTO chunks_fts(chunk_id, content, title_path)
        SELECT chunk_id, content, title_path FROM chunks
    """)
    conn.commit()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库（建表 / 启用 WAL）+ 必要时迁移 FTS 分词器。幂等。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        # 第一遍：CREATE IF NOT EXISTS 把缺的表/触发器建起来
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()

        # 第二遍：检查 chunks_fts 分词器是不是当前 schema 期望的
        # 如果不是（旧 DB 用 unicode61），自动迁移到 trigram
        if _fts_needs_migration(conn):
            _migrate_fts_tokenizer(conn)
    finally:
        conn.close()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
