# Chunking RAG Python 重写设计

**日期**：2026-04-23
**状态**：Spec（brainstorm 2026-04-23 敲定，待写 plan）
**作者**：tuyh3（个人 owner 分支，与团队 main 平行）

---

## 1. 背景与关联文档

### 1.1 TS 版（已 ship）

- 路径：`services-tuyh/chunking-rag/`（TypeScript，Express，端口 3002）
- 状态：已合进 `origin/main`（16 commits，9/9 e2e PASS）
- Eval baseline：**40/100**（团队统一测题集）
- Spec：[2026-04-23-chunking-rag-service-design.md](./2026-04-23-chunking-rag-service-design.md)
- 6 个前端端点全部可用，存储自包含在 `services-tuyh/chunking-rag/storage/`

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
2. **前端 0 修改**：6 个端点契约和 TS 版字节级一致（见 §4）
3. **二选一占 3002 端口**：和 TS 版互斥启动，不做反向代理
4. **存储完全自包含**：`services-tuyh/chunking-rag-py/storage/`（与 TS 版 storage 隔离，允许并存）

### 2.2 非目标

- 替换 TS 版：TS 版作为 fallback 保留在仓库，两版同时存在
- 和同事 `backend/` 集成：两服务并存靠端口约定，不共享数据
- 改动 `frontend/`：一行不动
- 修改团队 `docs/layer1-design-v2.md`
- 实现 v2 文档里的 char_offset anchor、content_type 三类分派、增量更新 pipeline（见 §10）

---

## 3. 架构

### 3.1 目录布局

```
TechnicalDocumentationCitationSystem/
├── backend/                       ⬅ 同事（文件管理 demo，不碰）
├── frontend/                      ⬅ 同事（硬编码 localhost:3002，不碰）
├── docs/
│   ├── layer1-design-v2.md        ⬅ 团队文档（只读参考）
│   └── superpowers/specs/
│       ├── 2026-04-23-chunking-rag-service-design.md   (TS 版)
│       └── 2026-04-23-chunking-rag-py-design.md        (本 spec)
└── services-tuyh/
    ├── chunking-rag/              ⬅ TS 版（已 ship，端口 3002）
    └── chunking-rag-py/           ⬅ Python 版（本 spec，端口 3002，与 TS 二选一）
        ├── requirements.txt
        ├── .env.example
        ├── README.md
        ├── pyproject.toml         (可选，只配 ruff/pytest)
        ├── app/
        │   ├── __init__.py
        │   ├── main.py            FastAPI app entry，lifespan 初始化 embedder/reranker
        │   ├── config.py          pydantic-settings
        │   ├── deps.py            FastAPI Depends 工厂（db / embedder / reranker 单例）
        │   ├── routes/
        │   │   ├── __init__.py
        │   │   ├── upload.py      POST /api/upload, GET /api/upload/raw-files
        │   │   ├── qa.py          GET /api/qa/files, /api/qa/stats, DELETE /api/qa/files/{name}
        │   │   └── qa_stream.py   POST /api/qa/ask-stream (SSE)
        │   ├── converter/
        │   │   ├── __init__.py
        │   │   ├── parser.py      各格式 → markdown + line_map (pdf/docx/pptx/xlsx/md)
        │   │   └── chunker.py     markdown → Chunk[]（单段落/标题切，保留 line 范围）
        │   ├── embedder/
        │   │   ├── __init__.py
        │   │   └── bge_m3.py      FlagEmbedding BGEM3FlagModel 封装（dense-only）
        │   ├── retriever/
        │   │   ├── __init__.py
        │   │   ├── dense.py       numpy 余弦相似度 top-k
        │   │   ├── bm25.py        rank_bm25 + jieba，每次查询在内存里重建 index
        │   │   ├── rrf.py         RRF 融合两路 ranked list
        │   │   └── reranker.py    FlagReranker 封装
        │   ├── qa/
        │   │   ├── __init__.py
        │   │   ├── orchestrator.py  组合检索 + 重排 + 阈值门控
        │   │   └── prompt.py        prompt 模板
        │   ├── llm/
        │   │   ├── __init__.py
        │   │   └── client.py        openai SDK + 亚信网关（stream/non-stream）
        │   ├── database/
        │   │   ├── __init__.py
        │   │   └── sqlite.py        sqlite3 stdlib + schema + CRUD
        │   ├── filename_utils.py    sanitize / fix_encoding / 冲突加后缀（抄 TS 版）
        │   └── sse.py               SSE 事件编码 util
        ├── tests/
        │   ├── conftest.py
        │   ├── test_chunker.py
        │   ├── test_filename_utils.py
        │   ├── test_sqlite.py
        │   ├── test_bm25.py
        │   ├── test_rrf.py
        │   ├── test_dense_retriever.py     (mock embedder)
        │   └── test_upload_qa_e2e.py       (TestClient，mock embedder/reranker/llm)
        └── storage/
            ├── raw/                原文件
            ├── converted/          转换后 .md
            ├── mappings/           line_map .json
            └── knowledge.db        SQLite
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

前端硬编码 `NEXT_PUBLIC_API_URL=http://localhost:3002`。本服务响应必须与 TS 版**字节级**一致（已在 TS 版 e2e 验证过）。

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
- 每条后调 `await response.send(...)` flush（FastAPI StreamingResponse + `async def` generator）

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

