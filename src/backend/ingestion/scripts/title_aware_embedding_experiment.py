"""title-aware embedding 受控实验。

目的：验证"把 title_path 拼到 chunk content 前再 embed"是否真改善检索质量，
重点看陷阱题（虚构字段 query）是否变糟。

关键约束：**不动主 DB**——读取主 DB 中 3 个文件的 chunks，重算 embedding 写到临时 DB。

用法:
  cd /path/to/TechnicalDocumentationCitationSystem
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.title_aware_embedding_experiment
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, vector_search

TEST_FILES = [
    "api-eviction.md",
    "incremental-adoption.md",
    "databuffer-codec.adoc",
]

QUERIES = [
    ("Q1 K8s 6步", "Pod 被 API 驱逐时是怎么一步步删除的"),
    ("Q2 React 真", "React Compiler 的增量采用是什么意思"),
    ("Q3 Spring 真", "DataBufferFactory 是用来做什么的"),
    ("Q4 SSH Secret", "Kubernetes 中用于存放 SSH 身份认证凭据的内置 Secret 类型是什么"),
    ("Q5 K8s trap", "如何在 Deployment 的 YAML 中配置 backupPolicy 字段来自动备份 Pod 数据"),
    ("Q6 React trap", "如何在 React 组件中配置 mitochondria 属性来管理状态"),
    ("Q7 Spring trap", "Spring Boot 中如何使用 quantumCache 注解来缓存 Service 方法的返回值"),
]


def fetch_chunks_from_main_db(file_basenames):
    main = sqlite3.connect("backend/storage/index/knowledge.db")
    main.row_factory = sqlite3.Row
    cur = main.cursor()
    chunks = []
    for basename in file_basenames:
        cur.execute(
            "SELECT * FROM chunks WHERE file_path LIKE ? ORDER BY chunk_index",
            (f"%{basename}",),
        )
        chunks.extend([dict(r) for r in cur.fetchall()])
    main.close()
    return chunks


def build_temp_db(chunks, embed_fn, db_path):
    if Path(db_path).exists():
        Path(db_path).unlink()
    init_db(Path(db_path))
    conn = get_connection(Path(db_path))

    file_paths = set(c["file_path"] for c in chunks)
    for fp in file_paths:
        conn.execute(
            """INSERT OR IGNORE INTO documents
               (file_path, file_name, file_hash, file_size, format,
                index_version, last_modified, indexed_at, index_status, chunk_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp, Path(fp).name, "h", 0, "md", "v1",
             "2026-04-30", "2026-04-30", "indexed", 0),
        )

    new_chunks = []
    for c in chunks:
        c_dict = dict(c)
        text_to_embed = embed_fn(c_dict)
        emb = model.encode(text_to_embed, normalize_embeddings=True).tolist()
        c_dict["embedding"] = emb
        new_chunks.append(c_dict)

    insert_chunks(conn, new_chunks)
    conn.commit()
    return conn


def variant_a(c):
    """A 版：只 embed content（原版）。"""
    return c["content"]


def variant_b(c):
    """B 版：拼 title_path + content。"""
    if c.get("title_path"):
        return f"{c['title_path']}\n\n{c['content']}"
    return c["content"]


def run_query(conn, query):
    q_emb = model.encode(query, normalize_embeddings=True).tolist()
    return vector_search(conn, q_emb, top_k=10)


def fmt_chunk(r, idx):
    return (
        f"    {idx}  {r['score']:.4f}  "
        f"{Path(r['file_path']).name:33s}  "
        f"{(r.get('title_path') or '<no-title>')[:40]:40s}  "
        f"{(r['content'] or '')[:50]!r}"
    )


if __name__ == "__main__":
    print("Loading bge-m3...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")
    print(f"loaded in {time.time() - t0:.1f}s")

    chunks = fetch_chunks_from_main_db(TEST_FILES)
    print(f"Got {len(chunks)} chunks across {len(TEST_FILES)} test files")

    print("\n=== Building variant A (content-only) ===")
    t0 = time.time()
    conn_a = build_temp_db(chunks, variant_a, "/tmp/exp_variant_a.db")
    print(f"  {time.time() - t0:.1f}s")

    print("=== Building variant B (title + content) ===")
    t0 = time.time()
    conn_b = build_temp_db(chunks, variant_b, "/tmp/exp_variant_b.db")
    print(f"  {time.time() - t0:.1f}s")

    print(f"\n{'='*120}")
    print("7 题对比 (top-3)")
    print(f"{'='*120}")
    for name, q in QUERIES:
        print(f"\n--- {name}: {q} ---")
        a_results = run_query(conn_a, q)
        b_results = run_query(conn_b, q)
        print("  [A 原版 content-only] top-3:")
        for i, r in enumerate(a_results[:3], 1):
            print(fmt_chunk(r, i))
        print("  [B title+content] top-3:")
        for i, r in enumerate(b_results[:3], 1):
            print(fmt_chunk(r, i))
        # 同一 chunk 在 A vs B 中分数对比（看 top-1 文件相同时 score 变化）
        if a_results and b_results:
            a1 = a_results[0]
            b1 = b_results[0]
            same_chunk = a1.get('chunk_id') == b1.get('chunk_id')
            print(f"  diff: top-1 same chunk? {same_chunk}; "
                  f"A score={a1['score']:.4f}, B score={b1['score']:.4f}, "
                  f"delta={b1['score'] - a1['score']:+.4f}")

    print("\n=== Done ===")
