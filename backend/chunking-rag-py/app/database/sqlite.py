import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
  id              TEXT PRIMARY KEY,
  original_name   TEXT NOT NULL,
  original_path   TEXT NOT NULL,
  converted_path  TEXT NOT NULL,
  format          TEXT NOT NULL,
  size            INTEGER NOT NULL,
  upload_time     TEXT NOT NULL,
  category        TEXT DEFAULT '',
  status          TEXT NOT NULL,
  tags            TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  id              TEXT PRIMARY KEY,
  file_id         TEXT NOT NULL,
  content         TEXT NOT NULL,
  start_line      INTEGER NOT NULL,
  end_line        INTEGER NOT NULL,
  original_lines  TEXT NOT NULL,
  vector          TEXT,
  FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[None]:
    """显式 BEGIN IMMEDIATE 写事务，异常回滚。autocommit (isolation_level=None) 下的唯一正确写法。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


class Db:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_file(
        self, *, id: str, original_name: str, original_path: str, converted_path: str,
        format: str, size: int, upload_time: str, status: str,
        category: str = "", tags: list[str] | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO files (id, original_name, original_path, converted_path, format, size, upload_time, category, status, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, original_name, original_path, converted_path, format, size, upload_time, category, status,
             json.dumps(tags) if tags else None),
        )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,))
        row = cur.fetchone()
        return _row_to_dict(cur, row) if row else None

    def update_file_status(self, file_id: str, status: str) -> None:
        self.conn.execute("UPDATE files SET status=? WHERE id=?", (status, file_id))

    def update_file_converted_path(self, file_id: str, path: str) -> None:
        self.conn.execute("UPDATE files SET converted_path=? WHERE id=?", (path, file_id))

    def get_files_by_name(self, original_name: str) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM files WHERE original_name=?", (original_name,))
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]

    def list_completed_files(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM files WHERE status='completed' ORDER BY upload_time DESC")
        return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        rows = []
        for c in chunks:
            rows.append((
                c.get("id") or str(uuid.uuid4()),
                c["file_id"], c["content"], c["start_line"], c["end_line"],
                json.dumps(c["original_lines"]),
                json.dumps(c["vector"]) if c.get("vector") is not None else None,
            ))
        self.conn.executemany(
            "INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_chunks_by_file(self, file_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM chunks WHERE file_id=?", (file_id,))
        return [self._chunk_from_row(cur, r) for r in cur.fetchall()]

    def get_completed_chunks(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT c.* FROM chunks c JOIN files f ON c.file_id=f.id WHERE f.status='completed'"
        )
        return [self._chunk_from_row(cur, r) for r in cur.fetchall()]

    def delete_file_and_chunks(self, file_id: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
        self.conn.execute("DELETE FROM files WHERE id=?", (file_id,))

    def get_stats(self) -> dict[str, int]:
        fc = self.conn.execute("SELECT COUNT(*) FROM files WHERE status='completed'").fetchone()[0]
        cc = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"fileCount": fc, "chunkCount": cc}

    @staticmethod
    def _chunk_from_row(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
        d = _row_to_dict(cursor, row)
        d["original_lines"] = json.loads(d["original_lines"])
        d["vector"] = json.loads(d["vector"]) if d.get("vector") else None
        return d
