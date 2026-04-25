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
| `file_path` 格式 | **相对 `backend/storage/raw/` 的路径，不带 `raw/` 前缀**。例：`backend/storage/raw/api/auth.md` → `file_path = "api/auth.md"` |
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
| [`/index`](#post-index) | POST | 触发索引一个文件 | entrance（陈一赓）|
| [`/files`](#delete-files) | DELETE | 删除一个文件的所有 chunks | entrance / 维护 |
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
        "file_path": "api/auth.md",
        "anchor_id": "api/auth.md#38",
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
| `metadata.file_path` | string | 文件路径（相对 raw/）|
| `metadata.anchor_id` | string | `{file_path}#{char_offset_start}`，前端跳转锚点 |
| `metadata.title_path` | string \| null | `Section > Subsection` 面包屑路径，无 heading 时 null |
| `metadata.char_offset_start/end` | int | content 在原文中的字符区间（含端点）|
| `metadata.is_truncated` | bool | 是否硬切产生（超长单句）。true 时 reranker/LLM 应注明"内容可能不完整"|
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

触发索引一个文件。文件必须先存在于 `backend/storage/raw/` 下。

**Request**:

```json
{ "file_path": "api/auth.md" }
```

**Response 200**:

```json
// 新文件或内容变化
{
  "status": "indexed",
  "chunk_count": 7,
  "file_hash": "938e3a40..."
}

// 同一文件重复调用，hash 没变
{ "status": "unchanged" }
```

**错误**：

| HTTP | error_type | 含义 |
|---|---|---|
| 404 | `file_not_found` | `file_path` 在 `backend/storage/raw/` 下不存在 |
| 400 | `unsupported_format` | 扩展名不支持（如 `.exe`）|
| 400 | `parse_failed` | 解析器抛异常（PDF 加密 / 文件损坏）|
| 500 | `embedding_timeout` | bge-m3 重试 5 次仍失败 |
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

**注意**：
- 处理失败时 raw/ 文件不删（让 entrance 决定重试）
- 大文件可能耗时 1-5 分钟，建议 fetch 超时设 ≥ 5 分钟

---

### DELETE `/files`

删除一个文件的所有 chunks（CASCADE 删 chunks_fts）。

**Request**:

```json
{ "file_path": "api/auth.md" }
```

**Response 200**:

```json
{ "status": "deleted", "deleted_chunks": 7 }
```

如果文件不在库里：

```json
{ "status": "not_found" }
```

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
cp backend/ingestion/tests/fixtures/sample.md backend/storage/raw/
```

`sample.md` 是个 13 行的 markdown，含 OAuth2 / Installation / API Reference 三段。

### 3. 索引（首次调用会加载 bge-m3，约 15s）

```bash
curl -X POST http://localhost:3003/index \
  -H "Content-Type: application/json" \
  -d '{"file_path":"sample.md"}'
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

## 联系方式

接口字段需要调整、有 bug、有性能问题，直接告诉我（涂祎豪），改完会同步更新这份文档。
