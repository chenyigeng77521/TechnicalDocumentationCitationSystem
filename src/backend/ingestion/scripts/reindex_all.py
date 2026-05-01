"""全量 re-index 所有已索引文件。

读 documents 表的 file_path，**清空 documents + chunks**，然后逐文件调
index_pipeline 触发 parser → chunker → embed → DB 重建。

为什么要清空：index_pipeline 有 'unchanged' 优化（按 file_hash 比对），但
chunker 代码改了之后，源文件 hash 没变 → 所有文件都会被跳过。所以必须
先清掉旧数据强制全部重跑。

用法:
  cd /path/to/TechnicalDocumentationCitationSystem
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all

  # 单文件测试（不清表，只重建一个）
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all --only api-eviction.md

  # 不清表（仅适用于 file 内容变了的常规 reindex，本场景不该用）
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all --no-truncate
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.sync.pipeline import index_pipeline, DB_PATH, RAW_DIR


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只 reindex 一个文件名（basename 匹配）")
    parser.add_argument("--no-truncate", action="store_true", help="不清空 documents/chunks 表（不推荐：chunker 改后旧 hash 会让 unchanged 跳过）")
    args = parser.parse_args()

    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    rows = conn.execute(
        "SELECT file_path FROM documents ORDER BY file_path"
    ).fetchall()

    if not args.only and not args.no_truncate:
        # 清空 chunks + documents（CASCADE 由 schema 中的 FK 处理 chunks）
        old_chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        old_docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        print(f"清空旧数据: {old_docs} documents / {old_chunks} chunks")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM chunks_fts")
        conn.execute("DELETE FROM documents")
        conn.commit()

    conn.close()

    file_paths = [r[0] for r in rows]
    base = RAW_DIR.resolve()

    # documents.file_path 历史上是绝对路径，新版应该是相对——两种都要兼容
    relatives = []
    for fp in file_paths:
        p = Path(fp)
        if p.is_absolute():
            try:
                rel = str(p.relative_to(base))
            except ValueError:
                print(f"  SKIP (路径在 RAW_DIR 外): {fp}", file=sys.stderr)
                continue
        else:
            rel = fp
        relatives.append(rel)

    if args.only:
        relatives = [r for r in relatives if Path(r).name == args.only]
        if not relatives:
            print(f"未找到匹配 --only={args.only} 的文件", file=sys.stderr)
            sys.exit(1)

    print(f"Re-indexing {len(relatives)} files...")
    t_start = time.time()
    failed = []
    indexed = 0
    unchanged = 0
    for i, rel in enumerate(relatives, 1):
        t0 = time.time()
        try:
            result = await index_pipeline(rel)
            elapsed = time.time() - t0
            status = result.get("status", "?")
            if status == "indexed":
                indexed += 1
            elif status == "unchanged":
                unchanged += 1
            print(f"  [{i:3d}/{len(relatives)}] {elapsed:5.1f}s  {status:10s}  {rel}")
        except Exception as e:
            print(f"  [{i:3d}/{len(relatives)}] FAILED: {type(e).__name__}: {e}  {rel}", file=sys.stderr)
            failed.append((rel, str(e)))

    total_elapsed = time.time() - t_start
    print(f"\nDone in {total_elapsed/60:.1f}min. {indexed} indexed, {unchanged} unchanged, {len(failed)} failed")
    if failed:
        for rel, err in failed:
            print(f"  FAIL: {rel}: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
