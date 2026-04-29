"""
Layer 3 FastAPI 服务入口
提供：
  POST /api/qa         — 单条问答
  POST /api/qa/batch   — 批量异步处理（jsonl 落盘 + ThreadPoolExecutor）
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import sys
# 将当前目录（reasoning/）和 LLM/ 目录加入 path，方便引用 retrieval.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "LLM"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import BATCH_MAX_WORKERS, BATCH_OUTPUT_DIR
from interfaces import (
    BatchItem,
    BatchQARequest,
    BatchQAResponse,
    QARequest,
    QAResponse,
    RetrievedChunk,
)
from reasoning.reasoning import build_citations, run_reasoning

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("layer3.main")

# ==================== FastAPI App ====================
app = FastAPI(
    title="Layer 3 — 推理与引用层",
    description="RAG 推理服务，单条问答 + 批量 JSONL 落盘",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 检索层调用封装 ====================

def retrieve_chunks(query: str) -> list[RetrievedChunk]:
    """
    调用 Layer 2 检索管道，将 Document 列表转换为 RetrievedChunk 列表。
    此函数是 Layer 2 与 Layer 3 的唯一耦合点，后续替换检索层只需修改这里。
    """
    try:
        from retrieval import pipeline  # type: ignore
    except ImportError:
        logger.warning("retrieval.py 未找到，返回空 chunks（请确认 PYTHONPATH）")
        return []

    try:
        docs = pipeline(query)
    except Exception as e:
        logger.error("检索层调用失败: %s", e)
        return []

    chunks: list[RetrievedChunk] = []
    for doc in docs:
        meta = doc.metadata if hasattr(doc, "metadata") else {}

        # 优先使用 reranker_score，降级到 vector score
        score: float = float(
            meta.get("reranker_score") or meta.get("score") or 0.0
        )

        # 从 metadata 提取 doc_path 和 anchor
        # retrieval.py 里字段名可能是 file_path / anchor_id / title_path 等
        doc_path: str = (
            meta.get("doc_path")
            or meta.get("file_path")
            or ""
        )
        anchor: str = (
            meta.get("anchor")
            or meta.get("anchor_id")
            or ""
        )

        # anchor_id 格式可能是 "file_path#char_offset"，需提取 #xxx 部分
        if anchor and "#" in anchor and not anchor.startswith("#"):
            anchor = "#" + anchor.split("#", 1)[1]
        elif anchor and not anchor.startswith("#"):
            anchor = "#" + anchor

        # 若 anchor 仍为空，用 title_path 推断
        if not anchor or anchor == "#":
            title_path: str = meta.get("title_path", "")
            if title_path:
                # title_path 转 anchor（空格 → -，全小写）
                anchor = "#" + title_path.lower().replace(" ", "-").replace(">", "").replace("/", "").strip("-")
            else:
                anchor = "#top"

        chunk = RetrievedChunk(
            chunk_id=meta.get("chunk_id", ""),
            content=doc.page_content if hasattr(doc, "page_content") else "",
            doc_path=doc_path,
            anchor=anchor,
            score=score,
            is_truncated=bool(meta.get("is_truncated", False)),
            title_path=meta.get("title_path"),
        )
        chunks.append(chunk)

    # 按 score 降序排列，保证 context 构建时高质量 chunk 优先
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks


# ==================== 核心处理函数（单条）====================

def process_single(item_id: str, query: str) -> QAResponse:
    """
    处理单条问答，封装完整 Pipeline：检索 → 推理 → 格式化响应。
    此函数在批量处理中被多线程并发调用，必须线程安全（无共享可变状态）。
    """
    logger.info("[%s] 开始处理: %s", item_id, query[:60])

    # Step 1：检索
    chunks = retrieve_chunks(query)

    # Step 2：推理
    result = run_reasoning(query, chunks)

    # Step 3：构建 citations（需要 used_chunks，从 context 构建时已截断）
    if result.is_refusal:
        citations = []
    else:
        # 从 chunks 中取出实际被引用的（used_chunks 已在 run_reasoning 内部处理）
        # 这里通过 citation_ids 映射回 chunks（与 reasoning.py 内部逻辑对齐）
        from reasoning import build_context_blocks  # type: ignore
        _, used_chunks = build_context_blocks(chunks)
        citations = build_citations(result.citation_ids, used_chunks)

    logger.info(
        "[%s] 完成: is_refusal=%s, citations=%d, score=%.3f",
        item_id, result.is_refusal, len(citations), result.max_score,
    )

    return QAResponse(
        id=item_id,
        answer=result.answer,
        citations=citations,
        is_refusal=result.is_refusal,
        confidence=result.confidence,
    )


# ==================== JSONL 文件写入（带锁）====================

# 全局文件写锁：key = 文件绝对路径
_file_locks: dict[str, threading.Lock] = {}
_file_locks_mutex = threading.Lock()


def _get_file_lock(filepath: str) -> threading.Lock:
    """获取指定文件的写锁（单例）"""
    with _file_locks_mutex:
        if filepath not in _file_locks:
            _file_locks[filepath] = threading.Lock()
        return _file_locks[filepath]


def write_jsonl_line(filepath: str, record: dict) -> None:
    """线程安全地向 JSONL 文件追加一行"""
    lock = _get_file_lock(filepath)
    with lock:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ==================== API 路由 ====================

@app.get("/health")
def health_check() -> dict:
    """服务健康检查"""
    return {"status": "ok", "service": "layer3-reasoning"}


@app.post("/api/qa", response_model=QAResponse)
def qa_single(request: QARequest) -> QAResponse:
    """
    单条问答接口
    入参：{ "id": "...", "question": "..." }
    出参：{ "id", "answer", "citations", "is_refusal", "confidence" }
    """
    try:
        return process_single(request.id, request.query)
    except Exception as e:
        logger.error("处理请求异常 [%s]: %s", request.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/qa/batch", response_model=BatchQAResponse)
def qa_batch(request: BatchQARequest) -> BatchQAResponse:
    """
    批量问答接口
    - ThreadPoolExecutor(max_workers=8) 并发处理
    - 每条结果逐行写入 JSONL，文件写锁保证线程安全
    - 每条任务独立 try/except，单条失败不影响整体

    入参：{ "items": [{"id": "...", "question": "..."}] }
    出参：{ "status", "file_path", "total", "succeeded", "failed" }
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="items 不能为空")

    # 准备输出文件路径
    output_dir = Path(BATCH_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 用第一条 id 作为文件名标识
    first_id = request.items[0].id
    output_file = str(output_dir / f"result_{first_id}.jsonl")

    # 清空/创建文件
    open(output_file, "w", encoding="utf-8").close()

    total = len(request.items)
    succeeded = 0
    failed = 0

    logger.info("批量处理开始：共 %d 条，输出到 %s", total, output_file)

    def _process_and_write(item: BatchItem) -> bool:
        """处理单条并写入文件，返回是否成功"""
        try:
            resp = process_single(item.id, item.query)
            record = {
                "id": resp.id,
                "answer": resp.answer,
                "citations": [c.model_dump() for c in resp.citations],
                "is_refusal": resp.is_refusal,
                "confidence": resp.confidence,
            }
            write_jsonl_line(output_file, record)
            return True
        except Exception as e:
            logger.error("批量任务 [%s] 失败: %s", item.id, e, exc_info=True)
            # 失败条目写入错误占位记录，保持 id 连续性
            error_record = {
                "id": item.id,
                "answer": "抱歉，我无法从提供的文档中找到答案。",
                "citations": [],
                "is_refusal": True,
                "confidence": 0.0,
                "_error": str(e),
            }
            try:
                write_jsonl_line(output_file, error_record)
            except Exception:
                pass
            return False

    # 多线程并发处理
    with ThreadPoolExecutor(max_workers=BATCH_MAX_WORKERS) as executor:
        futures = {executor.submit(_process_and_write, item): item for item in request.items}
        for future in as_completed(futures):
            if future.result():
                succeeded += 1
            else:
                failed += 1

    logger.info("批量处理完成：成功 %d，失败 %d，文件: %s", succeeded, failed, output_file)

    return BatchQAResponse(
        status="success" if failed == 0 else "partial_failure",
        file_path=output_file,
        total=total,
        succeeded=succeeded,
        failed=failed,
    )


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
