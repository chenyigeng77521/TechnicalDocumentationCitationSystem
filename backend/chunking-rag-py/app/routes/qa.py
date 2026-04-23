import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings
from app.database.sqlite import Db, write_tx
from app.deps import get_db, get_settings

router = APIRouter()


@router.get("/api/qa/files")
def list_files(db: Db = Depends(get_db), settings: Settings = Depends(get_settings)):
    raw_dir = settings.resolve_path(settings.raw_dir)
    files = db.list_completed_files()
    out = []
    for f in files:
        rp = raw_dir / f["original_name"]
        try:
            st = rp.stat()
            size = st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        except FileNotFoundError:
            size = f["size"]
            mtime = f["upload_time"]
        out.append({
            "name": f["original_name"], "size": size, "mtime": mtime,
            "id": f["id"], "format": f["format"],
            "uploadTime": f["upload_time"], "category": f.get("category") or "",
        })
    return {"success": True, "files": out, "total": len(out)}


@router.get("/api/qa/stats")
def stats(db: Db = Depends(get_db)):
    s = db.get_stats()
    return {
        "success": True,
        "totalFiles": s["fileCount"],
        "stats": {
            "fileCount": s["fileCount"],
            "chunkCount": s["chunkCount"],
            "indexedCount": s["chunkCount"],
        },
    }


@router.delete("/api/qa/files/{filename}")
def delete_file(
    filename: str,
    db: Db = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    raw_dir = settings.resolve_path(settings.raw_dir)
    converted_dir = settings.resolve_path(settings.converted_dir)
    mappings_dir = settings.resolve_path(settings.mappings_dir)

    safe = (raw_dir / filename).resolve()
    if not str(safe).startswith(str(raw_dir.resolve()) + os.sep):
        raise HTTPException(status_code=400, detail="invalid filename")

    matches = db.get_files_by_name(filename)
    if not matches and not safe.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    if matches:
        with write_tx(db.conn):
            for row in matches:
                db.delete_file_and_chunks(row["id"])

    if safe.exists():
        try:
            safe.unlink()
        except OSError:
            pass

    for row in matches:
        for p in (converted_dir / f"{row['id']}.md", mappings_dir / f"{row['id']}.json"):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    return {"success": True, "message": "文件已删除"}
