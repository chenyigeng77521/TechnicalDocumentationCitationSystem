"""sanity_check.py — 4 轨道 ingestion 检索 baseline 脚本

放在 ingestion/scripts/ 下，跟 eval_baseline.py 一个目录。

用法
====

# 在项目根目录跑：
cd /path/to/TechnicalDocumentationCitationSystem
/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.sanity_check

# 或直接用 python 调（也得 cwd 在项目根）：
/opt/anaconda3/envs/sqllineage/bin/python backend/ingestion/scripts/sanity_check.py

# 跑你自己的 query（命令行传）：
python -m backend.ingestion.scripts.sanity_check "你想问的问题"

# 跳过跨模块 reranker（不想等加载）：
python -m backend.ingestion.scripts.sanity_check --no-reranker

# 只跑某一个轨道：
python -m backend.ingestion.scripts.sanity_check --only-vec
python -m backend.ingestion.scripts.sanity_check --only-bm25
python -m backend.ingestion.scripts.sanity_check --only-rrf

# 改 query 集：编辑下面 QUERIES 列表

# 把输出存到文件：
python backend/ingestion/scripts/sanity_check.py | tee /tmp/sanity_out.txt

输出
====

每个 query 输出 6 段（C/D 需要 ingestion 服务运行在 :3003）：
  [A1] 纯向量             top-10  → ingestion 内部 chunks_repo.vector_search
  [A2] 纯 BM25            top-10  → ingestion 内部 chunks_repo.text_search
  [A3] RRF 合并           top-10  → 自实现 Reciprocal Rank Fusion (k0=60)
  [B]  跨模块             top-10  → 调 LLM/retrieval 的 _merge_results + Reranker（reranker 看 X0 单 chunk）
  [C]  X1.5 HTTP API     top-10  → POST :3003/chunks/vector-search（X1.5 化 content，无 reranker，按 vec score）
  [D]  X1.5 + reranker   top-10  → C 输出再喂给 reranker（reranker 看 X1.5 化 content 重新打分）← 生产链路真实效果

每条 chunk 输出格式（跟批量测试结果文件 `gold_sources[]` 同结构）：
  rank | score | {"doc_path": "docs/<domain>/<basename>", "anchor": "#section-id"}
       content: <chunk content[:200]>

最后：命中情况 (top1/top3/top5/top10 是否含 gold_doc，按完整路径或 basename 比对)

依赖
====

- conda env sqllineage
- bge-m3 + bge-reranker-base 模型
- 不需起 ingestion HTTP 服务（直接 import chunks_repo）
- 跨模块轨道 B 需要本地能 import backend.retrieval.retrieval
"""
import argparse
import sys
import time
from pathlib import Path

# 把项目根加到 sys.path（跟 eval_baseline.py 同惯例）
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import vector_search, text_search

# DB 在 src/backend/database/knowledge.db（比赛服路径约束）；用 PROJECT_ROOT 算绝对路径不依赖 cwd
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = _PROJECT_ROOT / "src" / "backend" / "database" / "knowledge.db"

# gold_doc 用完整 file_path（跟评委 jsonl gold_sources[].doc_path 同结构）
QUERIES = [
    {
        "name": "K8s API驱逐工作原理 (用户痛点 case，深层中文子目录)",
        "q": "API发起驱逐的工作原理",
        "gold_doc": "docs/kubernetes/调度与驱逐/api-eviction.md",
        "gold_anchor": "#how-api-initiated-eviction-works",
    },
    {
        "name": "React Compiler 增量采用",
        "q": "React Compiler的增量采用是什么意思？",
        "gold_doc": "docs/react/incremental-adoption.md",
        "gold_anchor": "#top",
    },
    {
        "name": "Spring DataBufferFactory",
        "q": "DataBufferFactory 是用来做什么的？",
        "gold_doc": "docs/spring/databuffer-codec.adoc",
        "gold_anchor": "#databufferfactory",
    },
    {
        "name": "K8s 内置 SSH Secret 类型 (深层中文子目录)",
        "q": "Kubernetes 中用于存放 SSH 身份认证凭据的内置 Secret 类型是什么？",
        "gold_doc": "docs/kubernetes/配置/secret.md",
        "gold_anchor": "#ssh-身份认证-secret-ssh-authentication-secrets",
    },
    {
        "name": "K8s trap (虚构 backupPolicy 字段)",
        "q": "如何在 Deployment 的 YAML 中配置 backupPolicy 字段来自动备份 Pod 数据？",
        "gold_doc": None,
        "gold_anchor": None,
    },
]


