# 数据处理层 (Layer 1) 接口文档

> **服务**：Ingestion Service
> **端口**：`:3003`
> **负责人**：涂祎豪
> **调用方**：陈一赓的 entrance（写入侧）/ 冷海军的检索增强层（读取侧）
> **设计 spec**：`docs/superpowers/specs/2026-04-25-data-layer-design.md`

---

## 快速上手

### 启动服务

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python -m backend.ingestion.api.server
```

监听 `http://localhost:3003`。bge-m3 模型懒加载（首次 `/index` 调用时加载，约 15 秒）。

### 健康检查

```bash
curl http://localhost:3003/health
# {"status":"ok","db_writable":true,"embedding_model_loaded":false}
```

---

## 关键约定（先读）

| 项 | 值 / 规则 |
|---|---|
| Embedding 模型 | `BAAI/bge-m3` |
| Embedding 维度 | **1024** |
| Normalize | **必须 `normalize_embeddings=True`**（写入与查询双方对齐）|
| `file_path` 格式 | **相对项目根 `data/` 的路径，带 `docs/<domain>/` 前缀**（与赛题评委 jsonl `gold_sources[].doc_path` 完全一致）。例：`data/docs/react/incremental-adoption.md` → `file_path = "docs/react/incremental-adoption.md"`。kubernetes 域有中文子目录如 `docs/kubernetes/调度与驱逐/api-eviction.md`，路径深度不固定 |
| `chunk_id` | `sha256(file_path|chunk_index|content[:100])` 的 hex 字符串 |
| `anchor_id` | `{file_path}#{char_offset_start}` |
| Score 范围 | vector cosine ∈ [0, 1]（normalize 后），BM25 归一化 ∈ (0, 1] |
| Content-Type | 所有 POST 请求必须 `application/json` |

---

## 接口总览

