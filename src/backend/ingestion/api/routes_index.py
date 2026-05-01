"""写入侧路由：POST /index, DELETE /files, GET /stats, /health。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §4.1
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.ingestion.common.errors import (
    IngestionError, ParseError, EmbeddingError, DBError,
    UnsupportedFormatError,
)
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import count_documents
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import (
    index_pipeline, handle_file_delete, DB_PATH,
)

router = APIRouter()


class IndexRequest(BaseModel):
    file_path: str


class DeleteRequest(BaseModel):
    file_path: str


@router.post("/index")
async def post_index(req: IndexRequest):
    try:
        result = await index_pipeline(req.file_path)
        return result
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "error_type": "file_not_found",
                    "detail": req.file_path},
        )
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except ParseError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except (EmbeddingError, DBError) as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except IngestionError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.delete("/files")
async def delete_files(req: DeleteRequest):
    return await handle_file_delete(req.file_path)


@router.get("/stats")
async def get_stats():
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        size_mb = (DB_PATH.stat().st_size / 1024 / 1024) if DB_PATH.exists() else 0
        return {
            "documents": count_documents(conn),
            "chunks": count_chunks(conn),
            "index_size_mb": round(size_mb, 2),
        }
    finally:
        conn.close()


@router.get("/health")
async def get_health():
    init_db(DB_PATH)
    return {
        "status": "ok",
        "db_writable": DB_PATH.exists(),
        "embedding_model_loaded": False,
    }
