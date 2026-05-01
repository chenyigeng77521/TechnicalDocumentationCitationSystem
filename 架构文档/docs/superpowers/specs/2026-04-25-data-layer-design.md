# 数据处理层设计（Layer 1 / Ingestion Service）

> **文档定位**：技术文档智能问答系统 - 数据处理层（涂祎豪）的设计 spec。
> **基线**：本设计严格遵循 `docs/plan/方案.md` 的 schema 与字段约定，按 2026-04-25 团队协调结果裁剪 MVP 范围。
> **不修改的文件**：`docs/plan/方案.md`（团队 canonical）、`backend/reasoning/interfaces.py`（接口契约）。

---

## 外行版摘要

### 1. 这一层做什么？

把"原材料"加工成"可检索的"。

具体讲：
- 用户上传的文件（PDF / Word / Excel / Markdown 等）→ 我这一层负责拆解成"小块"，每块算一个**向量指纹**，存进数据库
- 同时给上层（海军那边的检索层）开 3 个查询接口，他想按向量找近邻、按文字搜全文、按 ID 取单块都能调到

类比：图书馆员的工作。书来了 → 拆成段落 → 给每段贴标签和编号 → 上架。读者（海军）来要书时按编号或主题给他找出来。

### 2. 为什么需要？

团队架构图里我这一层是"链路的第一节"。没有它：
- 文件传上来没人处理（陈一赓的 entrance 不知道往哪里调）
- 海军那一层没有数据可检索（数据库是空的）
- 整个链路跑不通

### 3. 大致怎么做？

照团队的 `方案.md` 走，关键 6 件事：

1. **接文件**：陈一赓的 entrance 收到上传后调我们 `POST :3003/index`，我们去 `backend/storage/raw/` 下读那个文件
2. **解析**：按扩展名分派——PDF 用 PyMuPDF、Word 用 python-docx、扫描 PDF 触发 PaddleOCR、其它依次类推
3. **切块**：把长文本按"标题→段落→句子"三级 fallback 切成 1000 字以内的小块（chunk），相邻块留 200 字重叠
4. **算向量**：每块送进 bge-m3 模型，得到一个 1024 维的浮点数列表（向量指纹）
5. **写库**：单 SQLite 文件，包含 `documents` 表（文件级元数据）+ `chunks` 表（块内容 + 向量）+ `chunks_fts` 全文索引（自动同步）
6. **开接口给海军**：POST `/chunks/vector-search` / POST `/chunks/text-search` / GET `/chunks/{id}`

另外有个**兜底机制**：后台 `watchdog` 监听 raw/ 目录，万一陈一赓那边没调到，5 分钟内会自动发现新文件并处理。

### 4. 主要风险？

| 风险 | 概率 | 兜底 |
|---|---|---|
| PaddleOCR 慢（扫描 PDF 1-2 分钟）| 中 | entrance 那边 fetch 超时设 5 分钟，前端加 loading |
| 100 页以上 PDF 写入超时 | 中 | 分级 SLA：< 30s 小文件 / < 2min 中文件 / < 5min 大文件 |
| SQLite 多文件并发写锁 | 低 | 启用 WAL 模式 + 文件级互斥锁 |
| watchdog 漏事件 | 低 | 启动时全扫一次 + 每小时 GC |
| 海军端 embedding 算法跟我们不一致 | 低 | 双方都固定 bge-m3 + normalize_embeddings=True |

---

## 正文

### 1. 模块定位

| 项 | 值 |
|---|---|
| 模块路径 | `backend/ingestion/` |
| 服务端口 | `3003` |
| DB 文件路径 | `backend/storage/index/knowledge.db`（统一进 `backend/storage/`，跟 raw 平级） |
| 监听文件目录 | `backend/storage/raw/`（与 entrance 共用） |
| 日志路径 | `backend/ingestion/logs/ingestion.log` |
| Python 环境 | conda env `sqllineage`（Python 3.12.4） |
| 启动命令 | `python -m ingestion.server`（开发）/ uvicorn 启动（生产） |
| Web 框架 | FastAPI |

**与团队其它模块的边界（不修改的部分）**：

- `backend/entrance/`（陈一赓 / Express :3002）：上传后**他主动调我们** `POST :3003/index`，参数 `{ file_path }`
- `backend/reasoning/`（张满柱 / Flask :5050）：**不直接对接我们**。它通过 `interfaces.py` 调海军的 retrieval，海军调我们
- 海军模块（命名由海军定）：调我们的 3 个查询接口
- `backend/LLM/wiki/UpdateWiki/`（海军 :8080）：独立模块，跟我们无交集
- `backend/storage/`（团队公共存储目录）：**所有持久化数据**统一放这里——`backend/storage/raw/`（entrance 落地的原始文件，我们只读不写）+ `backend/storage/index/knowledge.db`（我们的 SQLite 文件，我们读写）。**ingestion/ 子目录里没有任何数据文件**，只有代码。