def basename(file_path):
    return Path(file_path).name


def rrf_merge(vec_results, bm25_results, k0=200):
    """Reciprocal Rank Fusion (无权重版)"""
    fused = {}
    for rank, r in enumerate(vec_results):
        cid = r["chunk_id"]
        if cid not in fused:
            fused[cid] = {**r, "rrf": 0.0, "vec_rank": None, "bm25_rank": None,
                          "vec_score": r["score"], "bm25_score": 0.0}
        fused[cid]["rrf"] += 1.0 / (k0 + rank + 1)
        fused[cid]["vec_rank"] = rank + 1
    for rank, r in enumerate(bm25_results):
        cid = r["chunk_id"]
        if cid not in fused:
            fused[cid] = {**r, "rrf": 0.0, "vec_rank": None, "bm25_rank": None,
                          "vec_score": 0.0, "bm25_score": r["score"]}
        else:
            fused[cid]["bm25_score"] = r["score"]
        fused[cid]["rrf"] += 1.0 / (k0 + rank + 1)
        fused[cid]["bm25_rank"] = rank + 1
    return sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)


def cross_module_pipeline(conn, query, q_emb, reranker_class, top_n=10):
    """跨模块版：调 LLM/retrieval 的 _merge_results + Reranker"""
    from backend.retrieval.retrieval import _merge_results
    from langchain_core.documents import Document

    vec_results = vector_search(conn, q_emb, top_k=50)
    bm25_results = text_search(conn, query, top_k=50)

    def to_doc(r):
        return Document(
            page_content=r["content"],
            metadata={
                "chunk_id": r["chunk_id"],
                "file_path": r["file_path"],
                "anchor_id": r["anchor_id"],
                "score": r["score"],
                "bm25_rank": r.get("bm25_rank"),
                "title_path": r.get("title_path"),
            },
        )

    vec_docs = [to_doc(r) for r in vec_results]
    bm25_docs = [to_doc(r) for r in bm25_results]
    merged_docs = _merge_results(vec_docs, bm25_docs)

    reranker = reranker_class(top_n=top_n)
    return reranker.rerank(query, merged_docs)


def hits(results, gold_doc, k, key="file_path"):
    """gold_doc 优先按完整路径相等比对；fallback 按 basename 相等（向后兼容旧 QUERIES）。"""
    if not gold_doc:
        return False
    gold_basename = basename(gold_doc)
    for r in results[:k]:
        actual = r[key] if isinstance(r, dict) else r.metadata.get(key, "")
        if actual == gold_doc or basename(actual) == gold_basename:
            return True
    return False


def print_track(name, results, gold_doc, top_n=10, is_documents=False):
    """每条 chunk 按批量测试结果里 `gold_sources[]` 的字段格式输出（doc_path 完整 + markdown_anchor）。"""
    import json as _json
    print(f"\n  [{name}] top-{top_n}")
    if gold_doc:
        hit_str = " | ".join(f"top{k}={hits(results, gold_doc, k)}" for k in [1, 3, 5, 10])
        print(f"    Recall: {hit_str}")
    print(f'    每行：rank | score | {{"doc_path":..., "anchor":...}} | content[:200]')
    print(f'    {"-"*150}')
    for i, r in enumerate(results[:top_n], 1):
        if is_documents:
            md = r.metadata
            doc_path = md.get("file_path", "?")
            anchor = md.get("markdown_anchor") or md.get("anchor_id") or "?"
            score = md.get("reranker_score", 0.0)
            content = (r.page_content or "")[:200].replace("\n", " ")
        else:
            doc_path = r.get("file_path", "?")
            anchor = r.get("markdown_anchor") or r.get("anchor_id") or "?"
            score = r.get("rrf") if "rrf" in r else r.get("score", 0.0)
            content = (r.get("content") or "")[:200].replace("\n", " ")
        citation = _json.dumps({"doc_path": doc_path, "anchor": anchor}, ensure_ascii=False)
        print(f'    {i:<3} {score:<7.4f} {citation}')
        print(f'         content: {content}')


