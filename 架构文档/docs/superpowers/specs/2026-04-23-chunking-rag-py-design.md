# Chunking RAG Python 重写设计

**日期**：2026-04-23
**状态**：Spec（brainstorm 2026-04-23 敲定，待写 plan）
**作者**：tuyh3（个人 owner 分支，与团队 main 平行）

---

## 1. 背景与关联文档

### 1.1 TS 版（已 ship）

- 路径：`backend/chunking-rag/`（TypeScript，Express，端口 3002）
- 状态：已合进 `origin/main`（16 commits，9/9 e2e PASS）
- Eval baseline：**40/100**（团队统一测题集）
- Spec：[2026-04-23-chunking-rag-service-design.md](./2026-04-23-chunking-rag-service-design.md)
- 6 个前端端点全部可用，存储自包含在 `backend/chunking-rag/storage/`

### 1.2 团队 Layer 1 设计文档

- 路径：`docs/layer1-design-v2.md`（1753 行）
- 归属：团队多人协作文档，**本 spec 不修改该文档**
- 使用方式：作为"满分形态"参考，本 spec 的"不在范围"章节链回 v2 对应小节

### 1.3 本 spec 目标

把 TS 版重写为 Python 版（**α 路线，B 范围 MVP**），靠 bge-m3 dense 检索 + BM25 + RRF + reranker + 硬阈值拒答，把 eval 从 40 拉到 **72–80**。前端 0 修改。

### 1.4 Deadline

- 2026-05-10 18:00（Day 19）是整体 deadline
- 今天是 Day 2，Feature 截止 Day 10（给 eval tuning 留 9 天）

---

## 2. 目标与非目标

### 2.1 目标

1. **Eval 72–80 分**（TS baseline 40），靠 4 个升级点叠加：
   - BAAI/bge-m3 dense embedding（TS 版用 text-embedding-3-large 降级为 keyword-only）
   - rank_bm25 + jieba 中文分词的关键词召回
   - RRF（Reciprocal Rank Fusion）融合 dense + BM25
   - FlagReranker(BAAI/bge-reranker-v2-m3) 重排 + 硬阈值 0.4 拒答
2. **前端 0 修改**：6 个端点与 TS 版**语义契约**一致（字段名/类型/嵌套 shape）——由 snapshot 契约测试锁定关键字段；header 顺序、JSON key 顺序、datetime 序列化等表达层细节不在锁定范围（见 §4）
3. **二选一占 3002 端口**：和 TS 版互斥启动，不做反向代理
4. **存储完全自包含**：`backend/chunking-rag-py/storage/`（与 TS 版 storage 隔离，允许并存）

### 2.2 非目标

- 替换 TS 版：TS 版作为 fallback 保留在仓库（同级兄弟目录 `backend/chunking-rag/`），两版同时存在
- 与同事 `backend/` 根目录的 Express 服务**进程/数据集成**：即使现在共享 `backend/` 目录（团队约定 2026-04-23 更新），仍通过端口约定二选一启动，不共享 SQLite、不共享 raw 目录
- 改动 `frontend/`：一行不动
- 修改团队 `docs/layer1-design-v2.md`
- 实现 v2 文档里的 char_offset anchor、content_type 三类分派、增量更新 pipeline（见 §10）

---

## 3. 架构

### 3.1 目录布局

```
TechnicalDocumentationCitationSystem/
├── backend/                          ⬅ 团队约定：所有方案都放这里（2026-04-23 更新）
│   ├── src/ package.json tsconfig.json ...  ⬅ 同事 chenyigeng 的文件管理 demo（不碰）
│   ├── chunking-rag/                 ⬅ TS 版（已 ship，端口 3002）
│   └── chunking-rag-py/              ⬅ Python 版（本 spec，端口 3002，与 TS 二选一）
├── frontend/                         ⬅ 同事（硬编码 localhost:3002，不碰）
└── docs/
    ├── layer1-design-v2.md           ⬅ 团队文档（只读参考）
    └── superpowers/specs/
        ├── 2026-04-23-chunking-rag-service-design.md   (TS 版)
        └── 2026-04-23-chunking-rag-py-design.md        (本 spec)
```

`backend/chunking-rag-py/` 内部：

```
backend/chunking-rag-py/
├── requirements.txt
├── .env.example
├── README.md
├── pyproject.toml              (可选，只配 ruff/pytest)
├── app/
│   ├── __init__.py
│   ├── main.py                 FastAPI app entry，lifespan 初始化 embedder/reranker
│   ├── config.py               pydantic-settings
│   ├── deps.py                 FastAPI Depends 工厂（db / embedder / reranker 单例）
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── upload.py           POST /api/upload, GET /api/upload/raw-files
│   │   ├── qa.py               GET /api/qa/files, /api/qa/stats, DELETE /api/qa/files/{name}
│   │   └── qa_stream.py        POST /api/qa/ask-stream (SSE)
│   ├── converter/
│   │   ├── __init__.py
│   │   ├── parser.py           各格式 → markdown + line_map (pdf/docx/pptx/xlsx/md)
│   │   └── chunker.py          markdown → Chunk[]（单段落/标题切，保留 line 范围）
│   ├── embedder/
│   │   ├── __init__.py
│   │   └── bge_m3.py           FlagEmbedding BGEM3FlagModel 封装（dense-only）
│   ├── retriever/
│   │   ├── __init__.py
│   │   ├── dense.py            numpy 余弦相似度 top-k
│   │   ├── bm25.py             rank_bm25 + jieba，每次查询在内存里重建 index
│   │   ├── rrf.py              RRF 融合两路 ranked list
│   │   └── reranker.py         FlagReranker 封装
│   ├── qa/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     组合检索 + 重排 + 阈值门控
│   │   └── prompt.py           prompt 模板
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py           openai SDK + 亚信网关（stream/non-stream）
│   ├── database/
│   │   ├── __init__.py
│   │   └── sqlite.py           sqlite3 stdlib + schema + CRUD
│   ├── filename_utils.py       sanitize / fix_encoding / 冲突加后缀（抄 TS 版）
│   └── sse.py                  SSE 事件编码 util
├── tests/
│   ├── conftest.py
│   ├── test_chunker.py
│   ├── test_filename_utils.py
│   ├── test_sqlite.py
│   ├── test_bm25.py
│   ├── test_rrf.py
│   ├── test_dense_retriever.py (mock embedder)
│   └── test_upload_qa_e2e.py   (TestClient，mock embedder/reranker/llm)
└── storage/
    ├── raw/                    原文件
    ├── converted/              转换后 .md
    ├── mappings/               line_map .json
    └── knowledge.db            SQLite
```