### 1.1 代码组织（子目录划分）

按方案.md §1.1-§1.5 五件事每件一个独立子目录，便于团队 review 和定位：

```
backend/ingestion/
├── parser/              # §1.1 文档解析（每种格式一个文件）
│   ├── __init__.py
│   ├── pdf_parser.py        # PyMuPDF + PaddleOCR 降级
│   ├── docx_parser.py       # python-docx
│   ├── xlsx_parser.py       # openpyxl
│   ├── pptx_parser.py       # python-pptx
│   ├── markdown_parser.py   # markdown 库
│   ├── html_parser.py       # beautifulsoup4 + markdownify
│   ├── txt_parser.py        # chardet 编码检测
│   ├── dispatcher.py        # 按扩展名 + MIME sniff 分派
│   └── types.py             # ParseResult / TitleNode dataclass
├── chunker/             # §1.2 chunk 切分
│   ├── __init__.py
│   ├── document_splitter.py # document 三级 fallback
│   ├── overlap.py           # overlap 拼接逻辑
│   └── types.py             # Chunk dataclass
├── db/                  # §1.3 SQLite 读写代码（注意：DB 文件本身在 backend/storage/index/，这里只放 .py 代码）
│   ├── __init__.py
│   ├── schema.sql           # CREATE TABLE / INDEX / TRIGGER 定义
│   ├── connection.py        # SQLite 连接池 + WAL 模式（连接 backend/storage/index/knowledge.db）
│   ├── documents_repo.py    # documents 表 CRUD
│   └── chunks_repo.py       # chunks 表 CRUD + FTS 查询
├── sync/                # §1.4 增量同步 + §1.5 5min SLA
│   ├── __init__.py
│   ├── pipeline.py          # index_pipeline 主流程
│   ├── file_lock.py         # 文件级互斥锁
│   ├── watchdog_runner.py   # 路径 B：watchdog observer
│   └── gc.py                # 启动扫描 + 每小时 GC
├── api/                 # HTTP 服务（FastAPI）
│   ├── __init__.py
│   ├── server.py            # FastAPI app 入口（uvicorn 启动）
│   ├── routes_index.py      # POST /index, DELETE /files, GET /stats, /health
│   └── routes_search.py     # POST /chunks/vector-search, /chunks/text-search, GET /chunks/{id}
├── common/              # 共享工具
│   ├── __init__.py
│   ├── embedding.py         # bge-m3 模型加载 + batch_embed
│   ├── errors.py            # 错误码枚举 + 自定义 Exception
│   └── logger.py            # JSON line logger
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/            # sample.md / sample.pdf 等测试用例
├── logs/                # ingestion.log 落地
├── __init__.py
├── requirements.txt
└── README.md
```

