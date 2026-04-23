import anyio
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse

from app.config import Settings
from app.database.sqlite import Db
from app.deps import get_db, get_embedder, get_llm, get_reranker, get_settings
from app.embedder.bge_m3 import BgeM3Embedder
from app.llm.client import LlmClient
from app.qa.orchestrator import retrieve_and_rerank
from app.qa.prompt import build_prompt
from app.retriever.reranker import BgeReranker
from app.sse import sse_event

router = APIRouter()

REFUSAL = (
    "抱歉，在文档库中未找到与您问题相关的内容。"
    "请尝试重新表述您的问题，或确保已上传相关文档。"
)


@router.post("/api/qa/ask-stream")
async def ask_stream(
    payload: dict = Body(...),
    db: Db = Depends(get_db),
    embedder: BgeM3Embedder = Depends(get_embedder),
    reranker: BgeReranker = Depends(get_reranker),
    llm: LlmClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
):
    question = (payload.get("question") or "").strip()
    if not question:
        async def empty_gen():
            yield sse_event({"answer": "问题不能为空"})
            yield sse_event({"sources": []})
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    chunks = await anyio.to_thread.run_sync(
        lambda: retrieve_and_rerank(
            question, embedder=embedder, reranker=reranker, db=db,
            threshold=settings.rerank_threshold,
        )
    )

    if not chunks:
        async def refuse_gen():
            yield sse_event({"answer": REFUSAL})
            yield sse_event({"sources": []})
        return StreamingResponse(
            refuse_gen(), media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    prompt = build_prompt(question, chunks)
    sources: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        f = db.get_file(c["file_id"])
        name = f["original_name"] if f else "未知文件"
        if name not in seen:
            seen.add(name)
            sources.append(name)

    async def gen():
        try:
            async for tok in llm.stream_answer(prompt):
                yield sse_event({"answer": tok})
        except Exception as e:  # noqa: BLE001
            yield sse_event({"answer": f"\n\n（服务器错误：{e}）"})
        yield sse_event({"sources": sources})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
