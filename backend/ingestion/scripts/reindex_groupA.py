"""ad-hoc reindex: 重新切块 + 写新 markdown_anchor，content 不变的复用旧 embedding。

目的：组 A 改造后，让 chunks 表的 markdown_anchor 字段填上、HTML 注释段被剥离。
不重新跑 bge-m3 embedding（节约 1-3 小时）——用 content hash 匹配旧 embedding。
新切出来的（content 变化的）chunks embedding 暂留 None，可后续单独补。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT = Path('/Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem')
sys.path.insert(0, str(PROJECT))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, delete_chunks_by_file
from backend.ingestion.parser.dispatcher import parse_document
from backend.ingestion.chunker.document_splitter import split_document

DB = Path('backend/storage/index/knowledge.db')


async def reindex_one(conn, file_path: str, file_hash: str, index_version: str) -> dict:
    """对一个 document：拉旧 chunks → 解析切块 → 按 content 复用 embedding → 删旧插新。"""
    abs_path = PROJECT / file_path
    if not abs_path.exists():
        return {'status': 'skip_missing', 'file': file_path}

    # 1. 拉旧 chunks
    old_rows = conn.execute(
        "SELECT chunk_id, content, embedding FROM chunks WHERE file_path = ?",
        (file_path,)
    ).fetchall()
    old_emb_by_content = {}
    for r in old_rows:
        if r['embedding']:
            old_emb_by_content[r['content']] = r['embedding']  # 留 JSON 字符串

    # 2. 解析（含 anchor + comment_ranges）
    try:
        parse_result = await parse_document(abs_path)
    except Exception as e:
        return {'status': 'parse_error', 'file': file_path, 'err': str(e)}

    # 3. 切块（含 markdown_anchor 绑定 + 注释剥离）
    new_chunks = split_document(
        parse_result,
        file_path=file_path,
        file_hash=file_hash,
        index_version=index_version,
    )

    # 4. 对每个新 chunk 按 content 找旧 embedding
    reused = 0
    new_dicts = []
    for c in new_chunks:
        d = c.to_dict()
        emb_json = old_emb_by_content.get(c.content)
        if emb_json:
            d['embedding'] = json.loads(emb_json)
            reused += 1
        else:
            d['embedding'] = None  # 待后续补
        new_dicts.append(d)

    # 5. 删旧插新
    delete_chunks_by_file(conn, file_path)
    insert_chunks(conn, new_dicts)

    return {
        'status': 'ok',
        'file': abs_path.name,
        'old_chunks': len(old_rows),
        'new_chunks': len(new_chunks),
        'reused_embeddings': reused,
    }


async def main():
    init_db(DB)
    conn = get_connection(DB)
    docs = conn.execute(
        "SELECT file_path, file_hash, index_version FROM documents"
    ).fetchall()
    print(f'要重索引 {len(docs)} 个文档\n')

    t0 = time.time()
    stats = {'ok': 0, 'skip_missing': 0, 'parse_error': 0,
             'old_total': 0, 'new_total': 0, 'reused_total': 0}
    parse_errors = []

    for i, d in enumerate(docs, 1):
        result = await reindex_one(conn, d['file_path'], d['file_hash'], d['index_version'])
        stats[result['status']] = stats.get(result['status'], 0) + 1
        if result['status'] == 'ok':
            stats['old_total'] += result['old_chunks']
            stats['new_total'] += result['new_chunks']
            stats['reused_total'] += result['reused_embeddings']
            if i % 20 == 0 or i == len(docs):
                elapsed = time.time() - t0
                print(f'  [{i}/{len(docs)}] elapsed={elapsed:.0f}s  '
                      f'last={result["file"]}: {result["old_chunks"]}→{result["new_chunks"]} '
                      f'(reused {result["reused_embeddings"]} emb)')
        elif result['status'] == 'parse_error':
            parse_errors.append(result)
            print(f'  ❌ {d["file_path"]}: {result["err"][:80]}')

    elapsed = time.time() - t0
    print(f'\n总耗时 {elapsed:.0f}s')
    print(f'成功: {stats["ok"]} 文档')
    print(f'丢失文件: {stats["skip_missing"]}')
    print(f'解析错: {stats["parse_error"]}')
    print(f'chunks: 旧 {stats["old_total"]} → 新 {stats["new_total"]} (差 {stats["old_total"] - stats["new_total"]})')
    print(f'embedding 复用: {stats["reused_total"]}/{stats["new_total"]} ({stats["reused_total"]*100//max(stats["new_total"],1)}%)')

    conn.close()


if __name__ == '__main__':
    asyncio.run(main())