### D4. 单进程 FastAPI + 模型常驻内存（lifespan）

- `app.main` 里 `@asynccontextmanager lifespan`：启动加载 bge-m3（~2GB VRAM/RAM）+ reranker（~600MB），放 `app.state`
- 路由通过 `Depends(get_embedder)` / `Depends(get_reranker)` 拿单例
- 不做 worker 池 / 任务队列（MVP 串行，上传大文件会阻塞，acceptable）
- DB 用 `sqlite3.connect(check_same_thread=False)` + 单连接，写操作靠 FastAPI 单进程默认串行

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

- **dense 检索**：所有 chunks 的 vector 字段存 JSON，查询时 load 进 numpy 算一次全量余弦（chunk 数 < 5000 不优化）
- **BM25**：每次查询前从 DB load 所有 chunk.content，jieba 分词，`rank_bm25.BM25Okapi` 即时建 index 算分（~50ms @ 1000 chunks，acceptable）
- **RRF**：`score = Σ 1/(k + rank_i)`，k=60 行业默认
- **Reranker**：`FlagReranker` 对 (question, chunk.content) 批量打分，normalize=True → [0,1]
- **阈值 0.4**：brainstorm 定的硬数字，留一个 env var `RERANK_THRESHOLD` 方便 eval 调

### D7. 拒答走 SSE 同路径，不另开端点

- `orchestrator.retrieve_and_rerank(question)` 在 `max(rerank_score) < RERANK_THRESHOLD` 时返回空 list
- `qa_stream.py` 判断 `if not chunks:` 则发一条 `data: {"answer": "抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。"}\n\n` + `data: {"sources": []}\n\n` 然后 close
- 不抛 HTTP 错误码（前端不处理非 200 的 SSE）

### D8. 文件名策略：沿用 TS 版 sanitize + 冲突后缀（D2b）

抄 TS 版 `services-tuyh/chunking-rag/src/routes/filename-utils.ts` 的实现，Python 重写为 `app/filename_utils.py`：
- `fix_encoding(name)`：latin1 乱码修正 → utf-8
- `sanitize_filename(name)`：清非法字符（保留中文）
- 冲突加 `_1` `_2` 后缀
- **`files.original_name` = 磁盘文件名 = 前端 DELETE 的 key**，一处生成处处一致

### D9. SQLite schema：TS 版同 schema，chunks 单表 + vector JSON 列

见 §7。chunks 表只保留 `vector TEXT`（JSON 数组，1024 维 float），不拆 chunk_versions（v2 feature）。

### D10. 端口冲突：README 明确"先 kill 3002"

```bash
lsof -ti:3002 | xargs kill -9  # 停掉 TS 版或同事 backend
cd services-tuyh/chunking-rag-py
conda activate sqllineage
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 3002
```

---

## 6. 数据流

### 6.1 上传（`POST /api/upload`）