**命名约定**：
- 子目录名一律小写 + 单数（`parser/` 不是 `parsers/`）
- 子目录里**单文件 module 用** snake_case（`pdf_parser.py`）
- **db/** 是代码模块名，不存数据——数据库文件在 `backend/storage/index/knowledge.db`

### 2. 总览数据流

```
┌─ 写入路径 A：entrance 触发（同步）─────────────────────┐
│                                                       │
│  用户上传 → entrance multer 落地 backend/storage/raw/  │
│              ↓                                        │
│  entrance 同时开两个线程，一个调我们：                 │
│      POST :3003/index { file_path: "xxx.pdf" }        │
│              ↓                                        │
│  ① 算 file_hash（sha256 整文件）                       │
│              ↓                                        │
│  ② 查 documents 表，hash 没变 → 200 { unchanged }      │
│              ↓ hash 变了或新文件                        │
│  ③ 解析器分派 → ParseResult                            │
│              ↓                                        │
│  ④ 切 chunk（document 类型三级 fallback）              │
│              ↓                                        │
│  ⑤ 算 embedding（bge-m3，concurrency=8）              │
│              ↓                                        │
│  ⑥ 写 SQLite（事务：删旧 chunks + 写新 chunks +        │
│              upsert documents 行）                     │
│              ↓                                        │
│  返回 200 { status: "indexed", chunk_count, duration } │
│  → entrance 等到这个响应才告诉前端"上传完成"           │
└───────────────────────────────────────────────────────┘

┌─ 写入路径 B：watchdog 监听（兜底）────────────────────┐
│  watchdog observer 监听 backend/storage/raw/          │
│      ↓ created / modified / deleted 事件              │
│  debounce 1 秒（合并风暴）                            │
│      ↓                                                │
│  与路径 A 共用 index_pipeline（文件级锁互斥）          │
│      ↓                                                │
│  保证 5 分钟内必处理（5min SLA）                       │
└───────────────────────────────────────────────────────┘

┌─ 读取路径：被海军 retrieval 调 ───────────────────────┐
│  POST /chunks/vector-search { embedding, top_k }       │
│      ↓ chunks 表全表 cosine similarity                 │
│  返回 top_k 个候选 chunk                                │
│                                                       │
│  POST /chunks/text-search { query, top_k }             │
│      ↓ chunks_fts MATCH (BM25 排序)                    │
│  返回 top_k 个候选 chunk                                │
│                                                       │
│  GET /chunks/{chunk_id}                                │
│      ↓ 主键查询                                        │
│  返回单个 chunk（含 embedding）                         │
└───────────────────────────────────────────────────────┘

┌─ 横切：定时 GC（每小时）──────────────────────────────┐
│  对比 documents 表中的 file_path 与 raw/ 实际文件      │
│      ↓                                                │
│  磁盘没了的 → 删 document 行（CASCADE 删 chunks）       │
│  孤儿 chunks（没有对应 document）→ 直接 DELETE         │
└───────────────────────────────────────────────────────┘
```

### 3. SQLite Schema（照搬方案.md 1.3 节，补 2 个字段）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 文档级元数据
CREATE TABLE IF NOT EXISTS documents (
    file_path        TEXT PRIMARY KEY,
    file_name        TEXT NOT NULL,
    file_hash        TEXT NOT NULL,
    file_size        INTEGER NOT NULL,
    format           TEXT NOT NULL,         -- 扩展名（不带点）：pdf/docx/md/...
    language         TEXT,                  -- zh/en/auto；解析阶段填，可空
    index_version    TEXT NOT NULL,         -- UUID。MVP 阶段固定 'v1'，schema 留位
    index_status     TEXT DEFAULT 'pending',-- pending / indexed / error
    error_detail     TEXT,
    chunk_count      INTEGER DEFAULT 0,
    last_modified    TIMESTAMP NOT NULL,
    indexed_at       TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- chunks 主存储
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          TEXT PRIMARY KEY,
    file_path         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,
    index_version     TEXT NOT NULL,
    content           TEXT NOT NULL,
    anchor_id         TEXT NOT NULL,        -- "{file_path}#{char_offset_start}"
    title_path        TEXT,                 -- "Section > Subsection > ..."，可空
    char_offset_start INTEGER NOT NULL,
    char_offset_end   INTEGER NOT NULL,
    char_count        INTEGER NOT NULL,
    chunk_index       INTEGER NOT NULL,     -- 文件内序号 0,1,2,...
    is_truncated      INTEGER DEFAULT 0,    -- 硬切时 1
    content_type      TEXT NOT NULL DEFAULT 'document', -- document / code / structured_data
    language          TEXT,                 -- 与 documents.language 同
    embedding         TEXT,                 -- JSON array float[1024]
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_path) REFERENCES documents(file_path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file    ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(index_version);

-- FTS5 全文索引（BM25 排序）
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    title_path,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- 自动同步触发器
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;
```

**对方案.md schema 的差异**：
- 补上 `chunks.content_type` 和 `chunks.language` 字段（方案.md 1.2.4 chunk 数据结构里有，但 1.3 SQL 漏了）
- 补 `chunks_au` 更新触发器（方案.md 只写了 ai/ad）
- `index_version` 字段保留，MVP 写死 'v1'，留升级位

### 4. 接口契约

#### 4.1 写入侧（被 entrance 调）

**重要约定 — `file_path` 字段格式**：

所有接口里的 `file_path` 都是**相对 `backend/storage/raw/` 的路径**，不带 `raw/` 前缀。例：

| 实际磁盘路径 | API 里 `file_path` |
|---|---|
| `backend/storage/raw/example.pdf` | `example.pdf` |
| `backend/storage/raw/api/auth.md` | `api/auth.md` |

我们内部 `resolve_under_storage_raw(file_path)` 拼出绝对路径。`anchor_id` 也用这个相对格式：`api/auth.md#4821`。

##### `POST /index`

请求：
```json
{ "file_path": "example.pdf" }
```

响应：
```json
// 成功
200 OK
{
  "status": "indexed",     // indexed / unchanged
  "chunk_count": 42,
  "duration_ms": 3500,
  "file_hash": "abc123..."
}

// 解析失败
400 Bad Request
{
  "status": "error",
  "error_type": "parse_failed",
  "detail": "PDF 加密文件不支持"
}

// 文件不存在
404 Not Found
{
  "status": "error",
  "error_type": "file_not_found"
}

// embedding/DB 内部错误
500 Internal Server Error
{
  "status": "error",
  "error_type": "embedding_timeout" | "db_error",
  "detail": "..."
}
```

**约定**：
- entrance 端 fetch 超时设 **5 分钟**（容纳大文件 OCR）
- 处理失败不删 raw/ 文件（让用户/entrance 决定是否重试）

##### `DELETE /files`

请求：
```json
{ "file_path": "example.pdf" }
```

响应：
```json
{ "status": "deleted", "deleted_chunks": 42 }
```

效果：删 documents 行 → CASCADE 删 chunks → 触发器删 chunks_fts 行。

##### `GET /stats`

响应：
```json
{
  "documents": 12,
  "chunks": 504,
  "index_size_mb": 8.3,
  "last_indexed_at": "2026-04-25T10:30:00Z"
}
```

##### `GET /health`

响应：
```json
{
  "status": "ok",
  "db_writable": true,
  "embedding_model_loaded": true
}
```

#### 4.2 检索侧（被海军调）

##### `POST /chunks/vector-search`

请求：
```json
{
  "embedding": [0.1, -0.3, 0.5, ...],   // 1024 维 float
  "top_k": 50,
  "filters": {                          // 可选，MVP 暂不实现，schema 预留
    "min_timestamp": "2026-04-20T10:00:00Z",
    "file_paths": ["docs/api/*"]
  }
}
```

响应：
```json
{
  "results": [
    {
      "chunk_id": "sha256_hash_string",
      "content": "OAuth2 Token 刷新接口...",
      "score": 0.85,                    // cosine similarity ∈ [0, 1]（normalize_embeddings=True 后单位向量，cosine ≥ 0），越大越像
      "metadata": {
        "file_path": "api/auth.md",
        "anchor_id": "api/auth.md#4821",
        "title_path": "Authentication > OAuth2 > Token Refresh",
        "char_offset_start": 4821,
        "char_offset_end": 5320,
        "is_truncated": false,
        "content_type": "document",
        "language": "zh",
        "last_modified": "2026-04-24T14:50:00Z"
      }
    }
  ],
  "total": 50
}
```

实现：`SELECT ... FROM chunks ORDER BY vec_cosine_similarity(embedding, ?) DESC LIMIT ?`

> MVP 用 Python 端计算 cosine（小语料 < 10k chunks 性能可接受 ~100ms）。P1 升级 sqlite-vec 扩展。

##### `POST /chunks/text-search`

请求：
```json
{
  "query": "OAuth2 token 刷新",
  "top_k": 50,
  "filters": { ... }                    // 同上
}
```

响应：同 vector-search，**区别**：
- `score` 字段是 BM25 归一化后的相似度，公式 `score = 1 / (1 + abs(bm25_rank))`，落在 (0, 1]，越大越像
- 多返回一个 **`bm25_rank`** 字段（FTS5 原始负数 rank，越小越相关），方便海军做 RRF 融合时直接用 rank
- 实现：`SELECT chunk_id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?`，再 JOIN chunks 取完整字段

##### `GET /chunks/{chunk_id}`

响应：单个 chunk 完整字段（包括 raw embedding，供海军调试）：
```json
{
  "chunk_id": "...",
  "content": "...",
  "embedding": [0.1, -0.3, ...],        // 完整 1024 维
  "metadata": { ... }                   // 同上
}
```

#### 4.3 字段对齐说明

我们返回的 `metadata` 字段与 `backend/reasoning/interfaces.py` 中的 `ChunkMetadata` **必须 1:1 对应**（海军在他那一层做转换时直接 mapping）：

| 我们的字段 | interfaces.ChunkMetadata 字段 | 备注 |
|---|---|---|
| `file_path` | `file_path` | 必填 |
| `anchor_id` | `anchor_id` | 必填，格式 `file_path#char_offset` |
| `title_path` | `title_path` | 可空 |
| `last_modified` | `last_modified` | ISO8601 |

`content_type` / `is_truncated` 在 interfaces.py 的 `RetrievedChunkResponse` 顶层（不在 metadata 内），海军那边重组装即可。

### 5. 写入 Pipeline 详细流程

```python
async def index_pipeline(file_path: str) -> dict:
    """
    路径 A 和路径 B 共用的入口。
    file_path 是相对 backend/storage/raw/ 的路径（如 "example.pdf"）。
    """
    abs_path = resolve_under_storage_raw(file_path)
    if not abs_path.exists():
        raise FileNotFoundError(file_path)

    # 文件级锁，防 A/B 并发处理同一文件
    async with file_lock(file_path):
        # 1. file_hash
        new_hash = sha256_of_file(abs_path)
        old_doc = db.get_document(file_path)
        if old_doc and old_doc.file_hash == new_hash:
            return {"status": "unchanged"}

        # 2. upsert documents 行（status=pending）
        new_version = "v1"  # MVP 固定
        db.upsert_document(
            file_path=file_path,
            file_hash=new_hash,
            file_size=abs_path.stat().st_size,
            format=abs_path.suffix.lstrip("."),
            index_version=new_version,
            index_status="pending",
            last_modified=datetime.utcnow(),
        )

        try:
            # 3. 解析
            parse_result = await parse_document(abs_path)

            # 4. 切 chunk
            chunks = chunker.split(parse_result, file_path=file_path,
                                   file_hash=new_hash, index_version=new_version)

            # 5. 算 embedding（并发 8）
            embeddings = await batch_embed(
                texts=[c.content for c in chunks],
                concurrency=8,
            )
            for c, emb in zip(chunks, embeddings):
                c.embedding = emb

            # 6. 写库（事务）
            with db.transaction():
                db.delete_chunks_by_file(file_path)  # MVP 全删重写
                db.insert_chunks(chunks)
                db.update_document(
                    file_path=file_path,
                    index_status="indexed",
                    chunk_count=len(chunks),
                    indexed_at=datetime.utcnow(),
                    error_detail=None,
                )

            return {
                "status": "indexed",
                "chunk_count": len(chunks),
                "file_hash": new_hash,
            }

        except ParseError as e:
            db.update_document(file_path=file_path, index_status="error",
                               error_detail=f"解析失败: {e}")
            raise
        except EmbeddingError as e:
            db.update_document(file_path=file_path, index_status="error",
                               error_detail=f"embedding 失败: {e}")
            raise
```

### 6. 解析器分派

按扩展名 → MIME 二次确认：

| 扩展名 | 解析器 | Python 包 | 备注 |
|---|---|---|---|
| `.md` | markdown 直读 | `markdown` | 提取 heading 作 title_tree |
| `.txt` | 直读 + 编码检测 | `chardet` | utf-8 / gbk 自动 |
| `.html` | 转 markdown | `beautifulsoup4` + `markdownify` | |
| `.pdf`（文字版） | PyMuPDF | `pymupdf` | 检测 `page.get_text()` 非空 |
| `.pdf`（扫描版） | PaddleOCR | `paddleocr` | 文字提取为空时降级 |
| `.docx` | python-docx → md | `python-docx` | 保留 heading |
| `.xlsx` | openpyxl → md 表格 | `openpyxl` | 每 sheet 一个段落 |
| `.pptx` | python-pptx → md | `python-pptx` | 每 slide 一个段落 |
| `.doc/.xls/.ppt` | LibreOffice 转新格式 | `unoconv` 或 `libreoffice --headless` | P1，MVP 直接报错 `unsupported_format` |

**统一输出 ParseResult**：

```python
@dataclass
class ParseResult:
    raw_text: str                    # 解析后纯文本
    title_tree: list[TitleNode]      # heading 层级，可空
    content_type: str = "document"   # MVP 全部固定 document
    language: str | None = None      # zh/en/auto
    confidence: float = 1.0          # 解析置信度 0-1（OCR 时填实际值）
    metadata: dict = field(default_factory=dict)  # 解析器特有字段
```

**code 类不分派**（已敲定决策）：`.py / .java / .json / .yaml` 等代码类文件按 document 处理，不走 AST 切分。

### 7. Chunk 切分策略（document 类型）

```python
MAX_CHARS = 1000
OVERLAP   = 200
MIN_CHARS = 30   # 过短 chunk 丢弃

def split_document(parse_result: ParseResult, **meta) -> list[Chunk]:
    """三级 fallback 切分：标题 → 段落 → 句子 → 硬切"""
    raw_text = parse_result.raw_text
    title_tree = parse_result.title_tree

    # 第 1 级：按标题切大段
    sections = split_by_title(raw_text, title_tree)

    chunks = []
    char_cursor = 0
    chunk_idx = 0

    for section in sections:
        title_path = " > ".join(section.title_chain) if section.title_chain else None
        text = section.text

        if len(text) <= MAX_CHARS:
            chunks.append(make_chunk(text, char_cursor, title_path, chunk_idx, **meta))
            chunk_idx += 1
        else:
            # 第 2 级：按 \n\n 切段落
            paragraphs = text.split("\n\n")
            for para in paragraphs:
                if len(para) <= MAX_CHARS:
                    chunks.append(make_chunk(para, char_cursor + offset_in_section, ...))
                    chunk_idx += 1
                else:
                    # 第 3 级：按句子切
                    sentences = split_sentences(para)  # 按 [。！？.!?] 切
                    buffer = ""
                    for sent in sentences:
                        if len(buffer) + len(sent) <= MAX_CHARS:
                            buffer += sent
                        else:
                            if buffer:
                                chunks.append(make_chunk(buffer, ...))
                                chunk_idx += 1
                            if len(sent) > MAX_CHARS:
                                # 单句仍超 → 硬切
                                for hard_chunk in hard_split(sent, MAX_CHARS):
                                    chunks.append(make_chunk(
                                        hard_chunk, ..., is_truncated=True))
                                    chunk_idx += 1
                                buffer = ""
                            else:
                                buffer = sent
                    if buffer:
                        chunks.append(make_chunk(buffer, ...))
                        chunk_idx += 1

        char_cursor += len(text)

    # 加 overlap：取前一 chunk 末尾 200 char 拼到下一 chunk 前
    chunks = apply_overlap(chunks, OVERLAP)

    # 过滤过短 chunk
    chunks = [c for c in chunks if c.char_count >= MIN_CHARS or c.is_truncated]

    return chunks


def make_chunk(content, char_offset_start, title_path, chunk_index,
               file_path, file_hash, index_version, is_truncated=False) -> Chunk:
    chunk_id = sha256(f"{file_path}|{chunk_index}|{content[:100]}").hexdigest()
    return Chunk(
        chunk_id=chunk_id,
        file_path=file_path,
        file_hash=file_hash,
        index_version=index_version,
        content=content,
        anchor_id=f"{file_path}#{char_offset_start}",
        title_path=title_path,
        char_offset_start=char_offset_start,
        char_offset_end=char_offset_start + len(content),
        char_count=len(content),
        chunk_index=chunk_index,
        is_truncated=is_truncated,
        content_type="document",
    )
```

### 8. Embedding

```python
from sentence_transformers import SentenceTransformer

_MODEL = None

def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer("BAAI/bge-m3")
    return _MODEL

async def batch_embed(texts: list[str], concurrency: int = 8) -> list[list[float]]:
    """
    batch_size 8，bge-m3 输出 1024 维向量，强制 normalize。
    海军端必须用同一模型 + 同一参数（normalize_embeddings=True）。
    """
    model = get_model()
    sem = asyncio.Semaphore(concurrency)

    async def _embed_one(batch_texts):
        async with sem:
            return await asyncio.to_thread(
                model.encode,
                batch_texts,
                normalize_embeddings=True,
                batch_size=8,
            )

    # 把 texts 分成 batch_size=8 的批次
    batches = [texts[i:i+8] for i in range(0, len(texts), 8)]
    results = await asyncio.gather(*[_embed_one(b) for b in batches])
    return [vec.tolist() for batch in results for vec in batch]
```

### 9. 增量同步（MVP 简化版）

**做的**：

| 场景 | 行为 |
|---|---|
| 文件首次上传 | 走完整 pipeline，写 documents + chunks |
| 同一文件再上传，hash 没变 | 返回 `unchanged`，不重新处理 |
| 同一文件再上传，hash 变了 | 删 file_path 下所有旧 chunks → 走完整 pipeline → 写新 chunks |
| 文件被删（路径 B 监听到 deleted 事件） | 删 documents 行（CASCADE 删 chunks 触发器删 fts） |
| 启动时全扫 GC | 对比 raw/ 实际文件 vs documents 表，缺失的删，多余的触发 index |
| 每小时定时 GC | 删孤儿 chunks（没有对应 document 的） |

**不做（明确写出来，避免歧义）**：
- ❌ chunk-level diff（embedding 复用）
- ❌ index_version 切换（schema 字段保留，MVP 始终 'v1'）
- ❌ chunk-level 软删除

### 10. 5 分钟 SLA / 路径 B 实现

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RawDirHandler(FileSystemEventHandler):
    """监听 backend/storage/raw/ 目录"""

    def __init__(self, debounce_seconds=1.0):
        self.debounce = debounce_seconds
        self.pending = {}  # file_path -> last_event_time

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_deleted(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "delete")

    def _schedule(self, path, action):
        # debounce 1 秒
        self.pending[path] = (time.time(), action)
        asyncio.get_event_loop().call_later(
            self.debounce + 0.1,
            lambda: self._fire_if_settled(path),
        )

    def _fire_if_settled(self, path):
        last_time, action = self.pending.get(path, (0, None))
        if time.time() - last_time >= self.debounce:
            del self.pending[path]
            file_path = make_relative(path)
            if action == "delete":
                asyncio.create_task(handle_file_delete(file_path))
            else:
                asyncio.create_task(index_pipeline(file_path))
```

启动时全扫一次：

```python
async def initial_scan_and_gc():
    """启动时对比磁盘和 documents 表，找差异"""
    disk_files = set(walk_raw_dir())
    db_files = set(db.get_all_document_paths())

    # 磁盘有 DB 没有 → 触发 index
    for fp in disk_files - db_files:
        asyncio.create_task(index_pipeline(fp))

    # DB 有磁盘没 → 删 document
    for fp in db_files - disk_files:
        asyncio.create_task(handle_file_delete(fp))
```

每小时 GC：

```python
async def hourly_gc():
    while True:
        await asyncio.sleep(3600)
        await initial_scan_and_gc()
        # 同时清理孤儿 chunks（防触发器漏执行）
        db.execute("""
            DELETE FROM chunks
            WHERE file_path NOT IN (SELECT file_path FROM documents)
        """)
```

### 11. 错误码与日志

**错误码**（响应中 `error_type`）：

| 错误码 | HTTP | 含义 | entrance 端建议处理 |
|---|---|---|---|
| `file_not_found` | 404 | file_path 在 raw/ 下不存在 | 检查 multer 落地路径 |
| `unsupported_format` | 400 | 扩展名未支持（如 .doc 旧版） | 提示用户转格式 |
| `parse_failed` | 400 | 解析器抛异常（PDF 加密 / 文件损坏） | 展示 detail 给用户 |
| `embedding_timeout` | 500 | bge-m3 调用 5 次重试仍失败 | 重试 |
| `db_error` | 500 | SQLite 写入异常 | 重试 |

**日志**：

- 路径：`backend/ingestion/logs/ingestion.log`
- 级别：INFO/WARN/ERROR 三级
- 格式：JSON line（便于后续聚合分析）
- 关键事件必记录：
  - `index_pipeline` 开始/结束（含 duration）
  - 每个 chunk 的 chunk_id（DEBUG 级）
  - 错误 stack trace（ERROR 级）

### 12. 测试策略

| 层级 | 工具 | 范围 |
|---|---|---|
| 单元测试 | pytest | 每个 parser、chunker、embedding 模块独立测 |
| 集成测试 | pytest + httpx | 起服务 → POST /index 真实文件 → 查 chunks 表断言 |
| 契约测试 | pytest + mock | mock 海军调用 vector-search/text-search，断言响应字段 |
| 性能测试 | pytest-benchmark | 100 页 PDF 端到端 < 30s（P0 SLA） |
| 联调 | 手工 | 与 entrance 真实联调上传 → 索引 → 海军查询 |

**最小验收 case**：

1. 上传 `sample.md`（10KB）→ 100ms 内返回 indexed
2. 上传 `sample.pdf`（100 页文字版）→ < 30s 返回
3. 上传 `sample_scanned.pdf`（10 页扫描）→ < 60s 返回（OCR）
4. 重复上传同一文件 → 返回 unchanged
5. 修改文件后重传 → 旧 chunks 删干净，新 chunks 数量正确
6. 删除文件 → documents 行 + chunks 全删
7. POST /chunks/vector-search 传一个已知 embedding → 返回相关 chunk top_k
8. POST /chunks/text-search 传 "OAuth2" → 返回包含该词的 chunk

### 13. 风险与兜底

| 风险 | 概率 | 影响 | 兜底 |
|---|---|---|---|
| PaddleOCR 慢（扫描 PDF 1-2 分钟） | 中 | 用户等待 | entrance 超时设 5 min；前端 loading；P1 改异步 |
| bge-m3 模型加载慢（首次 ~10s） | 高 | 服务启动慢 | 启动时 warmup 加载 |
| SQLite 多文件并发写锁 | 低 | 写延迟 | WAL 模式 + 文件级互斥锁 |
| watchdog 漏事件 | 低 | 文件未索引 | 每小时 GC 全扫一次 |
| 大文件 SLA 超时（500 页+） | 中 | 失败 | 分级 SLA：< 30s 小 / < 2min 中 / < 5min 大 / 超大异步 |
| chunk_id 哈希碰撞 | 极低 | 写入冲突 | sha256 + 文件路径 + 内容前 100 字，碰撞概率可忽略 |
| 编码非 UTF-8（旧 .txt） | 中 | 解析乱码 | chardet 检测 + 转码；失败标记 error_detail |
| index_version 升级（未来） | 低 | 数据迁移 | schema 已留字段，迁移脚本一次性跑 |

### 14. 协作边界总结

| 与谁对接 | 谁主动 | 内容 |
|---|---|---|
| entrance（陈一赓） | 他主动调我 | `POST :3003/index { file_path }` 同步等返回 |
| retrieval（海军） | 他主动调我 | `POST :3003/chunks/vector-search` / `text-search` / `GET /chunks/{id}` |
| reasoning（张满柱） | 不直接对接 | 通过海军间接，字段需对齐 `interfaces.ChunkMetadata` |
| frontend（陈一赓） | 不直接对接 | 通过 entrance 间接 |
| nginx / wiki UpdateWiki | 无关 | 各自独立 |

**协作前置条件（写在这里给协作方看）**：

1. **entrance 端**：在 `entrance/upload.ts` multer 完成后追加 `await fetch('http://localhost:3003/index', { method: 'POST', body: JSON.stringify({ file_path }) })`，超时设 5 min
2. **海军端**：retrieval.py 不再直接读 SQLite，改成调本服务 3 个端点；query embedding 在他那边算（bge-m3，normalize_embeddings=True）
3. **reasoning（张满柱）端**：无变化，他对 retrieval 的调用契约不变

---

## 名词解释

> 用 5 问展开本文档中关键技术术语：(1) 解决什么 (2) 没它会怎样 (3) 在流程哪一步 (4) 输入输出 (5) 当前项目非要它不可吗

### chunk（文档块）

1. **解决什么**：把长文档切成 LLM 能"一口塞下"的小段（一般 ≤ 1000 字）
2. **没它会怎样**：100 页 PDF 整个塞给 LLM → 超 context 长度限制 / 一次答错难定位
3. **在流程哪一步**：解析后、embedding 前
4. **输入输出**：输入是解析后的纯文本，输出是 list[Chunk]，每个 chunk 含 content + 锚点 + 元数据
5. **非要不可吗**：是。RAG 系统的基本单元，没有 chunk 就没有"检索粒度"

### embedding（向量化）

1. **解决什么**：把文本变成一串数字（1024 维向量），让"语义相似度"可以用数学算
2. **没它会怎样**：只能做关键词匹配，"超时配置"匹配不到"timeout setting"
3. **在流程哪一步**：chunk 切完后，写入 SQLite 前
4. **输入输出**：输入是 chunk 的 content 字符串，输出是 1024 维 float 列表
5. **非要不可吗**：是。语义检索的基础

### bge-m3

1. **解决什么**：BAAI（智源）开源的 embedding 模型，中英双语都强
2. **没它会怎样**：用 OpenAI 的 text-embedding 要联网 + 收费；用其它中文模型质量可能差
3. **在流程哪一步**：embedding 阶段调用
4. **输入输出**：输入是文本字符串列表，输出是 1024 维向量列表
5. **非要不可吗**：方案.md 已定。海军端也用同一模型，必须一致

### FTS5

1. **解决什么**：SQLite 自带的全文索引扩展，支持 BM25 排序
2. **没它会怎样**：全文搜索要 LIKE '%xxx%'，10k chunks 上 100ms+ 一次
3. **在流程哪一步**：写 chunks 时触发器自动同步；查询时 `chunks_fts MATCH ?`
4. **输入输出**：写入是 (chunk_id, content, title_path) 三元组；查询输入 query string，输出排序后的 chunk_id 列表
5. **非要不可吗**：是。BM25 一路召回的实现基础

### BM25

1. **解决什么**：经典的全文打分算法，比 TF-IDF 更准
2. **没它会怎样**：召回要么按词频排（差），要么纯靠向量（漏关键词命中）
3. **在流程哪一步**：FTS5 内置，查询时自动用
4. **输入输出**：输入 query + 文档集合，输出每个文档的相关度分数
5. **非要不可吗**：是。两路召回的"另一路"

### WAL（Write-Ahead Logging）

1. **解决什么**：SQLite 的并发写入模式，读不阻塞写
2. **没它会怎样**：默认 rollback 模式下，多线程同时写会卡
3. **在流程哪一步**：DB 初始化时 `PRAGMA journal_mode = WAL` 一次设置
4. **输入输出**：无，是数据库内部模式
5. **非要不可吗**：是。多文件并发上传场景必需

### watchdog（Python 文件监听库）

1. **解决什么**：监听文件系统事件（文件被创建 / 修改 / 删除），不用轮询
2. **没它会怎样**：要写定时任务每分钟扫一次磁盘，效率差
3. **在流程哪一步**：服务启动时起 observer，整个生命周期持续监听
4. **输入输出**：输入是要监听的目录路径，输出是事件回调（包含被改文件路径）
5. **非要不可吗**：是。路径 B（5 min SLA）的实现基础。轮询替代方案能 work，但延迟差很多

### PaddleOCR

1. **解决什么**：识别扫描版 PDF / 图片里的中文文字
2. **没它会怎样**：扫描 PDF 解析后是空文本，无法 embedding，失去检索能力
3. **在流程哪一步**：解析阶段，PyMuPDF 提取文字为空时降级触发
4. **输入输出**：输入是图片或 PDF 页面，输出是识别出的文字 + 位置坐标
5. **非要不可吗**：评委可能塞扫描件，做了保险。已敲定决策做

### anchor_id

1. **解决什么**：精确定位文档中"具体哪个字符位置"，前端可跳转
2. **没它会怎样**：只能跳到文档级，不能跳到段落级
3. **在流程哪一步**：chunk 创建时算（`{file_path}#{char_offset_start}`），存进 chunks.anchor_id
4. **输入输出**：输入是 file_path 和起始字符偏移，输出是字符串
5. **非要不可吗**：是。比赛 Task 2 要求"段落 anchor"，硬指标

### title_path

1. **解决什么**：人能读的"面包屑"路径（Section > Subsection > ...），UI 展示用
2. **没它会怎样**：UI 只能显示文件名 + 字符偏移，可读性差
3. **在流程哪一步**：解析阶段抽 heading 层级，chunk 切分时 join 成字符串
4. **输入输出**：输入是 title_tree + 当前段所在节点，输出是 " > " 拼接的字符串
5. **非要不可吗**：UI 体验大幅提升，但**可空**（无标题文档允许 null，系统不降级）

### file_hash

1. **解决什么**：判断文件内容是否变化（比改时间戳准）
2. **没它会怎样**：用户重传未修改的同一文件，会重复 embedding 一遍，浪费算力
3. **在流程哪一步**：每次 index_pipeline 第一步算
4. **输入输出**：输入是文件二进制内容，输出是 sha256 hex 字符串
5. **非要不可吗**：是。增量同步的核心判断

### index_version

1. **解决什么**：未来支持原子版本切换（写新版完了再删旧版，查询永远看到一致快照）
2. **没它会怎样**：MVP 阶段用不到，但 schema 留位避免后期迁移痛苦
3. **在流程哪一步**：MVP 写死 'v1'，未来 chunk-level diff 启用时切换
4. **输入输出**：UUID 字符串
5. **非要不可吗**：MVP 不必要，但 schema 留位**必要**（升级无痛）