### 3.2 与 TS 版的差异

| 维度 | TS 版 | Python 版 |
|---|---|---|
| 语言/运行时 | Node 20 + tsx/TypeScript | Python 3.12.4 (conda `sqllineage`) |
| Web 框架 | Express | FastAPI |
| DB 驱动 | better-sqlite3 | sqlite3 (stdlib) |
| Embedding | OpenAI text-embedding-3-large（跑不通降级 keyword） | 本地 BAAI/bge-m3 (FlagEmbedding, dense) |
| 关键词召回 | SQL `content LIKE %q%` | rank_bm25 + jieba |
| 融合 | 无（单路 LIKE） | RRF（手写） |
| Reranker | 无 | BAAI/bge-reranker-v2-m3 |
| 拒答门控 | 软文案 | reranker_score < 0.4 硬阈值 |
| LLM 客户端 | openai Node SDK | openai Python SDK |

### 3.3 与 layer1-design-v2.md 的差异

v2 设计目标是"满分形态"，本 spec 是 **B 范围 MVP**，显式砍掉：

- content_type（document/code/structured_data）三分支 chunking → 只做 document
- char_offset anchor → 只用 start_line/end_line（v1 格式）
- chunks + chunk_versions 双表（版本化） → 单表 chunks
- 增量更新 / 文件监听 5min SLA → 上传即触发 indexing
- LibreOffice 旧 Office 格式 → 只支持 docx/xlsx/pptx（openpyxl/python-docx/python-pptx）
- PaddleOCR → 不做
- WebSocket 进度推送 → 复用 SSE，上传同步返回
- bge-m3 sparse / colbert 多功能输出 → 只用 dense（1024 维）

---

## 4. 前端契约对齐（6 端点）

前端**主问答页关键路径**（[page.tsx:35,54,144,154,191](../../../frontend/app/page.tsx) 四处 `fetch()` 加刷新 stats 那次共 5 处）**直接写死字符串** `http://localhost:3002`——旁路了 `NEXT_PUBLIC_API_URL` 环境变量。虽然 [frontend/lib/api.ts:3](../../../frontend/lib/api.ts) 和 [frontend/lib/store.ts:87](../../../frontend/lib/store.ts) 确实读取 `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3002'`，但主页面代码并未使用 `lib/api.ts`。**结论**：端口必须是 3002（硬编码路径压倒 env 路径）；改 env 无效。

契约等价口径为**语义契约**：字段名、类型、嵌套 shape、SSE 事件载荷 schema 必须对齐 TS 版；header 顺序、JSON key 顺序、datetime 序列化格式、错误体 message 措辞属于表达层，允许 Express→FastAPI 自然差异。由 snapshot/e2e 契约测试（§9.2）固定前端实际读取的字段（`data.totalFiles` / `data.files[].{name,size,mtime,createdAt,modifiedAt}` / SSE `data.answer` + `data.sources` / upload `data.success` + `data.message`）。

| # | 端点 | 方法 | 请求 | 响应 |
|---|---|---|---|---|
| 1 | `/api/upload` | POST | `multipart/form-data` 字段 `files` (≤10 个，≤50MB each) | `{success, files: [{id, originalName, format, size, status}], message}` |
| 2 | `/api/upload/raw-files` | GET | `?page=N&limit=10` | `{success, files: [{name, path, size, createdAt, modifiedAt}], total, page, limit, totalPages}` |
| 3 | `/api/qa/files` | GET | — | `{success, files: [{name, size, mtime, id, format, uploadTime, category}], total}` |
| 4 | `/api/qa/stats` | GET | — | `{success, totalFiles, stats: {fileCount, chunkCount, indexedCount}}` |
| 5 | `/api/qa/ask-stream` | POST | `{question, topK?}` | SSE: `data: {"answer": "<incremental>"}\n\n` × N 次，末尾 `data: {"sources": [...]}\n\n` |
| 6 | `/api/qa/files/{filename}` | DELETE | path 参数 `filename`（URL encoded） | `{success, message}` |

**SSE 协议硬约束**（前端 `page.tsx:215-225` 解析：`if (data.answer) answer += data.answer; if (data.sources) sources = data.sources;`）：
- 每个 LLM token 发一次 `data: {"answer": "<token>"}\n\n`
- 结束前发一次 `data: {"sources": ["<filename1>", ...]}\n\n`
- 错误：发一条 `data: {"answer": "\n\n（服务器错误：<msg>）"}\n\n` 再 close
- 不用 `event: xxx` 自定义事件名，只用 `data:`
- 实现模式：FastAPI `StreamingResponse(media_type="text/event-stream")` + `async def gen()` 生成器：

  ```python
  async def gen():
      async for token in llm.stream(prompt):
          yield f"data: {json.dumps({'answer': token}, ensure_ascii=False)}\n\n"
      yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
  return StreamingResponse(gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
  ```

  每次 `yield` 即向客户端推送一个 frame；不需要显式 `flush`，也不需要 `anyio.sleep(0)`（后者对 TCP/proxy 分帧无帮助）。`X-Accel-Buffering: no` 关闭潜在 nginx/uvicorn 缓冲

**路径穿越校验**（#6 `DELETE`）：
```python
safe = pathlib.Path(raw_dir, filename).resolve()
if not str(safe).startswith(str(pathlib.Path(raw_dir).resolve()) + os.sep):
    raise HTTPException(400, "invalid filename")
```

---

## 5. 关键设计决策

### D1. 全 Python 重写（α 路线），不做渐进迁移

- **背景**：brainstorm 阶段对比过 α（整体重写）/ β（TS 保留 + Python 只接 embedding/rerank 两个微服务）/ γ（把 TS 的 retriever 换成调 Python HTTP）
- **决策**：α。理由：β/γ 要维护跨进程契约，对 eval 贡献为零；α 同时解决"bge-m3/FlagReranker 没有 Node 绑定"和"调试链路统一在 Python"两个问题
- **代价**：TS 版成沉默代码（放 repo 作 fallback，不再迭代）