```
multipart → FastAPI UploadFile
  │
  ▼ [filename_utils] sanitize + 冲突后缀 → safe_name
  │
  ▼ 写入 storage/raw/{safe_name}
  │
  ▼ [converter/parser] 按扩展名分派：
     .pdf  → PyMuPDF (fitz) → 文本 + 页码 → markdown + line_map
     .docx → python-docx → 段落 + 标题 → markdown + line_map
     .pptx → python-pptx → 幻灯片标题 + 内容 → markdown
     .xlsx → openpyxl → 表格 → markdown 表格语法
     .md   → 直读 + 空 line_map
  │
  ▼ 写入 storage/converted/{file_id}.md 和 storage/mappings/{file_id}.json
  │
  ▼ [converter/chunker] markdown + line_map → Chunk[]
  │
  ▼ [embedder.bge_m3] batch encode → vectors (N × 1024)
  │
  ▼ [database] 事务写入：
     INSERT files (status='completed')
     INSERT chunks (vector=JSON.dumps(v)) × N
  │
  ▼ 响应 {success, files:[...], message}
```

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
  ▼ for row in matches:
  │   事务：DELETE FROM chunks WHERE file_id=row.id; DELETE FROM files WHERE id=row.id;
  │   (任一事务失败 → 500，不继续后续步骤)
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
  status          TEXT NOT NULL,          -- 'processing'|'completed'|'failed'
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

**统计口径**：`getStats().fileCount` 只数 `status='completed'`，和 `GET /api/qa/files` 列表长度一致（抄 TS 版 [database/index.ts:306](../../../services-tuyh/chunking-rag/src/database/index.ts)）。

---

## 8. 模块职责

| 模块 | 职责 | 不做 |
|---|---|---|
| `app/main.py` | FastAPI 实例；lifespan 初始化 embedder/reranker/db；CORS；注册 routers | 业务逻辑 |
| `app/config.py` | pydantic-settings 读 `.env`（PORT, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL, RERANK_MODEL, RERANK_THRESHOLD, DB_PATH, RAW_DIR, CONVERTED_DIR, MAPPINGS_DIR） | — |
| `app/deps.py` | `get_db()` / `get_embedder()` / `get_reranker()` / `get_settings()` | — |
| `app/routes/upload.py` | #1 #2 端点；sanitize 文件名；多文件并行转换+切分+embed；写 DB | 不直接调 LLM |
| `app/routes/qa.py` | #3 #4 #6 端点；stats 计算；DELETE 级联 | 不做问答 |
| `app/routes/qa_stream.py` | #5 SSE；把 orchestrator 的 async generator 包成 StreamingResponse | 不做检索逻辑 |
| `app/converter/parser.py` | 5 种格式 → markdown + line_map；一个 `parse(path) -> (str, dict)` 入口 | 切分 |
| `app/converter/chunker.py` | markdown + line_map → `list[Chunk]`；14 个单测 | embedding |
| `app/embedder/bge_m3.py` | `class BgeM3Embedder` 封装 `FlagEmbedding.BGEM3FlagModel`，`.encode(texts: list[str]) -> np.ndarray[N, 1024]`，dense-only | sparse/colbert |
| `app/retriever/dense.py` | `dense_search(q_vec, chunks, k=20) -> list[(chunk, score)]` 纯 numpy | 持久化索引 |
| `app/retriever/bm25.py` | `bm25_search(query, chunks, k=20)`，内部 jieba + rank_bm25 即时建 index | 持久化 |
| `app/retriever/rrf.py` | `rrf_fuse(lists, k=60) -> list[chunk]` 纯函数 | — |
| `app/retriever/reranker.py` | `class BgeReranker` 封装 `FlagReranker`，`.score(q, docs) -> list[float]` normalize=True | — |
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

