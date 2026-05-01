"""启动扫描 + 每小时孤儿 chunk GC。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §10
"""
import asyncio
from pathlib import Path
from typing import Awaitable, Callable
from backend.ingestion.common.logger import get_logger
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.documents_repo import list_all_paths

DB_PATH = Path("backend/storage/index/knowledge.db")
RAW_DIR = Path("backend/storage/raw")

logger = get_logger("ingestion.gc")


def _walk_raw() -> set[str]:
    if not RAW_DIR.exists():
        return set()
    return {
        str(p.relative_to(RAW_DIR))
        for p in RAW_DIR.rglob("*")
        if p.is_file()
    }


async def initial_scan(
    on_index: Callable[[str], Awaitable],
    on_delete: Callable[[str], Awaitable],
) -> None:
    """启动时对比磁盘与 documents 表，找差异并补齐。"""
    disk = _walk_raw()
    conn = get_connection(DB_PATH)
    try:
        db_paths = set(list_all_paths(conn))
    finally:
        conn.close()

    for new_path in disk - db_paths:
        logger.info("initial_scan: index new", extra={"file_path": new_path})
        await on_index(new_path)

    for missing in db_paths - disk:
        logger.info("initial_scan: delete ghost", extra={"file_path": missing})
        await on_delete(missing)


def gc_orphan_chunks(db_path: Path = DB_PATH) -> int:
    """删 chunks 表里没有对应 document 的孤儿 chunk。返回删除数。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            DELETE FROM chunks
            WHERE file_path NOT IN (SELECT file_path FROM documents)
        """)
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.warning("gc orphan chunks", extra={"deleted": deleted})
        return deleted
    finally:
        conn.close()


async def hourly_gc_loop(on_index, on_delete, interval_seconds: int = 3600) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await initial_scan(on_index, on_delete)
            gc_orphan_chunks()
        except Exception as e:
            logger.error("hourly gc failed", extra={"error": str(e)})