### D2. 本地 embedding/reranker 不违反"统一 LLM 网关"红线

- **背景**：团队红线"所有 LLM 调用必须走亚信 LLM 网关"
- **用户已确认**：该红线限制的是 **文本生成** 类 LLM；embedding / reranker 作为本地模型权重加载，**不走任何外部 API**，不在红线范围
- **应用**：`openai` 客户端的 `base_url` 强制注入亚信网关，只承担 chat completion；embedder 和 reranker 完全离线（`FlagEmbedding` 直接吃本地或 HF cache 权重）

### D3. 范围选 B（实用 MVP），不选 A（最小连通）或 C（全量满分）

| 方案 | 范围 | 预估分数 | 工期 |
|---|---|---|---|
| A | 只接本地 embedding，其他照抄 TS | 55 左右 | 3 天 |
| **B** | **embedding + BM25 + RRF + reranker + 硬阈值** | **72–80** | **7 天** |
| C | B + char_offset + 三类分派 + 增量 | 85+ | 15+ 天 |

选 B：9 天 feature 预算可覆盖 B + eval tuning；C 吃不下。

### D4. 单进程 FastAPI + 模型常驻内存 + 每请求独立 DB 连接

**模型加载**：
- `app.main` 里 `@asynccontextmanager lifespan`：启动加载 bge-m3（~2GB VRAM/RAM）+ reranker（~600MB），放 `app.state`
- 路由通过 `Depends(get_embedder)` / `Depends(get_reranker)` 拿单例
- **全局 model lock**（避免对 FlagEmbedding/torch 并发安全做未验证假设）：`app.state.model_lock = threading.Lock()`，所有 `embedder.encode` / `reranker.score` 调用必须在 `with model_lock:` 内。详见 R7

**并发模型**（纠正 v1 认知错误）：
- FastAPI **不默认串行**：`async def` 路由共享事件循环，sync `def` 路由走 AnyIO threadpool（默认 40 worker）。请求天然可并发。
- `sqlite3.connect(check_same_thread=False)` **只关闭线程检查断言，不提供互斥**。单连接被多线程并发写会破坏内部游标/事务状态。

**sync/async 执行纪律**（避免 threading.Lock + torch 推理阻塞事件循环）：
- **上传端点**：`POST /api/upload` 声明为 `def`（非 `async def`）——自动落 threadpool，内部直接 `with model_lock: embedder.encode(...)` 是 worker 线程级阻塞，不影响其他请求
- **问答 SSE 端点**：`async def` 无法避免（`StreamingResponse` + openai 异步 stream）。规则：
  - **任何**同步模型推理（embedder / reranker）或 `threading.Lock` 获取，必须通过 `await anyio.to_thread.run_sync(...)` 卸载到 threadpool，**严禁**在 async 路由/生成器里直接调
  - `orchestrator.retrieve_and_rerank(question)` 是纯同步函数；`qa_stream.py` 里这样调：
    ```python
    chunks = await anyio.to_thread.run_sync(
        orchestrator.retrieve_and_rerank, question, embedder, reranker, db
    )
    ```
  - LLM 流式本身走 `openai` SDK 的 `async for`，不需要卸载
- **DB 操作**：同步端点直接 execute；async 端点内的 DB 操作也卸载到 threadpool（`await anyio.to_thread.run_sync(db.get_file, id)`）
- 违反此纪律的代码 = 单个慢请求让整个服务卡死的高风险 bug；plan 阶段在 e2e 测试里加并发读 + 并发问答验证

**DB 连接策略**：WAL 在 app startup 一次性开启（**数据库级持久设置**，写入 DB 文件头）；每请求一个连接只设**连接级**设置

```python
# app/main.py lifespan 里（仅执行一次）
def init_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")   # 持久化到 DB 文件，后续连接自动 WAL
    conn.executescript(SCHEMA_SQL)              # CREATE TABLE / INDEX (见 §7)
    conn.close()

# app/deps.py — 每请求调一次
def get_db(settings: Settings = Depends(get_settings)):
    conn = sqlite3.connect(
        settings.resolve_path(settings.db_path),
        isolation_level=None,      # autocommit；事务由 write_tx() 显式管理
    )
    conn.execute("PRAGMA busy_timeout=10000;")  # 10s 文件锁超时（连接级）
    conn.execute("PRAGMA foreign_keys=ON;")     # 连接级
    try:
        yield Db(conn)
    finally:
        conn.close()
```

**事务 helper**（关键：`isolation_level=None` 下 `with conn:` **不提供**事务语义——autocommit 模式里每条 execute 立即提交，`with` 的 rollback 无事可回。**不要**用 `with conn:` 写事务）：

```python
from contextlib import contextmanager

@contextmanager
def write_tx(conn: sqlite3.Connection):
    """显式 BEGIN IMMEDIATE 写事务，异常回滚。autocommit 模式下的唯一正确写法。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")
```

所有多语句写操作必须 `with write_tx(conn):` 包住（如 §6.1 三阶段状态机里"INSERT chunks × N + UPDATE files status"那一步、`DELETE /files/:name` 的"DELETE chunks + DELETE files"）。单条 INSERT/UPDATE 可直接 execute（autocommit 自己就是一个事务）。

- WAL 模式（startup 一次性写入 DB 文件头，不每连接执行）：多个读请求并发无阻塞；写事务走 `BEGIN IMMEDIATE` 拿 RESERVED 锁，串行化靠 SQLite 文件锁（非 Python GIL、非 threading.Lock）
- 连接开销：sqlite3 本地文件 ~1ms 级，MVP 负载可接受

**单请求内串行**：`POST /api/upload` 一次最多 10 个文件，在**同一个请求的同一个线程**里顺序 parse/chunk/embed/write——不起 `asyncio.gather` 并发（GIL + GPU 串行化 + DB 写锁下并发无实际收益且复杂度陡增）。

**不做 worker 池 / 任务队列**：MVP 认可"上传大文件会阻塞该请求"，不阻塞其他请求（因为 threadpool 还有其他 worker）。

