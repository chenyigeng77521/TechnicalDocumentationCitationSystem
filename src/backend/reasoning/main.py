"""
Layer 3 FastAPI 服务入口
提供：
  POST /api/qa         — 单条问答
  POST /api/qa/batch   — 批量异步处理（jsonl 落盘 + ThreadPoolExecutor）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import sys
# 将当前目录（reasoning/）和 LLM/ 目录加入 path，方便引用 retrieval.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "retrieval"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import BATCH_MAX_WORKERS, BATCH_OUTPUT_DIR, REFUSAL_TEXT
from interfaces import (
    BatchItem,
    BatchOutputRecord,
    BatchQARequest,
    BatchQAResponse,
    GoldSource,
    QARequest,
    QAResponse,
    RetrievedChunk,
)
from reasoning import build_citations, build_context_blocks, run_reasoning
from interfaces import ReasoningResult  # 新增，用于 process_single 返回完整推理结果

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s ✅ [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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

# ==================== 工具函数 ====================

def infer_domain(doc_path: str) -> Optional[str]:
    """
    从 doc_path 推断 domain。
    规则：取 docs/<domain>/... 路径中的 <domain> 段（大小写原样保留）。
    示例：docs/react/hooks.md → "react"
          data/docs/Spring/xxx.md → "Spring"
    """
    # 统一路径分隔符
    parts = doc_path.replace("\\", "/").split("/")
    # 找到 "docs" 所在位置，取其后一段
    for i, part in enumerate(parts):
        if part.lower() == "docs" and i + 1 < len(parts):
            return parts[i + 1]
    return None


# ==================== 检索层调用封装 ====================

def retrieve_chunks(query: str) -> list[RetrievedChunk]:
    """
    调用 Layer 2 检索管道，将 Document 列表转换为 RetrievedChunk 列表。
    此函数是 Layer 2 与 Layer 3 的唯一耦合点，后续替换检索层只需修改这里。
    """
    logger.info("[retrieve] 开始检索: query=%s", query[:60])
    try:
        from retrieval import pipeline  # type: ignore
    except ImportError as e:
        logger.warning("[retrieve] retrieval 模块加载失败: %s", e)
        return []


    docs = pipeline(query)

    logger.info("[retrieve] 检索完成: raw_docs=%d", len(docs))

    chunks: list[RetrievedChunk] = []
    for idx, doc in enumerate(docs):
        meta = doc.metadata if hasattr(doc, "metadata") else {}

        # 打印第一个结果详情
        if idx == 0:
            logger.info("[retrieve] 首个结果: doc_path=%s, score=%s, content_len=%d",
                        meta.get("doc_path", ""), meta.get("score", ""), len(doc.page_content or ""))

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
        # anchor 优先用 markdown_anchor（人类可读的 H1~H4 标题锚点如 #react-compiler）
        # 检索层 _row_to_metadata 已通过 _normalize_anchor 保证格式为 '#xxx'，None → '#top'
        anchor: str = (
            meta.get("markdown_anchor")  # 优先用 ingestion 输出的 section-id(评委要的格式)
            or meta.get("anchor")
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
            content=doc.metadata.get("content") or (doc.page_content if hasattr(doc, "page_content") else ""),
            doc_path=doc_path,
            anchor=anchor,
            score=score,
            is_truncated=bool(meta.get("is_truncated", False)),
            title_path=meta.get("title_path"),
        )
        chunks.append(chunk)

    # 按 score 降序排列，保证 context 构建时高质量 chunk 优先
    chunks.sort(key=lambda c: c.score, reverse=True)
    logger.info("[retrieve] 转换完成: chunks=%d, top_score=%.4f, first_anchor=%s",
                len(chunks), chunks[0].score if chunks else 0, chunks[0].anchor if chunks else "N/A")
    return chunks


# ==================== 核心处理函数（单条）====================

def process_single(item_id: str, query: str) -> tuple[QAResponse, ReasoningResult, list]:
    """
    处理单条问答，封装完整 Pipeline：检索 → 推理 → 格式化响应。
    返回 (QAResponse, ReasoningResult, used_chunks) 三元组：
    - QAResponse：单条接口直接返回
    - ReasoningResult：包含 trap_type/unanswerable_reason，批量落盘使用
    - used_chunks：实际注入 context 的 chunk 列表，用于构建 evidence

    此函数在批量处理中被多线程并发调用，必须线程安全（无共享可变状态）。
    """
    logger.info("[%s] 开始处理: query=%s", item_id, query[:60])

    # Step 1：检索
    logger.info("[%s] Step1-检索开始...", item_id)
    try:
        chunks = retrieve_chunks(query)
    except Exception as e:
        logger.error("[retrieve] 检索异常 [%s]: %s", item_id, e, exc_info=True)
        chunks = []
        result = ReasoningResult(
            answer=REFUSAL_TEXT + " , " + str(e),
            citations=[],
            is_refusal=True,
            confidence=0.0,
            max_score=0.0,
            citation_ids=[],
        )
        qa_resp = QAResponse(
            id=item_id,
            answer=result.answer,
            citations=[],
            is_refusal=result.is_refusal,
            confidence=result.confidence,
        )
        return qa_resp, result, chunks

    logger.info("[%s] Step1-检索结束: chunks=%d", item_id, len(chunks))

    # Step 2：推理
    logger.info("[%s] Step2-推理开始...", item_id)
    result = run_reasoning(query, chunks)
    logger.info("[%s] Step2-推理结束: is_refusal=%s, answer_len=%d",
                item_id, result.is_refusal, len(result.answer or ""))

    # Step 3：构建 citations
    used_chunks: list = []
    if result.is_refusal:
        citations = []
        logger.info("[%s] Step3-构建citations: is_refusal，跳过", item_id)
    else:
        _, used_chunks = build_context_blocks(chunks)
        citations = build_citations(result.citation_ids, used_chunks)
        logger.info("[%s] Step3-citations=%d", item_id, len(citations))

    logger.info(
        "[%s] 完成: is_refusal=%s, citations=%d, score=%.3f",
        item_id, result.is_refusal, len(citations), result.max_score,
    )

    qa_resp = QAResponse(
        id=item_id,
        answer=result.answer,
        citations=citations,
        is_refusal=result.is_refusal,
        confidence=result.confidence,
    )
    return qa_resp, result, used_chunks


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
    logger.info("[api/qa] 收到请求: id=%s, query=%s", request.id, request.query[:60])
    try:
        qa_resp, _, _ = process_single(request.id, request.query)
        logger.info("[api/qa] 返回响应: id=%s, is_refusal=%s, citations=%d, answer_len=%d, confidence=%.4f",
                    qa_resp.id, qa_resp.is_refusal, len(qa_resp.citations),
                    len(qa_resp.answer or ""), qa_resp.confidence)
        return qa_resp
    except Exception as e:
        logger.error("[api/qa] 处理异常 [%s]: %s", request.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/qa/batch", response_model=BatchQAResponse)
async def qa_batch(request: BatchQARequest) -> BatchQAResponse:
    """
    批量问答接口（异步版）
    - asyncio.Semaphore(4) 控制并发，避免网关限流
    - 单条 120 秒超时，防止线程泄漏
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

    logger.info("批量处理开始：共 %d 条，输出到 %s", total, output_file)

    def _process_and_write(item: BatchItem) -> tuple[str, bool]:
        """处理单条并写入 JSONL，返回 (item_id, success)"""
        try:
            qa_resp, reasoning_result, used_chunks = process_single(item.id, item.query)

            # ---- 优化：用 dict 查找替代双重循环 ----
            chunk_map = {(c.doc_path, c.anchor): c.content for c in used_chunks}
            gold_sources: list[GoldSource] = []
            if not qa_resp.is_refusal:
                for c in qa_resp.citations:
                    evidence = chunk_map.get((c.doc_path, c.anchor), "")
                    gold_sources.append(GoldSource(
                        doc_path=c.doc_path,
                        anchor=c.anchor,
                        evidence=evidence,
                    ))

            # ---- domain：优先用调用方传入，fallback 从 doc_path 推断 ----
            domain = item.domain
            if not domain and gold_sources:
                domain = infer_domain(gold_sources[0].doc_path)

            # ---- 构建落盘记录 ----
            record = BatchOutputRecord(
                id=item.id,
                domain=domain,
                question=item.query,
                is_answerable=not qa_resp.is_refusal,
                answer=qa_resp.answer,
                gold_sources=gold_sources,
                answer_type=item.answer_type,
                difficulty=item.difficulty,
                trap_type=reasoning_result.trap_type if qa_resp.is_refusal else None,
                unanswerable_reason=reasoning_result.unanswerable_reason if qa_resp.is_refusal else None,
            )
            write_jsonl_line(output_file, record.model_dump(exclude_none=True))
            return item.id, True

        except Exception as e:
            logger.error("批量任务 [%s] 失败: %s", item.id, e, exc_info=True)
            # 失败条目写入拒答占位记录，保持 id 连续性
            error_record = BatchOutputRecord(
                id=item.id,
                domain=item.domain,
                question=item.query,
                is_answerable=False,
                answer="抱歉，我无法从提供的文档中找到答案。",
                gold_sources=[],
                answer_type=item.answer_type,
                difficulty=item.difficulty,
                unanswerable_reason=f"[处理异常] {e}",
            )
            try:
                row = error_record.model_dump(exclude_none=True)
                row["_error"] = str(e)
                write_jsonl_line(output_file, row)
            except Exception:
                pass
            return item.id, False

    # ---- 异步执行批量，单条 120 秒超时，并发 4 ----
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(4)

    async def _run_with_sem(item: BatchItem) -> tuple[str, bool]:
        async with sem:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _process_and_write, item),
                timeout=120.0,
            )

    tasks = [_run_with_sem(item) for item in request.items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    succeeded = 0
    failed = 0
    for r in results:
        if isinstance(r, Exception):
            failed += 1
        elif r[1]:
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