| 路径 | 方法 | 用途 | 主要调用方 |
|---|---|---|---|
| [`/chunks/vector-search`](#post-chunksvector-search) | POST | 向量近邻检索（Dense kNN）| 海军 |
| [`/chunks/text-search`](#post-chunkstext-search) | POST | 全文检索（FTS5 BM25）| 海军 |
| [`/chunks/{chunk_id}`](#get-chunkschunk_id) | GET | 按主键取单个 chunk（含完整 embedding）| 海军 / 调试 |
| [`/index?add/modify/delete=<file_path>`](#post-index) | POST | 增量索引：新增 / 修改 / 删除（query param 三选一） | entrance / 前端 |
| [`/stats`](#get-stats) | GET | 库存统计 | 监控 |
| [`/health`](#get-health) | GET | 健康检查 | 监控 |

---

## 检索接口（海军主用）

### POST `/chunks/vector-search`

向量近邻检索。**你算好 query 的 embedding（bge-m3 + normalize）传过来**，返回库里 cosine 最相似的 top_k 个 chunk。

**Request**:

```json
{
  "embedding": [0.1, -0.3, 0.5, ...],
  "top_k": 50,
  "filters": null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `embedding` | `float[1024]` | **必填**。query 的向量。维度必须 1024，否则返回 400 |
| `top_k` | `int` | 默认 50。返回最相似的前 K 个 |
| `filters` | `object \| null` | MVP 暂不实现；schema 留位（未来支持 `min_timestamp` / `file_paths` 等过滤）|

**Response 200**:

```json
{
  "results": [
    {
      "chunk_id": "81e76ae62a95...",
      "content": "OAuth2 token refresh requires the `Authorization: Bearer {refresh_token}` header.\nToken has a 7-day default expiry.",
      "score": 0.85,
      "metadata": {
        "file_path": "docs/react/incremental-adoption.md",
        "anchor_id": "docs/react/incremental-adoption.md#38",
        "title_path": "Sample Document > Authentication",
        "char_offset_start": 38,
        "char_offset_end": 153,
        "is_truncated": false,
        "content_type": "document",
        "language": null,
        "last_modified": null
      }
    }
  ],
  "total": 1
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `chunk_id` | string | sha256 hex，主键 |
| `content` | string | chunk 原文（可直接送 reranker）|
| `score` | float | cosine similarity ∈ [0, 1]，越大越像 |
| `metadata.file_path` | string | 文件路径（相对项目根 `data/`，带 `docs/<domain>/` 前缀，如 `docs/react/foo.md`）|
| `metadata.anchor_id` | string | `{file_path}#{char_offset_start}`，前端跳转锚点 |
| `metadata.title_path` | string \| null | `Section > Subsection` 面包屑路径，无 heading 时 null |
| `metadata.char_offset_start/end` | int | content 在原文中的字符区间（含端点）|
| `metadata.is_truncated` | bool | 是否硬切产生（超长单句）。true 时 reranker/LLM 应注明"内容可能不完整"|
| `metadata.markdown_anchor` | string | markdown section anchor，如 `#top` 或 `#section-id`；**赛题 citation 输出用**。Layer 2 海军应映射到 `RetrievedChunk.anchor`，reasoning 端 `Citation.anchor` 透传 |
| `metadata.is_x15_truncated` | bool | X1.5 max_chars 截断标记。**仅 X1.5 路径**实际发生截断时为 true，其它情况（X0 路径、UNTITLED 退化、by-id 接口、未截断的 X1.5）一律 false |
| `metadata.content_type` | string | `document` / `code` / `structured_data`。MVP 全部 `document` |
| `metadata.language` | string \| null | `zh` / `en` / null（待解析端填充）|
| `metadata.last_modified` | string \| null | ISO8601。MVP 暂为 null（不 JOIN documents）|

**错误**：
- `400`：embedding 维度不是 1024

---

### POST `/chunks/text-search`

全文检索（SQLite FTS5 + BM25）。**直接传字符串，不需要 embedding**。

**Request**:

```json
{
  "query": "OAuth2 token refresh",
  "top_k": 50,
  "filters": null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | **必填**。FTS5 查询字符串（支持空格分词、引号短语）|
| `top_k` | int | 默认 50 |
| `filters` | object \| null | 同 vector-search，MVP 不实现 |

**Response 200**:

```json
{
  "results": [
    {
      "chunk_id": "...",
      "content": "...",
      "score": 0.681,
      "bm25_rank": -0.467,
      "metadata": { ... }
    }
  ],
  "total": 1
}
```

**与 vector-search 的差异**：

| 字段 | 说明 |
|---|---|
| `score` | BM25 归一化后的相似度，公式 `1 / (1 + abs(bm25_rank))`，∈ (0, 1] |
| `bm25_rank` | **额外字段**。FTS5 原始 rank（**负数**，越小越相关），便于做 RRF 融合时直接用 rank 而非 score |

**RRF 融合提示**：你做 vector + BM25 两路召回融合时，建议直接用 `bm25_rank` 排序位置（rank-based），而不是混合两个 score（绝对值不同 scale）。

---

### GET `/chunks/{chunk_id}`

按主键取单个 chunk，**返回完整 embedding 数组**（调试 / 重排时单独取）。

**Request**:

```bash
GET /chunks/81e76ae62a95e0759b6c28fe3c97b23c5692d1470d37dcdc308a0c2857d5fe95
```

**Response 200**:

```json
{
  "chunk_id": "81e76ae62a95...",
  "content": "OAuth2 token refresh ...",
  "embedding": [0.0106, 0.0314, -0.0296, ...],
  "metadata": { ... }
}
```

`embedding` 是 1024 维 float 数组（vector-search 返回里没有这个字段，太大；只有 by-id 才返回）。

**错误**：
- `404`：chunk_id 不存在 → `{"detail":"chunk <id> not found"}`

---

## 写入接口（entrance 用，海军一般不调）

### POST `/index`

增量索引接口。三个 query param 互斥（必须且只能提供一个）：

| Query param | 含义 | 内部行为 |
|---|---|---|
| `?add=<file_path>` | 新增文件索引 | 走 `index_pipeline` |
| `?modify=<file_path>` | 文件内容变了，重新索引 | 走 `index_pipeline`（按 file_hash 自动判定） |
| `?delete=<file_path>` | 删除文件的所有 chunks | 走 `handle_file_delete` |

`file_path` = 相对项目根 `data/` 的路径，**必含 `docs/<domain>/` 前缀**，例 `docs/react/foo.md`。

**三个操作都必须传完整路径**（不能只传 basename）。原因：DB 用完整路径作主键，不同子目录可能撞同名（如 `docs/react/foo.md` 和 `docs/spring/foo.md` 是两个不同文件，basename 都是 `foo.md`）。

唯一区别：**add / modify 时物理文件必须存在于 `data/<file_path>`**（要解析）；**delete 不需要文件存在**（只按 file_path 查 DB 删 chunks，文件早就被前端从磁盘移除了也能正常 delete）。

**Request 例**：

```bash
POST /index?add=docs/react/incremental-adoption.md
POST /index?modify=docs/react/incremental-adoption.md
POST /index?delete=docs/react/incremental-adoption.md
```

**Response 200**：

```json
// add / modify：新文件或内容变化
{ "status": "indexed", "chunk_count": 7, "file_hash": "938e3a40..." }

// add / modify：内容没变（hash 一致）
{ "status": "unchanged" }

// modify：之前已索引，内容变化（旧 chunks 已删，新 chunks 已写）
{ "status": "replaced", "chunk_count": 9, "file_hash": "..." }

// delete
{ "status": "deleted", "deleted_chunks": 7 }

// delete：文件不在库里
{ "status": "not_found" }
```

**说明**：
- `add` 和 `modify` 走相同后端逻辑（`index_pipeline` 按 `file_hash` 自动区分 indexed / replaced / unchanged）。前端区分 add / modify 只是语义意图，后端不强制校验。
- 单文件 SLA：典型 < 1 秒（含已加载模型）。首次进程启动加载 SentenceTransformer 约 15 秒。
- 200 题增量需求约束 5 分钟内生效，单文件远低于此阈值。

**错误**：

| HTTP | error_type | 含义 |
|---|---|---|
| 400 | `invalid_params` | 没提供或同时提供多个 add/modify/delete |
| 404 | `file_not_found` | add/modify 时 `file_path` 在 `data/` 下不存在 |
| 400 | `unsupported_format` | 扩展名不支持（如 `.exe`）|
| 400 | `parse_failed` | 解析器抛异常（PDF 加密 / 文件损坏）|
| 500 | `embedding_timeout` | embedding 重试 N 次仍失败 |
| 500 | `db_error` | SQLite 异常 |

错误响应体（统一结构）：

```json
{
  "detail": {
    "status": "error",
    "error_type": "parse_failed",
    "detail": "PDF 加密文件不支持"
  }
}
```

---

## 联调专用接口（开关控制）

### POST `/upload`（联调用，受 INGESTION_UPLOAD_ENABLED 开关控制）

⚠️ **此端点默认关闭**——`INGESTION_UPLOAD_ENABLED=true ./start.sh` 才注册。

接收 multipart/form-data 文件，**两阶段分离**：阶段 1 全部落地，阶段 2 才（可选）索引。

**Request**:

```
POST /upload?index=true|false
Content-Type: multipart/form-data

Form fields:
  files: 文件数组（最多 200，单文件 ≤ 50 MB）
         同名字段重复出现 = 多文件，不是逗号分隔字符串

Query parameters:
  index: 可选，默认 false。true 表示阶段 1 完成后串行 await 索引每个 saved 文件
         （多文件累加耗时，client timeout 应设 ≥ N×60s）
         ⚠️ 批量场景（>10 个）建议 index=false 后另调 /index，避免单连接长阻塞
```

**Response 200**（成功，含部分单文件级 error）:

```json
{
  "success": true,
  "uploaded": [
    {"filename": "doc.docx", "size": 73728, "status": "saved"},
    {"filename": "evil.exe", "status": "error", "error_type": "unsupported_format",
     "detail": "扩展名 .exe 不在白名单"}
  ],
  "indexed": [
    {"filename": "doc.docx", "chunks": 511, "elapsed_s": 7.7}
  ]
}
```

**请求级错误**（HTTP 400/422，整批拒绝）：

| HTTP | detail | 触发 |
|---|---|---|
| 422 | FastAPI 默认 unprocessable | 完全没传 `files` 字段 / 空 files 列表 |
| 400 | `path_traversal_detected` | 任一文件名含 `..` / `/` / `\`（安全攻击）|
| 400 | `too_many_files: {n} > 200` | 单次 > 200 文件，n 是实际数 |
| 404 | （路由未注册）| 开关 OFF |

**单文件级错误**（HTTP 200 中 status="error"）：

| error_type | 触发 |
|---|---|
| `invalid_filename` | 空 / 长度 > 255 / 非法字符无法清理 |
| `unsupported_format` | 扩展名不在白名单（.docx/.pdf/.xlsx/.pptx/.md/.txt）|
| `oversized` | 单文件 > 50 MB |
| `parse_failed` / `embedding_timeout` 等 | 阶段 2 索引失败（snake_case，参见 `common/errors.py`）|

**curl 示例**：

```bash
INGESTION_UPLOAD_ENABLED=true ./start.sh

# 仅上传，不索引
curl -F "files=@/path/to/doc.pdf" http://localhost:3003/upload

# 上传 + 自动索引（同步等待）
curl -F "files=@/path/to/doc.pdf" "http://localhost:3003/upload?index=true"
```

📖 设计 spec：[`docs/superpowers/specs/2026-04-27-upload-endpoint-design.md`](../../docs/superpowers/specs/2026-04-27-upload-endpoint-design.md)

---

## 监控接口

### GET `/stats`

```bash
curl http://localhost:3003/stats
# {"documents":12,"chunks":504,"index_size_mb":8.3}
```

### GET `/health`

```bash
curl http://localhost:3003/health
# {"status":"ok","db_writable":true,"embedding_model_loaded":false}
```

`embedding_model_loaded` 是模型懒加载状态——首次 `/index` 调用后才会变 true（不影响功能，仅观测）。

---

## 字段对齐 `backend/reasoning/interfaces.py`

我们的 `metadata` 字段与 reasoning 层 `ChunkMetadata` 的映射：

| 我们返回的字段 | `interfaces.ChunkMetadata` | 备注 |
|---|---|---|
| `metadata.file_path` | `file_path` | 必填 |
| `metadata.anchor_id` | `anchor_id` | 必填，格式 `file_path#char_offset` |
| `metadata.title_path` | `title_path` | 可空 |
| `metadata.last_modified` | `last_modified` | ISO8601，MVP 为 null |

**注意**：`content_type` 和 `is_truncated` 在 `interfaces.RetrievedChunkResponse` 是顶层字段（不在 `metadata` 内），你在转换时需要把它们从我们的 `metadata` 里提出来放顶层。

---

## 联调步骤（推荐你按这个顺序测）

### 1. 启动服务（终端 A，保持运行）

```bash
python -m backend.ingestion.api.server
```

### 2. 准备样本数据（终端 B）

```bash
mkdir -p data/docs/react
cp src/backend/ingestion/tests/fixtures/sample.md data/docs/react/
```

`sample.md` 是个 13 行的 markdown，含 OAuth2 / Installation / API Reference 三段。

### 3. 索引（首次调用会加载 bge-m3，约 15s）

```bash
curl -X POST 'http://localhost:3003/index?add=docs/react/sample.md'
# {"status":"indexed","chunk_count":3,...}
```

### 4. 全文搜（验证 BM25 接口）

```bash
curl -X POST http://localhost:3003/chunks/text-search \
  -H "Content-Type: application/json" \
  -d '{"query":"OAuth2","top_k":3}'
```

应该看到一个 chunk，content 干净（不含其它段标题）。

### 5. 向量搜（你算 query embedding 测）

```python
from sentence_transformers import SentenceTransformer
import json, urllib.request

model = SentenceTransformer("BAAI/bge-m3")
query_emb = model.encode("token refresh", normalize_embeddings=True).tolist()
assert len(query_emb) == 1024

req = urllib.request.Request(
    "http://localhost:3003/chunks/vector-search",
    data=json.dumps({"embedding": query_emb, "top_k": 3}).encode(),
    headers={"Content-Type": "application/json"},
)
print(urllib.request.urlopen(req).read().decode())
```

### 6. 按 ID 取 chunk（拿完整 embedding 测）

```bash
# 从 step 4 的输出复制 chunk_id
curl http://localhost:3003/chunks/<paste_chunk_id_here>
```

### 7. RRF 融合伪代码（参考）

```python
def rrf(vector_results, text_results, k=60):
    scores = {}
    for rank, r in enumerate(vector_results):
        scores[r["chunk_id"]] = scores.get(r["chunk_id"], 0) + 1 / (k + rank + 1)
    for rank, r in enumerate(text_results):  # 已按 bm25_rank 排序
        scores[r["chunk_id"]] = scores.get(r["chunk_id"], 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
```

---

## 已知限制（MVP 范围）

- `filters` 字段保留但**不实现**（min_timestamp / file_paths 过滤）
- vector-search MVP 用 Python 端全表 cosine（< 10k chunks 性能 OK，~100ms）。P1 升级 sqlite-vec 扩展可 10x 加速
- `metadata.last_modified` 暂为 null（避免每次 search JOIN documents 表）。如果你需要，告诉我加上
- `content_type` 暂全部 `document`（不分派 code / structured_data，已是团队共识）

---

## X1.5 search 接口字段语义（重要）

自 X1.5 实施起（spec: `docs/superpowers/specs/2026-04-30-x15-rigorous-design.md`），`vector-search` / `text-search` 接口的字段语义变化：

### 不变（保契约）

- `chunk_id`：DB sha256 真主键，组内分最高 chunk 的代表，可用 by-id 反查
- `metadata.title_path`、`metadata.is_truncated`、其它从代表 chunk 继承
- `total` 字段 = `len(results)`，分组合并后的返回条数（不是原始命中行数）

### 跟随 content 走（X1.5 路径）

- `content` = `title_path + "\n\n" + raw_slice (max_chars=2000 居中截)`（仅 SECTION 路径加 title prefix；UNTITLED_SEG 路径不加）
- `metadata.char_offset_start` = window 起点（**不是代表 chunk 的 offset**）
- `metadata.char_offset_end` = window 终点
- `metadata.anchor_id` = `f"{file_path}#{char_offset_start}"`，跟着 window 起点

### 新增（赛题输出用）

- `metadata.markdown_anchor`：section 标识（如 `#api-发起驱逐` / `#top`），**赛题判分按这字段**
- `metadata.is_x15_truncated`：X1.5 截断标记

### 收缩（合并影响）

- 同 `(file_path, title_path)` 内多个命中合并为 1 个 result
- title_path 空的 chunks 按同 file_path + chunk_index 物理连续切段（避免跨文件位置误并）
- 30 个候选可能收缩到 ~15-20 个 result

### by-id 接口不变

- `GET /chunks/{chunk_id}` 仍返回单 chunk 原 content（不 X1.5 化）
- metadata 也含 `markdown_anchor` / `is_x15_truncated=false`（复用 `_row_to_metadata`）

### feature flag 应急回滚

- env var `INGESTION_X15_ENABLED`，默认 `true`
- 应急：设 `false` 重启 ingestion 服务（30 秒回滚到 X0 行为）

### Layer 2 映射建议（**海军 team 改动**）

ingestion 当前已透传整个 metadata 到海军 retrieval.py 的 Document.metadata，所以 `markdown_anchor` 已自动传到 reasoning。但 reasoning/main.py 的 anchor 提取优先级需要 1 行改动：

```python
# backend/reasoning/main.py:92
anchor: str = (
    meta.get("markdown_anchor")    # ← 加这一行（X1.5 字段优先）
    or meta.get("anchor")
    or meta.get("anchor_id")
    or ""
)
```

不改的话：reasoning 输出的 citation.anchor 仍是 char_offset 形式（`#1234`），跟赛题 gold anchor（`#data-fetching` 等）对不上，丢分。

---

## 联系方式

接口字段需要调整、有 bug、有性能问题，直接告诉我（涂祎豪），改完会同步更新这份文档。