### D5. chunking 算法：复用 TS 版逻辑，Python 重写

- 输入：`converter/parser.py` 产出的 markdown + line_map
- 切分：按 markdown 标题（`#` `##` `###`）切大段，每段再按空行切小段，每块目标长度 400–800 字符，≥ 100 字符 fallback 合并
- 输出：`Chunk(content, start_line, end_line, original_lines)`
- 不做 char_offset（v2 feature）
- chunker 必须有 14 个单测（对标 TS 版 chunker.test.ts），关键 case：单段超长、标题分隔、空行合并、含代码块跳过内部切分

### D6. 检索链路：dense + BM25 → RRF → rerank → 阈值

```
question
  ├── embedder.encode(question) ─▶ dense_top20 (余弦，全部 chunks)
  └── bm25_query (jieba 分词)   ─▶ bm25_top20
                     │
                     ▼
                RRF 融合 (k=60)    ─▶ fused_top20
                     │
                     ▼
             reranker(question, fused_top20) ─▶ scored
                     │
                     ▼
            max(score) < 0.4 ?
              yes → 拒答："未找到相关内容"
              no  → 保留 score ≥ 0.4 的，取 top 5 喂 LLM
```

- **召回集过滤**：两路召回**只**在 `files.status='completed'` 的 chunks 上检索——通过 SQL JOIN 或先 `SELECT c.* FROM chunks c JOIN files f ON c.file_id=f.id WHERE f.status='completed'` 一次性 load。避免 converting/failed 文件（状态更新失败、pending indexing 中）的残留 chunks 被误召回
- **dense 检索**：过滤后 chunks 的 vector 字段 load 进 numpy 算一次全量余弦（chunk 数 < 5000 不优化）
- **BM25**：每次查询前从过滤后的 chunks load content，jieba 分词，`rank_bm25.BM25Okapi` 即时建 index 算分（~50ms @ 1000 chunks，acceptable）
- **RRF**：`score = Σ 1/(k + rank_i)`，k=60 行业默认
- **Reranker**：`FlagReranker` 对 (question, chunk.content) 批量打分，`normalize=True` 经 **sigmoid** 映射到 [0,1]——**非 calibrated 概率**，只反映相对强弱（官方文档 <https://bge-model.com/tutorial/5_Reranking/5.2.html>）
- **阈值 0.4**：**初始种子值**（brainstorm 凭直觉起点），**必须**在 eval tuning 窗口（Day 11–19）用团队测题集校准；可能最终落在 0.3–0.6 区间。env var `RERANK_THRESHOLD` 在 tuning 期反复调整，记录每个值对应的 eval 分数与拒答率，选最佳折中值

### D7. 拒答走 SSE 同路径，不另开端点

- `orchestrator.retrieve_and_rerank(question)` 在 `max(rerank_score) < RERANK_THRESHOLD` 时返回空 list
- `qa_stream.py` 判断 `if not chunks:` 则发一条 `data: {"answer": "抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。"}\n\n` + `data: {"sources": []}\n\n` 然后 close
- 不抛 HTTP 错误码（前端不处理非 200 的 SSE）

### D8. 文件名策略：沿用 TS 版 sanitize + 冲突后缀

抄 TS 版 `backend/chunking-rag/src/routes/filename-utils.ts` 的实现，Python 重写为 `app/filename_utils.py`：
- `fix_encoding(name)`：latin1 乱码修正 → utf-8
- `sanitize_filename(name)`：清非法字符（保留中文）
- 冲突加 `_1` `_2` 后缀——**原子创建**：用 `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` 拿 fd，失败（`FileExistsError`）则加后缀重试。这**不是**"先 `os.path.exists` 探测再写"（TOCTOU 竞态），而是内核级原子 `create-or-fail`；拿到 fd 后才 write bytes
- 写 bytes 失败（磁盘满 / upload stream 中断）：必须 `os.unlink(path)` 删掉 0 字节/部分写入文件，避免 raw 孤儿 + 下次同名上传被 `_1` 误后缀
- **`files.original_name` = 磁盘文件名 = 前端 DELETE 的 key**，一处生成处处一致

### D9. SQLite schema：TS 版同 schema，chunks 单表 + vector JSON 列

见 §7。chunks 表只保留 `vector TEXT`（JSON 数组，1024 维 float），不拆 chunk_versions（v2 feature）。

### D10. 上传失败显式状态机，不留孤儿 DB 态

对标 TS 版 [upload.ts:88-123](../../../backend/chunking-rag/src/routes/upload.ts)：
- INSERT files(status='converting') **在** parse/chunk/embed **之前**完成——父记录是所有后续失败的 DB 归属点
- 成功路径：chunks 写入 + UPDATE status='completed' 在同一逻辑事务里
- 失败路径：UPDATE status='failed'（失败再失败只 log，不递归抛）；raw/converted/mapping 文件**保留**（与 TS 版一致，供重试/排查）
- HTTP 码：逐文件 `files[].status='completed'|'failed'` 区分，整体返回 200；入参非法才返回 400/413
- GC：与 TS 版 D3 一致，不做启动/周期性清理，留到后续版本

**为什么不事务化文件系统**：SQLite + FS 跨原子操作不可能——TS 版 D3 已经接受 best-effort + 日志。Python 版沿用同口径。

### D11. 端口冲突：README 明确"先 kill 3002"

```bash
# 3002 端口占用时清理（无进程也不报错）
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true

cd backend/chunking-rag-py
conda activate sqllineage
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 3002
```

---

## 6. 数据流

### 6.1 上传（`POST /api/upload`）

对标 TS 版 [upload.ts:88-123](../../../backend/chunking-rag/src/routes/upload.ts) 的 `converting → completed / failed` 状态机（TS 版注释原话："防止出现 completed + chunks=0 灰态"）。失败时 DB 必须留下 `status='failed'` 记录，不能产生"raw 有文件但 DB 无记录"的孤儿态。

