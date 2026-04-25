"""index_pipeline：路径 A 和路径 B 共用入口。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §5
"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from backend.ingestion.common.embedding import batch_embed
from backend.ingestion.common.errors import (
    ParseError, EmbeddingError, DBError,
)
from backend.ingestion.common.logger import get_logger
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import (
    upsert_document, get_document, update_status, delete_document,
)
from backend.ingestion.db.chunks_repo import (
    insert_chunks, delete_chunks_by_file,
)
from backend.ingestion.parser.dispatcher import parse_document
from backend.ingestion.chunker.document_splitter import split_document
from backend.ingestion.sync.file_lock import file_lock

DB_PATH = Path("backend/storage/index/knowledge.db")
RAW_DIR = Path("backend/storage/raw")
INDEX_VERSION = "v1"   # MVP 固定
LOG_FILE = Path("backend/ingestion/logs/ingestion.log")

logger = get_logger("ingestion.pipeline", log_file=LOG_FILE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_under_raw(file_path: str) -> Path:
    """把相对 file_path 解析成绝对路径，并校验不逃逸 RAW_DIR。"""
    base = RAW_DIR.resolve()
    abs_path = (base / file_path).resolve()
    if not str(abs_path).startswith(str(base)):
        raise ValueError(f"file_path 逃逸 RAW_DIR: {file_path}")
    return abs_path


async def index_pipeline(file_path: str) -> dict:
    """主流程：解析 → 切 chunk → embed → 写 DB。"""
    abs_path = _resolve_under_raw(file_path)
    if not abs_path.exists():
        raise FileNotFoundError(file_path)

    init_db(DB_PATH)

    async with file_lock(file_path):
        new_hash = _sha256_of_file(abs_path)

        conn = get_connection(DB_PATH)
        try:
            old_doc = get_document(conn, file_path)
            if old_doc and old_doc["file_hash"] == new_hash:
                logger.info("unchanged", extra={"file_path": file_path})
                return {"status": "unchanged"}

            upsert_document(
                conn,
                file_path=file_path,
                file_name=abs_path.name,
                file_hash=new_hash,
                file_size=abs_path.stat().st_size,
                format=abs_path.suffix.lstrip("."),
                index_version=INDEX_VERSION,
                last_modified=_utcnow(),
                index_status="pending",
            )

            try:
                parse_result = await parse_document(abs_path)
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"解析失败: {e}")
                raise ParseError(str(e))

            chunks = split_document(
                parse_result,
                file_path=file_path,
                file_hash=new_hash,
                index_version=INDEX_VERSION,
            )

            try:
                embeddings = await batch_embed([c.content for c in chunks])
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"embedding 失败: {e}")
                raise EmbeddingError(str(e))

            for c, emb in zip(chunks, embeddings):
                c.embedding = emb

            try:
                delete_chunks_by_file(conn, file_path)
                insert_chunks(conn, [c.to_dict() for c in chunks])
                update_status(
                    conn, file_path,
                    index_status="indexed",
                    chunk_count=len(chunks),
                    indexed_at=_utcnow(),
                )
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"DB 写入失败: {e}")
                raise DBError(str(e))

            logger.info("indexed", extra={
                "file_path": file_path, "chunks": len(chunks),
            })
            return {
                "status": "indexed",
                "chunk_count": len(chunks),
                "file_hash": new_hash,
            }
        finally:
            conn.close()


async def handle_file_delete(file_path: str) -> dict:
    """删文件时同步删 documents（CASCADE 删 chunks）。"""
    init_db(DB_PATH)
    async with file_lock(file_path):
        conn = get_connection(DB_PATH)
        try:
            doc = get_document(conn, file_path)
            if doc is None:
                return {"status": "not_found"}
            chunk_count = doc["chunk_count"]
            delete_document(conn, file_path)
            logger.info("deleted", extra={"file_path": file_path})
            return {"status": "deleted", "deleted_chunks": chunk_count}
        finally:
            conn.close()