| 文件 | 用例数 | 关键 case |
|---|---|---|
| `test_chunker.py` | 14 | 单段超长切、标题边界、空行合并、代码块保护、短段 fallback、line_map 对齐、中文、混合段落/标题、空输入、只有标题无内容、嵌套标题、尾部不完整段、连续空行、Unicode |
| `test_filename_utils.py` | 6 | latin1 乱码修复、非法字符清洗、保留中文、冲突加 `_1`、`_2` 递增、空扩展名 |
| `test_sqlite.py` | 8 | schema 幂等、insert/get/update/delete files 往返、chunks 级联删、vector JSON 往返、stats 只计 completed、searchChunks LIKE |
| `test_bm25.py` | 3 | 中文分词召回、排序合理、空查询 |
| `test_rrf.py` | 3 | 两路完全重合、完全不重合、部分重合排序符合预期 |
| `test_dense_retriever.py` | 2 | mock embedder：top-k 返回值、score 降序 |
| `test_upload_qa_e2e.py` | 6 | TestClient 跑通 6 个端点（embedder/reranker/llm 全 mock）；SSE 解析；DELETE 级联；路径穿越 400 |

**不测**：embedder/reranker 真实模型加载（吃资源，靠 eval 集验证）；真实 LLM 调用（靠 mock `openai` client）。

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

- 前端 `chunk.split('\n')` 不做跨 chunk buffer
- 单 `data: {"answer": "<token>"}\n\n` ~50 字节远小于 TCP MSS 1460，演示场景 P(出现) 极低
- **缓解**：Python 版每个 event 后 `await anyio.sleep(0)` 让事件循环 flush；不修前端
- **不缓解**：前端改造（违反"0 修改"红线）

### R3. sqlite3 单连接写 + FastAPI 多请求并发

- FastAPI 默认单进程，路由里拿单例 `Db`，`sqlite3.connect(check_same_thread=False)`
- 并发写靠 SQLite 自己的文件锁（`BEGIN IMMEDIATE`）
- **缓解**：DB 写操作都用 `with db.conn: db.conn.execute(...)` 自动开 transaction
- **剩余风险**：多人同时上传同名文件可能触发 UNIQUE 冲突—由 `dedupe_filename` 在写文件前消解

### R4. eval 集达不到 72 分

- 72–80 是 brainstorm 基于经验估算，未实测
- **缓解**：feature 完成后留 9 天 tuning（chunk 大小、top_k、RERANK_THRESHOLD、prompt）
- **降级路径**：若 Day 15 仍 < 65，在 orchestrator 里加一个 keyword-expansion 前置（同义词词典或 LLM 改写），不在本 spec 范围但可快速补

### R5. 二选一端口占用导致演示事故

- 演示时 TS 版和 Python 版都不能同时跑
- **缓解**：README 写 `lsof -ti:3002 | xargs kill -9` 作为启动前置步骤
- **剩余风险**：演示现场端口抢占看现场纪律

### R6. 团队 main 分支与个人 owner 分支漂移

- `docs/layer1-design-v2.md` 可能在本 spec 实现期间被团队更新
- **缓解**：不修改该文档；若团队明确某个 v2 feature 纳入 MVP 必须做，新开 spec 讨论 scope 变更

---

## 附录 A：依赖清单（`requirements.txt`）

```
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.9
pydantic-settings>=2.6
python-multipart>=0.0.12          # FastAPI form 支持
openai>=1.54                       # LLM 客户端（亚信网关兼容）
FlagEmbedding>=1.3                 # bge-m3 + reranker-v2-m3
rank-bm25>=0.2.2
jieba>=0.42
numpy>=2.0
PyMuPDF>=1.24                      # import fitz
python-docx>=1.1
python-pptx>=1.0
openpyxl>=3.1
pytest>=8.3
pytest-asyncio>=0.24
httpx>=0.27                        # TestClient 依赖
```

Python 3.12.4（conda env `sqllineage`）。依赖管理 `pip install -r requirements.txt`（不用 uv）。

## 附录 B：.env.example

```
PORT=3002
HOST=0.0.0.0

LLM_API_KEY=<亚信网关 key>
LLM_BASE_URL=https://<亚信网关>/v1
LLM_MODEL=<团队指定模型>

EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_THRESHOLD=0.4

DB_PATH=./storage/knowledge.db
RAW_DIR=./storage/raw
CONVERTED_DIR=./storage/converted
MAPPINGS_DIR=./storage/mappings

LOG_LEVEL=INFO
```