**限额实现**（FastAPI/python-multipart 不会自动套用 multer 的 `limits`，必须显式写）：
- **文件数 ≤ 10**：`files: list[UploadFile] = File(...)` 解析完 `len(files)` 检查，>10 直接 413 + `{success:false, message:"最多 10 个文件"}`
- **单文件 ≤ 50MB**：**不能**依赖 `file.size`（UploadFile 在 streaming 流式下可能为 None 或不准）。必须**流式写 + 累计字节**：

  ```python
  MAX_BYTES = 50 * 1024 * 1024
  fd = os.open(raw_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
  written = 0
  try:
      while chunk := await upload.read(64 * 1024):
          written += len(chunk)
          if written > MAX_BYTES:
              os.close(fd); os.unlink(raw_path)
              raise HTTPException(413, detail=f"{upload.filename} 超过 50MB")
          os.write(fd, chunk)
  finally:
      try: os.close(fd)
      except OSError: pass
  ```
- **非法 multipart**（解析失败）：FastAPI 自己返回 422；不覆盖此行为
- **顺序**：limits 检查在 INSERT files(status='converting') **之前**——限额失败不留 DB 记录

每个上传文件逐个处理（单请求内**顺序**，不并行——见 D4）：

```
multipart → FastAPI UploadFile
  │
  ▼ [filename_utils] sanitize + 冲突后缀 → safe_name
  │
  ▼ 写入 storage/raw/{safe_name}  (失败 → 跳过该文件，加入响应 files[] 的 failed 记录，继续下一个)
  │
  ▼ [database] INSERT files (
       id=uuid4, original_name=safe_name, original_path=..., converted_path='',
       format=ext, size, upload_time=now, status='converting', category='', tags=NULL
     )   — 父表先落地，父记录 = 后续所有失败状态的归属
  │
  ▼ try:
  │    [converter/parser] 按扩展名分派 → markdown + line_map
  │        .pdf  → PyMuPDF (fitz) → 文本 + 页码
  │        .docx → python-docx → 段落 + 标题
  │        .pptx → python-pptx → 幻灯片标题 + 内容
  │        .xlsx → openpyxl → 表格 → markdown 表格语法
  │        .md   → 直读 + 空 line_map
  │    写入 storage/converted/{file_id}.md + storage/mappings/{file_id}.json
  │    UPDATE files SET converted_path=? WHERE id=?
  │    [converter/chunker] markdown + line_map → Chunk[]
  │    [embedder.bge_m3] batch encode → vectors (N × 1024)
  │    [database] 单事务（`with write_tx(conn):` — 见 D4）：
  │        INSERT chunks × N (vector=JSON.dumps(v))
  │        UPDATE files SET status='completed' WHERE id=?
  │
  ▼ except Exception as e:
  │    [database] UPDATE files SET status='failed' WHERE id=?  (更新失败仅 log.warn，不再抛)
  │    raw 文件保留（支持重试/人工排查，与 TS 版一致）
  │    converted/mapping 若已写入则保留（与 TS 版一致；delete 路径会级联清理）
  │    响应 files[] 加入 {id, originalName, status:'failed', error: str(e)}
  │
  ▼ 响应 {success:true, files:[...所有文件的 {id, originalName, format, size, status, [error]} ], message:"成功 X/Y"}
```

**HTTP 状态码**：只要入参合法（multipart 解析成功、文件数≤10、单文件≤50MB），**始终返回 200**——逐文件成败靠 `files[].status` 区分，整体不抛 5xx。入参非法（multipart 解析失败、超限）时返回 400/413，响应体 `{success:false, message:"..."}`（对标 TS 版）。

### 6.2 问答流式（`POST /api/qa/ask-stream`）

```
{question, topK=5}
  │
  ▼ [retriever/dense] embedder.encode(question) → q_vec
  │                  load all chunks' vectors → numpy → cosine top 20
  │
  ▼ [retriever/bm25] jieba(question) → rank_bm25 top 20
  │
  ▼ [retriever/rrf] 融合 → top 20
  │
  ▼ [retriever/reranker] FlagReranker 打分 → scored
  │
  ▼ max(score) < 0.4 ？
     yes → SSE 拒答 + sources=[] → end
     no  → 取 score ≥ 0.4 的前 5 条
  │
  ▼ [qa/prompt] 拼 prompt（含 chunk 前 500 字符）
  │
  ▼ [llm/client] openai stream chat completion
  │
  ▼ for async token: SSE data: {"answer": token}
  │
  ▼ SSE data: {"sources": [去重 filename]}
  │
  ▼ res.end()
```

### 6.3 删除（`DELETE /api/qa/files/{filename}`）

```
filename (URL decoded)
  │
  ▼ 路径穿越校验（resolve + startswith check）
  │
  ▼ [database] matches = SELECT * FROM files WHERE original_name = filename
  │   （理论唯一，防御性写成 list；matches 为空且 raw 文件也不存在 → 404）
  │
  ▼ with write_tx(conn):  # 见 D4
  │     for row in matches:
  │         DELETE FROM chunks WHERE file_id=row.id
  │         DELETE FROM files WHERE id=row.id
  │   (事务失败 → 500，不继续后续步骤)
  │
  ▼ os.unlink(storage/raw/{filename})
  │   (失败 → warn，继续)
  │
  ▼ for row in matches:
  │   os.unlink(storage/converted/{row.id}.md)
  │   os.unlink(storage/mappings/{row.id}.json)
  │   (失败 → warn，继续)
  │
  ▼ 响应 {success: true, message: "..."}
```

best-effort + 日志，不做跨 DB+FS 事务回滚（对标 TS 版 D3 决策）。

---

## 7. SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS files (
  id              TEXT PRIMARY KEY,       -- uuid4 str
  original_name   TEXT NOT NULL,          -- sanitize 后的磁盘文件名（= DELETE 的 key）
  original_path   TEXT NOT NULL,          -- 绝对或相对 storage/raw/ 路径
  converted_path  TEXT NOT NULL,          -- storage/converted/{id}.md
  format          TEXT NOT NULL,          -- 'pdf'|'docx'|'pptx'|'xlsx'|'md'
  size            INTEGER NOT NULL,       -- bytes
  upload_time     TEXT NOT NULL,          -- ISO8601
  category        TEXT DEFAULT '',
  status          TEXT NOT NULL,          -- 'converting'|'completed'|'failed' （与 TS 版一致）
  tags            TEXT                    -- JSON array 或 NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id              TEXT PRIMARY KEY,       -- uuid4
  file_id         TEXT NOT NULL,
  content         TEXT NOT NULL,          -- 切分后纯文本
  start_line      INTEGER NOT NULL,
  end_line        INTEGER NOT NULL,
  original_lines  TEXT NOT NULL,          -- JSON: 映射回原文件的行号数组
  vector          TEXT,                   -- JSON: float[1024]（bge-m3 dense），indexing 失败时为 NULL
  FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
