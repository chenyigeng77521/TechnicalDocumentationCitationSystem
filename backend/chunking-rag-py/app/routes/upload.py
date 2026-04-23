import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import Settings
from app.converter.chunker import chunk_markdown
from app.converter.parser import parse
from app.database.sqlite import Db, write_tx
from app.deps import get_db, get_embedder, get_settings
from app.embedder.bge_m3 import BgeM3Embedder
from app.filename_utils import dedupe_and_open, fix_encoding, sanitize_filename

router = APIRouter()

MAX_FILES = 10
MAX_BYTES = 50 * 1024 * 1024
READ_CHUNK = 64 * 1024
SUPPORTED_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md"}


@router.post("/upload")
def upload(
    files: list[UploadFile] = File(...),
    db: Db = Depends(get_db),
    embedder: BgeM3Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"最多 {MAX_FILES} 个文件")

    raw_dir = settings.resolve_path(settings.raw_dir)
    converted_dir = settings.resolve_path(settings.converted_dir)
    mappings_dir = settings.resolve_path(settings.mappings_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    converted_dir.mkdir(parents=True, exist_ok=True)
    mappings_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    for up in files:
        safe_name = sanitize_filename(fix_encoding(up.filename or "unnamed"))
        ext = Path(safe_name).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            results.append({
                "id": str(uuid.uuid4()),
                "originalName": safe_name,
                "status": "failed",
                "error": f"unsupported format: {ext}",
            })
            continue

        raw_path, fd = dedupe_and_open(raw_dir, safe_name)
        written = 0
        size_exceeded = False
        try:
            while True:
                chunk = up.file.read(READ_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_BYTES:
                    size_exceeded = True
                    break
                os.write(fd, chunk)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        if size_exceeded:
            try:
                os.unlink(raw_path)
            except OSError:
                pass
            raise HTTPException(status_code=413, detail=f"{safe_name} 超过 50MB")

        disk_name = raw_path.name
        file_id = str(uuid.uuid4())
        upload_time = datetime.now(timezone.utc).isoformat()

        db.insert_file(
            id=file_id, original_name=disk_name, original_path=str(raw_path),
            converted_path="", format=ext.lstrip("."), size=written,
            upload_time=upload_time, status="converting",
        )

        try:
            md, line_map = parse(raw_path)
            converted_path = converted_dir / f"{file_id}.md"
            converted_path.write_text(md, encoding="utf-8")
            (mappings_dir / f"{file_id}.json").write_text("{}", encoding="utf-8")
            db.update_file_converted_path(file_id, str(converted_path))

            chunks = chunk_markdown(md, line_map)
            if chunks:
                vectors = embedder.encode([c.content for c in chunks])
                chunk_rows = [
                    {
                        "id": str(uuid.uuid4()), "file_id": file_id,
                        "content": c.content, "start_line": c.start_line, "end_line": c.end_line,
                        "original_lines": c.original_lines, "vector": vectors[i].tolist(),
                    }
                    for i, c in enumerate(chunks)
                ]
                with write_tx(db.conn):
                    db.insert_chunks(chunk_rows)
                    db.update_file_status(file_id, "completed")
            else:
                db.update_file_status(file_id, "completed")

            results.append({
                "id": file_id, "originalName": disk_name, "format": ext.lstrip("."),
                "size": written, "status": "completed", "uploadTime": upload_time,
            })
        except Exception as e:  # noqa: BLE001
            try:
                db.update_file_status(file_id, "failed")
            except Exception:  # noqa: BLE001
                pass
            results.append({
                "id": file_id, "originalName": disk_name, "format": ext.lstrip("."),
                "size": written, "status": "failed", "error": str(e),
            })

    success = sum(1 for r in results if r["status"] == "completed")
    return {
        "success": True,
        "files": results,
        "message": f"成功处理 {success} / {len(files)} 个文件",
    }


@router.get("/upload/raw-files")
def list_raw_files(
    page: int = 1, limit: int = 10,
    settings: Settings = Depends(get_settings),
):
    page = max(1, page)
    limit = max(1, min(100, limit))
    raw_dir = settings.resolve_path(settings.raw_dir)
    if not raw_dir.exists():
        return {"success": True, "files": [], "total": 0, "page": page, "limit": limit, "totalPages": 0}
    entries = [p for p in raw_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total = len(entries)
    start = (page - 1) * limit
    end = start + limit
    page_entries = entries[start:end]
    return {
        "success": True,
        "files": [
            {
                "name": p.name, "path": str(p),
                "size": p.stat().st_size,
                "createdAt": datetime.fromtimestamp(p.stat().st_ctime, tz=timezone.utc).isoformat(),
                "modifiedAt": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            for p in page_entries
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "totalPages": math.ceil(total / limit) if total else 0,
    }
