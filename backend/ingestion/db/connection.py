"""SQLite 连接 + WAL + 初始化建表 + FTS 分词器迁移。"""
import sqlite3
from pathlib import Path

import jieba

# 模块加载时关掉 jieba 启动 log + 预热，避免首次 INSERT 卡顿（约 0.4-0.6s）
jieba.setLogLevel(60)
jieba.initialize()

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path("backend/storage/index/knowledge.db")

# 当前 schema 期望的 FTS 分词器（同 schema.sql 里的 tokenize 设置）
EXPECTED_FTS_TOKENIZER = "unicode61 remove_diacritics 2"


def jieba_tokenize(text: str | None) -> str | None:
    """SQLite UDF：把中文用 jieba 切词后用空格拼接，给 unicode61 tokenize。

    规则：
    - None → None（保留 SQL NULL 语义）
    - 空字符串 → 空字符串
    - 其他 → jieba.cut（精确模式）后空格拼接，过滤纯空白 token
    """
    if text is None:
        return None
    return ' '.join(t for t in jieba.cut(text) if t.strip())


def _register_sqlite_functions(conn: sqlite3.Connection) -> None:
    """注册自定义 SQLite UDF。

    spec §6.4 AC1：所有可能执行 chunks 写入（trigger 调 jieba_tokenize）
    或 FTS 迁移（_migrate_fts_tokenizer 里 INSERT...SELECT jieba_tokenize(...)）
    的连接，必须先调用此函数。
    """
    conn.create_function('jieba_tokenize', 1, jieba_tokenize, deterministic=True)


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
    """DROP 旧 chunks_fts → 用 unicode61 重建 → 重建 3 个 trigger → jieba 重填。

    spec §6.4 AC2：DROP TABLE 会级联删 chunks_ai/ad/au 三个 trigger
    （现有 connection.py 老注释明写此约束），所以重建 FTS 表后必须把
    trigger 也建回来，否则后续 INSERT/UPDATE/DELETE 不再同步到 chunks_fts。

    重建的 trigger 必须用 jieba_tokenize（跟 schema.sql 当前版本一致）。
    `CREATE TRIGGER IF NOT EXISTS` 在迁移场景下安全，因为 DROP TABLE 已经
    把 trigger 拿掉，IF NOT EXISTS 实际等价于 CREATE。

    前置条件：conn 必须先调 _register_sqlite_functions(conn)，否则
    INSERT...SELECT jieba_tokenize(...) 会报 'no such function'。
    init_db() 已在调用此函数前注册 UDF。

    spec §6.1 R4：迁移不是原子事务（executescript 自动 commit），
    失败需手动 DROP chunks_fts 让下次启动重建。
    """
    conn.executescript("""
        DROP TABLE IF EXISTS chunks_fts;

        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED,
            content,
            title_path,
            tokenize = 'unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(chunk_id, content, title_path)
            VALUES (new.chunk_id,
                    jieba_tokenize(new.content),
                    jieba_tokenize(new.title_path));
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
            INSERT INTO chunks_fts(chunk_id, content, title_path)
            VALUES (new.chunk_id,
                    jieba_tokenize(new.content),
                    jieba_tokenize(new.title_path));
        END;
    """)
    # 一句 SQL 把全部 chunks 走 jieba_tokenize 重新写进 fts
    conn.execute("""
        INSERT INTO chunks_fts(chunk_id, content, title_path)
        SELECT chunk_id, jieba_tokenize(content), jieba_tokenize(title_path)
        FROM chunks
    """)
    conn.commit()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库（建表 / 启用 WAL）+ 必要时迁移 FTS 分词器。幂等。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _register_sqlite_functions(conn)  # spec §6.4 AC1：迁移路径必须先注册 UDF
    try:
        # 第一遍：CREATE IF NOT EXISTS 把缺的表/触发器建起来
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()

        # 第二遍：检查 chunks_fts 分词器是不是当前 schema 期望的
        if _fts_needs_migration(conn):
            _migrate_fts_tokenizer(conn)
    finally:
        conn.close()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    _register_sqlite_functions(conn)  # spec §6.4 AC1：业务连接也要注册 UDF
    return conn
