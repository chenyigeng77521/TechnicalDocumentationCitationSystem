"""documents 表 CRUD。"""
import sqlite3
from datetime import datetime
from typing import Optional


def upsert_document(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    file_name: str,
    file_hash: str,
    file_size: int,
    format: str,
    index_version: str,
    last_modified: datetime,
    language: Optional[str] = None,
    index_status: str = "pending",
    error_detail: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO documents (
            file_path, file_name, file_hash, file_size, format, language,
            index_version, index_status, error_detail, last_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            file_hash = excluded.file_hash,
            file_size = excluded.file_size,
            format = excluded.format,
            language = excluded.language,
            index_version = excluded.index_version,
            index_status = excluded.index_status,
            error_detail = excluded.error_detail,
            last_modified = excluded.last_modified
        """,
        (file_path, file_name, file_hash, file_size, format, language,
         index_version, index_status, error_detail, last_modified),
    )
    conn.commit()


def get_document(conn: sqlite3.Connection, file_path: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM documents WHERE file_path = ?", (file_path,)
    ).fetchone()


def update_status(
    conn: sqlite3.Connection,
    file_path: str,
    *,
    index_status: str,
    chunk_count: Optional[int] = None,
    indexed_at: Optional[datetime] = None,
    error_detail: Optional[str] = None,
) -> None:
    fields = ["index_status = ?"]
    values: list = [index_status]
    if chunk_count is not None:
        fields.append("chunk_count = ?")
        values.append(chunk_count)
    if indexed_at is not None:
        fields.append("indexed_at = ?")
        values.append(indexed_at)
    if error_detail is not None:
        fields.append("error_detail = ?")
        values.append(error_detail)
    values.append(file_path)
    conn.execute(
        f"UPDATE documents SET {', '.join(fields)} WHERE file_path = ?",
        values,
    )
    conn.commit()


def delete_document(conn: sqlite3.Connection, file_path: str) -> None:
    conn.execute("DELETE FROM documents WHERE file_path = ?", (file_path,))
    conn.commit()


def list_all_paths(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT file_path FROM documents").fetchall()
    return [r["file_path"] for r in rows]


def count_documents(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM documents").fetchone()[0]