```

**与 TS 版 schema 完全一致**（TS 版也是单表 + vector JSON）。Python 版 `sqlite3` 手写 row → dict 映射，没有 ORM。

**统计口径**：`getStats().fileCount` 只数 `status='completed'`，和 `GET /api/qa/files` 列表长度一致（抄 TS 版 [database/index.ts:306](../../../backend/chunking-rag/src/database/index.ts)）。

---

## 8. 模块职责

| 模块 | 职责 | 不做 |
|---|---|---|
| `app/main.py` | FastAPI 实例；lifespan 初始化 embedder/reranker/db；CORS；注册 routers | 业务逻辑 |
| `app/config.py` | pydantic-settings 读 `.env`（PORT, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, RERANK_MODEL, RERANK_THRESHOLD, DB_PATH, RAW_DIR, CONVERTED_DIR, MAPPINGS_DIR） | — |
| `app/deps.py` | `get_db()` / `get_embedder()` / `get_reranker()` / `get_settings()` | — |
| `app/routes/upload.py` | #1 #2 端点；sanitize 文件名；单请求内**逐文件顺序**转换+切分+embed；converting→completed/failed 状态机；写 DB | 不直接调 LLM；不并行处理多文件（见 D4） |
| `app/routes/qa.py` | #3 #4 #6 端点；stats 计算；DELETE 级联 | 不做问答 |
| `app/routes/qa_stream.py` | #5 SSE；把 orchestrator 的 async generator 包成 StreamingResponse | 不做检索逻辑 |
| `app/converter/parser.py` | 5 种格式 → markdown + line_map；一个 `parse(path) -> (str, dict)` 入口 | 切分 |
| `app/converter/chunker.py` | markdown + line_map → `list[Chunk]`；14 个单测 | embedding |
| `app/embedder/bge_m3.py` | `class BgeM3Embedder` 封装 `FlagEmbedding.BGEM3FlagModel`；`.encode(texts) -> np.ndarray[N, 1024]` 内部调 `model.encode(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)['dense_vecs']`；所有 encode 调用在 `model_lock` 内 | sparse/colbert |
| `app/retriever/dense.py` | `dense_search(q_vec, chunks, k=20) -> list[(chunk, score)]` 纯 numpy | 持久化索引 |
| `app/retriever/bm25.py` | `bm25_search(query, chunks, k=20)`，内部 jieba + rank_bm25 即时建 index | 持久化 |
| `app/retriever/rrf.py` | `rrf_fuse(lists, k=60) -> list[chunk]` 纯函数 | — |
| `app/retriever/reranker.py` | `class BgeReranker` 封装 `FlagReranker`，`.score(q, docs) -> list[float]` `normalize=True`；调用在 `model_lock` 内 | — |
| `app/qa/orchestrator.py` | `retrieve_and_rerank(question) -> list[Chunk]`；阈值门控 | LLM 调用 |
| `app/qa/prompt.py` | `build_prompt(question, chunks) -> str`；TS 版同款模板 | — |
| `app/llm/client.py` | `async def stream_answer(prompt) -> AsyncIterator[str]`；openai SDK + 亚信 base_url | 重试/缓存 |
| `app/database/sqlite.py` | `class Db`：schema 初始化 + 所有 CRUD；外部只通过这层访问 SQLite | 业务决策 |
| `app/filename_utils.py` | `fix_encoding` / `sanitize_filename` / `dedupe_filename`；对标 TS 版 | — |
| `app/sse.py` | `def sse_event(data: dict) -> str` 一个 helper | — |

---

## 9. 测试策略

### 9.1 pytest 约定

- 框架：`pytest` + `pytest-asyncio`（`asyncio_mode=auto`）
- 配置：`pyproject.toml` 或 `pytest.ini`
- 命令：`pytest -v tests/`
- 验收基准：**所有单测 PASS**，且 e2e 的 6 端点冒烟全绿

### 9.2 关键单测清单

#### 9.2.1 单元测试

| 文件 | 用例数 | 关键 case |
|---|---|---|
| `test_chunker.py` | 14 | 单段超长切、标题边界、空行合并、代码块保护、短段 fallback、line_map 对齐、中文、混合段落/标题、空输入、只有标题无内容、嵌套标题、尾部不完整段、连续空行、Unicode |
| `test_filename_utils.py` | 7 | latin1 乱码修复、非法字符清洗、保留中文、冲突加 `_1`/`_2` 递增、空扩展名、`O_EXCL` 原子创建（同名竞态） |
| `test_sqlite.py` | 10 | schema 幂等、insert/get/update/delete files 往返、chunks 级联删、vector JSON 往返、stats 只计 completed、searchChunks LIKE、WAL 模式生效、`converting→completed/failed` 状态转换 |
| `test_bm25.py` | 3 | 中文分词召回、排序合理、空查询 |
| `test_rrf.py` | 3 | 两路完全重合、完全不重合、部分重合排序符合预期 |
| `test_dense_retriever.py` | 2 | mock embedder：top-k 返回值、score 降序 |

#### 9.2.2 契约 / 端到端 / 鲁棒性测试

| 文件 | 用例 | 说明 |
|---|---|---|
| `test_contract_snapshot.py` | 6 × 2 = 12 | 对每个端点：(a) 记录 TS 版响应（预先抓取并 checkin 到 `tests/fixtures/ts_responses/`）；(b) FastAPI 响应 → 提取前端实际读取的字段做**字段级等价比对**（不比 header、不比 JSON key 顺序）。锁定契约：`/qa/stats` 的 `data.totalFiles`；`/qa/files` 和 `/upload/raw-files` 的 list 元素字段；`/upload` 的 `success/files/message`；SSE 事件的 `data.answer`/`data.sources` shape |
| `test_cors.py` | 2 | 对标 TS 版 `app.use(cors())` 的**默认 allow-all** 语义：OPTIONS preflight 返回 204 + `Access-Control-Allow-Origin: *`（或回显请求 origin）+ 允许 `GET/POST/DELETE/OPTIONS` 方法；实际 GET 带任意 `Origin` 头不被拒绝。**不测**"未配置 origin 拒绝"——TS 版不做此限制，Python 版要保持语义一致 |
| `test_upload_limits.py` | 3 | 单文件 > 50MB → 413 + `{success:false, message}`；文件数 > 10 → 413 或 400；空 multipart → 400 |
| `test_upload_failure.py` | 4 | 转换失败：DB 留 `status='failed'` + raw 保留 + 响应 `files[].status='failed'`；chunking 失败同上；embedding 失败同上；状态流转 `converting→failed` 被覆盖 |
| `test_concurrent_upload.py` | 2 | 两个并发请求上传同名 `foo.md`：`O_EXCL` 保证各自拿到 `foo.md` 和 `foo_1.md`；DB `original_name` 唯一映射 |
| `test_qa_empty_db.py` | 2 | 空库问答：SSE 发拒答文案 + `sources=[]`；无 chunks 时 reranker 不被调用 |
| `test_sse_framing.py` | 2 | 长回答（>100 token）SSE 流解析无丢字；手动构造跨包边界的 `chunk.split('\n')` 输入下前端解析器（test 内 port 实现）行为 ≥ TS 版 |
| `test_upload_qa_e2e.py` | 6 | TestClient 跑通 6 个端点（embedder/reranker/llm 全 mock）；SSE 解析；DELETE 级联；路径穿越 400 |

**不测**：embedder/reranker 真实模型加载（吃资源，靠 eval 集验证）；真实 LLM 调用（靠 mock `openai` client）；前端本体（0 修改）。

**TS 响应快照的抓法**：一次性脚本 `scripts/capture_ts_snapshots.py`——启动 TS 版服务，喂固定 fixture（`tests/fixtures/sample.md` 等），`requests.get/post` 抓响应存 JSON 到 `tests/fixtures/ts_responses/`。plan 阶段写这个脚本并 checkin 结果。

### 9.3 eval 集跑法（feature 完成后）

- 用团队统一 eval 脚本（脚本路径由团队提供，本 spec 不把脚本接入列为实现任务——plan 阶段若团队路径已明确再补接入步骤）
- 启动服务：`uvicorn app.main:app --port 3002`
- 对比基线：TS 版 40/100 → Python 版 target 72–80/100
- 每次 tuning（调 `RERANK_THRESHOLD`、`top_k`、chunk 大小）重跑一次并记录

---

## 10. 不在本次范围

对照 `docs/layer1-design-v2.md`（章节号对齐该文档实际目录），明确砍掉：

| v2 要做的 | 对应 v2 章节 | 本 spec 不做，理由 |
|---|---|---|
| content_type = code / structured_data 分支 chunking | §4.2.2 / §4.2.3 | MVP 只做 document（§4.2.1）分支 |
| char_offset anchor（Chunk 数据结构扩展字段） | §4.2.4 | 沿用 v1 的 start_line/end_line |
| chunks + chunk_versions 双表（版本化） | §4.3 / §4.3.1 | 单表 chunks（no 版本化） |
| 增量更新 pipeline + 5min SLA | §4.4 / §4.5 | 上传同步触发 indexing，无文件监听 |
| LibreOffice 旧版 Office 格式 | §4.1.2 | 只支持 .docx/.xlsx/.pptx 新格式 |
| PaddleOCR 扫描件识别 | §7 Q3（待定项） | 不做 |
| WebSocket 进度推送 | §5.2 | 上传同步返回 |
| bge-m3 sparse + colbert 多输出融合 | §7 Q1（待定项） | 只用 dense（降低复杂度和 VRAM） |
| sqlite-vec 向量索引升级 | §7 Q4（待定项） | 继续用 vector JSON 列（chunk 数 < 5000 够用） |
| Layer 1 ↔ Layer 2 检索契约（Python 微服务拆分） | §5.1 / §5.3 | 单进程 FastAPI，不拆 Node/Python 双服务 |

上述全部列入"v2 升级路径"，本次不碰。

---

## 11. 已知风险

### R1. bge-m3 / reranker 首次加载慢且吃内存

- FlagEmbedding 首次运行会从 HuggingFace Hub 下载（bge-m3 ~2.3GB，reranker-v2-m3 ~1.1GB）
- 加载进显存 / 内存峰值 ~4GB
- **缓解**：
  - README 写明"首次启动等 5 分钟"
  - 提前跑 `from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)` 预热 HF cache
  - 设备自动选择：FlagEmbedding 默认检测到 CUDA 就走 GPU，无则 CPU（CPU 性能下降可接受，MVP 演示够）

### R2. 前端 SSE 跨 TCP 分帧 bug（TS 版继承的已知问题）

- 前端 [page.tsx:211-224](../../../frontend/app/page.tsx) `chunk.split('\n')` 不做跨 chunk buffer——TCP/代理把单个 `data: ...\n\n` 切在中间则丢字
- 单 event ~50 字节远小于 TCP MSS 1460，本地演示场景 P(出现) 极低
- **缓解**：服务端送 `X-Accel-Buffering: no` + `async def gen()` 每 token 一 yield（见 §4 SSE 代码块）——**这不能消除**跨包 bug，只降低进入缓冲的概率
- **本质无解的理由**：只要前端不做 buffer 就无根治方案；`anyio.sleep(0)` 只释放事件循环，**对 TCP/proxy 分帧零保障**（v1 spec 错误认知，已从 §4 删除）
- **接受风险**：MVP 演示实测未出；若后续高频触发，下一迭代改前端加 buffer（跳出"前端 0 修改"约束）

### R3. 并发写 SQLite（D4 方案的剩余风险）

- D4 方案：每请求独立连接 + WAL + `BEGIN IMMEDIATE` + `busy_timeout=10000`
- **同名上传竞态**：D8 用 `O_CREAT|O_EXCL` 原子创建消除——**不再是剩余风险**
- **剩余风险**：WAL 文件锁超时（`sqlite3.OperationalError: database is locked`，10s 超时仍失败）
  - 触发场景：极端并发（上传 + 大批量 DELETE 同时跑）或磁盘异常
  - 处理：让 500 抛出，由前端重试

### R4. eval 集达不到 72 分

- 72–80 是 brainstorm 基于经验估算，未实测
- **缓解**：feature 完成后留 9 天 tuning（chunk 大小、top_k、RERANK_THRESHOLD、prompt）
- **降级路径**：若 Day 15 仍 < 65，在 orchestrator 里加一个 keyword-expansion 前置（同义词词典或 LLM 改写），不在本 spec 范围但可快速补

### R5. 二选一端口占用导致演示事故

- 演示时 TS 版和 Python 版都不能同时跑
- **缓解**：README 写 `pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true`（POSIX 可移植，BSD/GNU xargs 差异无关，无进程时静默退出）作为启动前置步骤
- **剩余风险**：演示现场端口抢占看现场纪律

### R6. 团队 main 分支与个人 owner 分支漂移

- `docs/layer1-design-v2.md` 可能在本 spec 实现期间被团队更新
- **缓解**：不修改该文档；若团队明确某个 v2 feature 纳入 MVP 必须做，新开 spec 讨论 scope 变更

### R7. FlagEmbedding / torch 并发调用安全性未验证

- HF + torch 推理路径**通常**对 read-only 权重线程安全，但 FlagEmbedding 的 wrapper 维护了 tokenizer 状态、batch buffer、可能的 kv cache，**未**官方保证多线程并发
- FastAPI threadpool 下多个请求可能同时调 `embedder.encode` / `reranker.score`
- **缓解**：D4 定义的 `app.state.model_lock = threading.Lock()`，所有模型调用在 `with model_lock:` 内串行化——MVP 性能影响可接受（推理本身毫秒级，排队开销小）
- **剩余风险**：lock 造成并发 QPS 上限 = 1 / 单次推理耗时。bge-m3 CPU 推理 ~200ms 意味着 QPS ≤ 5。演示场景够用，真实高并发需要：
  - 方案 A：复制多个模型实例 + semaphore（VRAM/RAM 翻倍）
  - 方案 B：换成异步 batch 推理服务（超出 MVP 范围）
- **退出 lock 的触发条件**：plan 完成后实测 FlagEmbedding 无锁并发若不出错且有稳定收益，再考虑去除 lock；默认保留

---

## 附录 A：依赖清单（`requirements.txt`）

全部 **pin 到精确版本**——避免 `>=` 在冷启动时拉到未验证的新版破坏兼容性。数值是 brainstorm 时的合理起点，plan 的第一个实施任务是冷启动验证（见 §附录 C）：

```
# Web 框架
fastapi==0.115.5
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
python-multipart==0.0.18