def x15_via_http(query: str, q_emb: list, top_k: int = 10):
    """通过 ingestion HTTP API 调 X1.5 化的 vector-search。

    需要 ingestion 服务运行在 :3003（backend/ingestion/start.sh --bg）。
    返回 (results | None, err_message | None)。
    """
    import requests
    try:
        resp = requests.post(
            "http://localhost:3003/chunks/vector-search",
            json={"embedding": q_emb, "top_k": 30},  # 取 30 让 X1.5 合并后还能拿到 ~10
            timeout=30,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:80]}"
        data = resp.json()
        # 把 ingestion result 格式转成 print_track 能消费的（file_path / anchor_id / content / score）
        results = []
        for r in data.get("results", [])[:top_k]:
            results.append({
                "file_path": r["metadata"]["file_path"],
                "anchor_id": r["metadata"]["anchor_id"],
                "content": r["content"],
                "score": r["score"],
                "is_x15_truncated": r["metadata"].get("is_x15_truncated", False),
                "markdown_anchor": r["metadata"].get("markdown_anchor", ""),
            })
        return results, None
    except requests.exceptions.ConnectionError:
        return None, "无法连 :3003（服务未启动）"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def x15_with_reranker(query: str, q_emb: list, reranker_class, top_n: int = 10):
    """D 轨道：通过 ingestion HTTP API 拿 X1.5 化 result，再过 reranker。

    模拟生产链路：reranker 看 X1.5 化的 section 全量 content 重新打分排序。
    """
    from langchain_core.documents import Document

    # 1. HTTP 拿 X1.5 化 result（top_k=30 给 reranker 足够素材）
    x15_results, err = x15_via_http(query, q_emb, top_k=30)
    if err:
        return None, err

    # 2. 转成 Document 格式喂 reranker
    docs = [
        Document(
            page_content=r["content"],  # ← X1.5 化的 section 全量 + title prefix
            metadata={
                "file_path": r["file_path"],
                "anchor_id": r["anchor_id"],
                "score": r["score"],
                "markdown_anchor": r.get("markdown_anchor", ""),
                "is_x15_truncated": r.get("is_x15_truncated", False),
            },
        )
        for r in x15_results
    ]

    # 3. reranker 看 X1.5 化 content 打分
    reranker = reranker_class(top_n=top_n)
    reranked = reranker.rerank(query, docs)
    return reranked, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default=None, help="直接跑这一个 query")
    parser.add_argument("--only-vec", action="store_true")
    parser.add_argument("--only-bm25", action="store_true")
    parser.add_argument("--only-rrf", action="store_true")
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--no-x15", action="store_true", help="不跑 X1.5 HTTP 轨道（C）")
    parser.add_argument("--only-x15", action="store_true", help="只跑 X1.5 HTTP 轨道（C），跳过其它")
    parser.add_argument("--only-d", action="store_true", help="只跑 D 轨道（X1.5 + reranker，看生产链路真实效果）")
    parser.add_argument("--no-d", action="store_true", help="跳过 D 轨道")
    args = parser.parse_args()

    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    cnt = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    print(f"DB: {DB_PATH}")
    print(f"Total chunks: {cnt}\n")

    print("Loading bge-m3 (~10s)...")
    t0 = time.time()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")
    print(f"  bge-m3 loaded in {time.time()-t0:.1f}s")

    # reranker 加载条件：B 轨道 或 D 轨道（X1.5 + reranker）
    reranker_class = None
    needs_reranker = (
        not args.no_reranker
        and not args.only_vec
        and not args.only_bm25
        and not args.only_rrf
        and not args.only_x15  # only_x15 跳过 reranker（C 不需要）
    )
    if needs_reranker:
        print("Loading bge-reranker-base (~10s)...")
        t0 = time.time()
        from backend.retrieval.retrieval import Reranker
        reranker_class = Reranker
        Reranker()  # 触发加载
        print(f"  reranker loaded in {time.time()-t0:.1f}s")

    if args.query:
        queries_to_run = [{"name": "命令行 query", "q": args.query, "gold_doc": None, "gold_anchor": None}]
    else:
        queries_to_run = QUERIES

    for q in queries_to_run:
        print("\n" + "=" * 100)
        print(f"Query: {q['name']}")
        print(f"  Q:    {q['q']}")
        if q["gold_doc"]:
            print(f"  Gold: {q['gold_doc']} | {q['gold_anchor']}")
        else:
            print(f"  Gold: (无 / trap)")
        print("=" * 100)

        q_emb = model.encode(q["q"], normalize_embeddings=True).tolist()

        # 轨道 A1: 纯向量
        if not (args.only_bm25 or args.only_rrf or args.only_x15 or args.only_d):
            t0 = time.time()
            vec_results = vector_search(conn, q_emb, top_k=10)
            print(f"  ({time.time()-t0:.2f}s)", end="")
            print_track("A1 纯向量", vec_results, q["gold_doc"])

        # 轨道 A2: 纯 BM25
        if not (args.only_vec or args.only_rrf or args.only_x15 or args.only_d):
            t0 = time.time()
            bm25_results = text_search(conn, q["q"], top_k=10)
            print(f"  ({time.time()-t0:.2f}s)", end="")
            print_track("A2 纯 BM25", bm25_results, q["gold_doc"])

        # 轨道 A3: RRF 合并（每路取 50 再合并）
        if not (args.only_vec or args.only_bm25 or args.only_x15 or args.only_d):
            t0 = time.time()
            vec50 = vector_search(conn, q_emb, top_k=50)
            bm2550 = text_search(conn, q["q"], top_k=50)
            rrf_results = rrf_merge(vec50, bm2550)
            print(f"  ({time.time()-t0:.2f}s)", end="")
            print_track("A3 RRF 合并", rrf_results, q["gold_doc"])

        # 轨道 B: 跨模块 reranker（reranker 看 X0 单 chunk）
        if reranker_class is not None and not (args.only_x15 or args.only_d):
            t0 = time.time()
            try:
                reranked = cross_module_pipeline(conn, q["q"], q_emb, reranker_class, top_n=10)
                print(f"  ({time.time()-t0:.2f}s)", end="")
                print_track("B 跨模块 union+reranker", reranked, q["gold_doc"], is_documents=True)
            except Exception as e:
                print(f"  [B 跨模块] 失败: {type(e).__name__}: {e}")

        # 轨道 C: X1.5 HTTP API（X1.5 化 content，无 reranker，按 vec score）
        if not args.no_x15 and not args.only_d:
            t0 = time.time()
            x15_results, err = x15_via_http(q["q"], q_emb, top_k=10)
            elapsed = time.time() - t0
            if err:
                print(f"  [C X1.5 HTTP] 跳过 ({elapsed:.2f}s): {err}")
                print(f"               (是否启动了 ingestion 服务？backend/ingestion/start.sh --bg)")
            else:
                print(f"  ({elapsed:.2f}s)", end="")
                print_track("C X1.5 HTTP API (section 全量化)", x15_results, q["gold_doc"])

        # 轨道 D: X1.5 + reranker（生产链路真实效果，reranker 看 X1.5 化 content）
        if reranker_class is not None and not args.no_d:
            t0 = time.time()
            try:
                reranked, err = x15_with_reranker(q["q"], q_emb, reranker_class, top_n=10)
                elapsed = time.time() - t0
                if err:
                    print(f"  [D X1.5+reranker] 跳过 ({elapsed:.2f}s): {err}")
                else:
                    print(f"  ({elapsed:.2f}s)", end="")
                    print_track("D X1.5 + reranker (生产链路真实效果)", reranked, q["gold_doc"], is_documents=True)
            except Exception as e:
                print(f"  [D X1.5+reranker] 失败: {type(e).__name__}: {e}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
