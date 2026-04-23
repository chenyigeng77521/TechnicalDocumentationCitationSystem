# chunking-rag-py

Python 重写的 chunking-rag 服务（α 路线 / B 范围 MVP），与 `backend/chunking-rag/` (TS 版) 和 `backend/entrance/` (同事 chenyigeng) 同根并存，**端口 3002 二选一启动**。

**设计规范**：[docs/superpowers/specs/2026-04-23-chunking-rag-py-design.md](../../docs/superpowers/specs/2026-04-23-chunking-rag-py-design.md)
**实施计划**：[docs/superpowers/plans/2026-04-23-chunking-rag-py-plan.md](../../docs/superpowers/plans/2026-04-23-chunking-rag-py-plan.md)

## 启动

```bash
# 清空 3002 端口（POSIX 可移植，无进程时静默退出）
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true

cd backend/chunking-rag-py
conda activate sqllineage          # Python 3.12.4
pip install -r requirements.txt
cp .env.example .env               # 首次：填入亚信网关 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
uvicorn app.main:app --host 0.0.0.0 --port 3002
```

**首次启动会从 HuggingFace Hub 下载**：
- `BAAI/bge-m3` (~2.3GB dense embedding)
- `BAAI/bge-reranker-v2-m3` (~1.1GB reranker)

耐心等 5 分钟（实测 ~40 分钟首次抓取，后续启动 <30 秒）。

## 架构

- **Web**：FastAPI 0.115 + uvicorn，lifespan 加载模型常驻
- **DB**：sqlite3 stdlib + WAL，每请求独立连接，`BEGIN IMMEDIATE` 互斥
- **Embedding**：FlagEmbedding BGEM3FlagModel (dense-only, 1024 维)
- **BM25**：rank_bm25 + jieba 中文分词，查询时内存重建
- **融合**：手写 RRF（k=60）
- **Rerank**：FlagReranker bge-reranker-v2-m3，`normalize=True` sigmoid → [0,1]
- **拒答门控**：`RERANK_THRESHOLD=0.4`（tuning window 可调）
- **LLM**：openai SDK + 亚信网关，SSE 流式
- **并发纪律**：sync 端点 → threadpool；async 端点内同步模型/DB 调用走 `anyio.to_thread.run_sync`；全局 `threading.Lock` 串行化模型推理（R7）

## 前端对接

前端 `frontend/app/page.tsx` 四处 `fetch()` 硬编码 `http://localhost:3002`。6 个端点完全兼容：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/upload` | POST | multipart, ≤10 files ≤50MB each; converting→completed/failed 状态机 |
| `/api/upload/raw-files?page=&limit=` | GET | 分页列 raw 目录 |
| `/api/qa/files` | GET | 列 `status='completed'` 的文件（含 mtime） |
| `/api/qa/stats` | GET | `{totalFiles, stats:{fileCount, chunkCount, indexedCount}}` |
| `/api/qa/ask-stream` | POST | SSE `data:{answer}` × N + 末尾 `data:{sources}` |
| `/api/qa/files/{filename}` | DELETE | 路径穿越校验 + 级联删 chunks |

## 测试

```bash
cd backend/chunking-rag-py
pytest tests/ -v
```

期望 **86 passed**，覆盖：
- 单元（filename_utils 8 / sqlite 11 / chunker 15 / parser 6 / bm25 3 / rrf 3 / dense 2 / embedder 2 / reranker 2 / orchestrator 4 / llm 2 / sse 2 / config 4 = 64）
- E2E 契约+鲁棒性（health/stats/files/upload/raw-files/ask-stream SSE/delete cascade/path traversal/limits/failure state machine/concurrent upload/CORS = 22）

## 已知限制

- **模型 lock 下 QPS ≤ 1/推理耗时**（spec R7）：bge-m3 CPU 推理 ~200ms ⇒ QPS ≤ 5。演示场景够用，高并发需复制模型实例 + semaphore
- **上传中途失败保留 raw 文件**（spec D10）：DB 留 `status='failed'` 记录，支持重试/排查；不做启动/周期性 GC
- **SSE 跨 TCP 分帧 bug**（spec R2，从 TS 版继承）：前端 `chunk.split('\n')` 不做跨包 buffer，本地演示 P(出现) 极低，未修
- **端口冲突**：与 `backend/chunking-rag/` TS 版和 `backend/entrance/` 同事服务都占 3002，约定 "谁演示谁启动"

## 规划外（v2 升级路径）

见 spec §10：content_type 分派、char_offset anchor、chunk_versions 版本化、增量更新 pipeline、PaddleOCR、sparse/colbert、sqlite-vec 等全部不在本次范围。