# LLM 客户端
openai==1.57.0

# Embedding & Rerank（FlagEmbedding 会间接拉 torch，torch 和 numpy 版本耦合）
FlagEmbedding==1.3.4

# 检索
rank-bm25==0.2.2
jieba==0.42.1

# 数值计算（注意：FlagEmbedding/torch 对 numpy 2.x 支持情况需冷启动验证）
numpy==1.26.4

# 文档解析
PyMuPDF==1.25.1
python-docx==1.1.2
python-pptx==1.0.2
openpyxl==3.1.5

# 测试
pytest==8.3.4
pytest-asyncio==0.24.0
httpx==0.27.2
```

Python **3.12.4**（conda env `sqllineage`）。依赖管理 `pip install -r requirements.txt`（不用 uv）。

## 附录 C：冷启动验证清单（plan 的 Task 1）

写任何业务代码之前，先在干净 env 里跑通依赖解析 + 模型首次加载。任一失败就更新 `requirements.txt` 的对应 pin：

```bash
cd backend/chunking-rag-py                # 所有后续命令都在 service root
conda activate sqllineage
python --version                                # 必须 3.12.4
pip install -r requirements.txt                 # 必须零冲突
python -c "from FlagEmbedding import BGEM3FlagModel; m = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True); out = m.encode(['hello'], return_dense=True, return_sparse=False, return_colbert_vecs=False); print(out['dense_vecs'].shape)"  # 期望 (1, 1024)
python -c "from FlagEmbedding import FlagReranker; r = FlagReranker('BAAI/bge-reranker-v2-m3'); print(r.compute_score([('q','d')], normalize=True))"
python -c "import fitz, docx, pptx, openpyxl, jieba; from rank_bm25 import BM25Okapi; print('parsers + bm25 OK')"
python -c "import fastapi, uvicorn, pydantic, pydantic_settings; print('web OK')"
uvicorn app.main:app --port 3002 &              # 不需要真实路由实现，仅验证 app import
sleep 2; curl -s http://localhost:3002/health || true
kill %1
```

全部 PASS 后再开 Task 2。

## 附录 B：.env.example

所有 `*_DIR` / `DB_PATH` 环境变量值为**相对路径**时，`config.py` 解析为**相对服务根**（即 `backend/chunking-rag-py/`），不依赖启动 cwd：

```python
# app/config.py 关键片段
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parent.parent  # app/config.py → app/ → chunking-rag-py/

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVICE_ROOT / ".env"),   # 绝对路径，不受启动 cwd 影响
        env_file_encoding="utf-8",
    )
    port: int = 3002
    ...
    db_path: Path = Path("storage/knowledge.db")

    def resolve_path(self, p: Path) -> Path:
        return p if p.is_absolute() else (SERVICE_ROOT / p).resolve()
```

路由/服务里使用时一律 `settings.resolve_path(settings.db_path)`，不要直接用 raw 值。

`.env.example` 内容：

```
PORT=3002
HOST=0.0.0.0

LLM_API_KEY=<亚信网关 key>
LLM_BASE_URL=https://<亚信网关>/v1
LLM_MODEL=<团队指定模型>

EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_THRESHOLD=0.4

# 所有下列路径按 service root 相对解析，不受启动 cwd 影响
DB_PATH=storage/knowledge.db
RAW_DIR=storage/raw
CONVERTED_DIR=storage/converted
MAPPINGS_DIR=storage/mappings

LOG_LEVEL=INFO
```
