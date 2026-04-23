# 技术文档智能问答与引用溯源系统

> **赛题背景**
>     "能否基于一批文档回答问题、且准确引用出处、不知道就说不知道"，是 Context Engineering 最基本的考查点。本题用公开技术文档作为语料，不涉及任何内部知识库。
> 
> **核心任务**
> 
> 1. 对评委会给定的文档集构建检索问答系统
> 2. 每次回答必须附带至少一条出处（文档路径 + 段落 anchor）
> 3. 对文档中不存在答案的问题，必须明确拒答而非幻觉
> 4. 支持文档增量更新（新增/修改/删除后 5 分钟内生效）
> 5. 提供 WebUI 供评委交互

---

## 系统整体架构

```
上传/文件系统
     │
     ▼
[文档解析 & 切分]  ──→  [Elasticsearch 8.x]           ←──  [PostgreSQL 元数据库]
     │                    (BM25 + Dense kNN + Sparse)        (Path / Hash / Anchor)
     │                         │
     ▼                         ▼
[增量同步 Pipeline]   [查询扩展 Query Expansion]
                               │
                               ▼
                      [三路召回 + RRF 融合]
                      BM25 + Dense + ColBERT
                               │
                               ▼
                        [Reranker 精排]
                        (语义兜底修正)
                               │
                    ┌──────────┴──────────┐
                    │ max_score < 0.4?    │
                   YES                   NO
                    │                    │
               直接拒答            [LLM 推理]
                                        │
                               [引用验证 Pipeline]
                                   (同步 + 异步)
                                        │
                                   返回响应 + UI 展示
```

---

## 1. 数据处理层

### 1.1 文档解析

不同文件类型使用对应解析器，统一输出结构化文本块：

| 文件类型            | 解析器            |
| --------------- | -------------- |
| Markdown / HTML | `Docling`      |
| PDF（文字版）        | `Unstructured` |
| PDF（扫描版）        | `PaddleOCR`    |
| Word / EPUB     | `Unstructured` |

解析输出格式：

```json
{
  "file_path": "docs/api/authentication.md",
  "title_path": ["Authentication", "OAuth2", "Token Refresh"],
  "char_offset_start": 4821,
  "char_offset_end": 5340,
  "raw_text": "..."
}
```

**Anchor 设计（双字段，职责分离）：**

- `anchor_id`（主键，程序定位用）：`文件路径 + char_offset_start`，例如 `docs/api/auth.md#4821`
- `title_path`（可读性附属字段，UI 展示用）：`Authentication > OAuth2 > Token Refresh`

两者同时存储于元数据库，UI 点击跳转使用 `anchor_id` 精确定位，引用展示使用 `title_path` 增强可读性。对于无标题的文档（纯文本、配置文件等），`title_path` 留空，仅使用 `anchor_id`，系统不因此降级。

### 1.2 Chunk 切分策略

采用**滑动窗口 + 语义段落感知**切分：

- 窗口大小：512 tokens
- 重叠：128 tokens（保障跨段落问题的上下文连续性）
- 优先在段落边界处切分，避免在句子中间断开
- 每个 Chunk 元数据记录三级溯源链：`文件 → 章节（title_path）→ Chunk（anchor_id）`

Chunk 元数据结构：

```json
{
  "chunk_id": "uuid-xxxx",
  "file_path": "docs/api/authentication.md",
  "file_hash": "sha256:aabbcc...",
  "anchor_id": "docs/api/authentication.md#4821",
  "title_path": "Authentication > OAuth2 > Token Refresh",
  "char_offset_start": 4821,
  "char_offset_end": 5340,
  "token_count": 487,
  "embedding": [...]
}
```

### 1.3 混合存储

**Elasticsearch 8.x（唯一检索引擎）：**

统一承载 BM25 全文检索、kNN 向量检索和 RRF 融合。

```
Index: doc_chunks
├── chunk_id          (keyword)
├── file_path         (keyword)
├── anchor_id         (keyword)
├── title_path        (text)
├── content           (text, 用于 BM25)
├── embedding         (dense_vector, dims=1024, 用于 Dense kNN)
└── sparse_embedding  (sparse_vector, 用于 ColBERT 稀疏召回)
```

**PostgreSQL（元数据库）：**

存储文档级管理信息，不参与检索。SQLite 在单机场景下也可替代，零配置、无服务依赖。

```sql
CREATE TABLE documents (
    file_path       TEXT PRIMARY KEY,
    file_hash       TEXT NOT NULL,        -- 整文档 SHA-256，用于增量判断
    index_status    TEXT DEFAULT 'pending', -- pending / indexed / error
    error_detail    TEXT,                 -- 具体错误类型，非空时 UI 展示
    indexed_at      TIMESTAMP,
    chunk_count     INT
);
```

### 1.4 增量同步（解决 watchdog 与 WebUI 上传冲突）

增量触发来源有两条路径，必须统一到同一 Pipeline 并加锁防重：

```
路径 A：WebUI 上传
  FastAPI /upload 接口接收文件
       │
       ▼
  保存到 /data/docs/ 目录
       │
       └──→ 直接调用 index_pipeline(file_path)  ← 主路径，优先

路径 B：外部文件变更（评委直接拷贝文件到目录）
  watchdog 监听 /data/docs/
       │
       ▼
  检测到 created / modified / deleted 事件
       │
       └──→ 调用 index_pipeline(file_path)      ← 兜底路径
```

`index_pipeline` 内部加文件级分布式锁，同一文件的并发触发只执行一次：

```python
def index_pipeline(file_path: str):
    with file_lock(file_path):              # 防止路径A和路径B同时触发
        new_hash = sha256(file_path)
        old_hash = db.get_hash(file_path)

        if new_hash == old_hash:
            return  # 内容未变，跳过

        db.set_status(file_path, "pending")

        try:
            chunks = parse_and_chunk(file_path)      # 解析 + 切分
            es.delete_by_file(file_path)             # 删除旧 chunks
            es.bulk_index(chunks)                    # 写入新 chunks
            db.update(file_path, hash=new_hash,
                      status="indexed", chunk_count=len(chunks))
        except ParseError as e:
            db.set_status(file_path, "error",
                          detail=f"解析失败: {e.type}，请确认文件未加密或格式正确")
        except Exception as e:
            db.set_status(file_path, "error", detail=str(e))
```

**删除处理：** watchdog 监听到 `deleted` 事件时，调用 `es.delete_by_file(file_path)` 并从元数据库移除记录。

### 1.5 5分钟 SLA 保障

**时间估算（单文档，单机）：**

| 文档规模        | 解析   | 切分 + Embedding | 写入 ES | 合计      |
| ----------- | ---- | -------------- | ----- | ------- |
| 小文档（< 50页）  | ~5s  | ~20s           | ~5s   | ~30s    |
| 中等（50~200页） | ~20s | ~80s           | ~15s  | ~2min   |
| 大文档（> 200页） | ~60s | 并发分批处理         | ~30s  | ~3~4min |

对大文档采用**分片并发 Embedding**（8 个 worker 并发调用 bge-m3），确保 200 页以内文档在 5 分钟内完成索引。

UI 的 `pending` 状态显示预计完成时间：

```
⏳ 正在索引... 预计还需 2 分钟（已完成 34%）
```

---

## 2. 检索增强层

### 2.1 查询扩展（Query Expansion）

**问题背景：** bge-m3 是通用多语言模型，在以下场景存在语义理解局限：

- **专业术语漂移**：`RAFT`、`gRPC`、`CRD` 等技术专有名词的向量表示可能和通用语义混淆，导致召回偏离
- **短查询语义稀疏**：评委提问往往很短（如"超时配置"），短文本 embedding 向量信息密度低，召回方差大
- **中英混合对齐偏差**：技术文档中文描述 + 英文术语混排，跨语言语义对齐得分偏低

**解决方案：查询扩展 + 三路召回**

在向量检索前对原始查询做轻量扩展，增强语义覆盖面：

```python
def expand_query(query: str) -> str:
    """调用 LLM 生成同义表达，拼接后统一 embed，token 消耗极小"""
    expansions = llm.generate(
        f"给出以下技术问题的2个同义表达，仅输出问题本身，换行分隔，不加序号：\n{query}"
    )
    return query + " " + " ".join(expansions.strip().split("\n"))

# 示例：
# 原始查询：  "超时配置"
# 扩展后：    "超时配置 连接超时设置 timeout configuration"
```

### 2.2 三路召回（统一在 Elasticsearch 内完成）

利用 ES 8.x 原生混合检索，BM25、Dense kNN、ColBERT Sparse 三路在单次查询内完成，RRF 融合直接由 ES 返回：

- **BM25**：关键词匹配，弥补向量检索对专业术语的语义漂移
- **Dense kNN**（bge-m3 单向量）：语义相似度召回，覆盖同义表达
- **ColBERT Sparse**（bge-m3 多向量）：对短查询效果更稳，信息密度更高

```json
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query": { "match": { "content": "{expanded_query}" } }
          }
        },
        {
          "knn": {
            "field": "embedding",
            "query_vector": [...],
            "num_candidates": 100
          }
        },
        {
          "knn": {
            "field": "sparse_embedding",
            "query_vector": "{colbert_sparse_vector}",
            "num_candidates": 100
          }
        }
      ],
      "rank_window_size": 50,
      "rank_constant": 60
    }
  },
  "size": 20
}
```

RRF 融合公式：`score(d) = Σ 1 / (k + rank_i(d))`，无需调参，跨分布稳定。

**Reranker 作为语义兜底：** `bge-reranker-v2-m3` 的 cross-encoder 结构会重新计算查询与 chunk 的完整语义相关性，能纠正召回阶段的语义漂移，是第二道语义修正关卡。

### 2.3 自适应 TopK

根据问题类型用关键词规则动态调整 TopK，无需分类模型：

```python
def get_top_k(query: str) -> int:
    BROAD_KEYWORDS  = ["所有", "列举", "比较", "对比", "区别", "有哪些", "分别"]
    SIMPLE_KEYWORDS = ["是什么", "是多少", "什么时候", "谁是", "版本号"]

    if any(kw in query for kw in BROAD_KEYWORDS):
        return 8   # 综合型问题，扩大召回
    if any(kw in query for kw in SIMPLE_KEYWORDS):
        return 3   # 事实型问题，精确召回
    return 5       # 默认值
```

### 2.4 Reranker 精排与过滤

使用 `bge-reranker-v2-m3` 对 TopK 结果重新打分：

```
召回 TopK 结果
      │
      ▼
bge-reranker-v2-m3 打分
      │
      ▼
跨文档语义去重（余弦相似度 > 0.95 的 chunk 对，保留 title_path 更深 / 更新的）
      │
      ▼
按 reranker_score 降序排列
      │
  ┌───┴───────────────┐
  │  max_score < 0.4？ │   ← 硬性门控，代码判断，不经过 LLM
  │       YES         │
  └────────┬──────────┘
           │ NO
           ▼
  硬截断，保留 token < 6k（从高分 chunk 开始保留，截断时在 prompt 中注明"context 可能不完整"）
           │
           ▼
      进入 LLM 推理
```

---

## 3. 推理与引用层

### 3.1 上下文注入格式

每个 Chunk 包装为：

```
[ID: 1, Source: docs/api/auth.md#4821 | Authentication > OAuth2 > Token Refresh]
Token 刷新接口需在请求头中携带 Authorization: Bearer {refresh_token}...
```

### 3.2 提示词

```
你是一个严格的技术文档问答助手。

规则：
1. 仅根据下方提供的 Context 回答，严禁使用任何外部知识。
2. 每个事实性陈述句末必须标注来源，格式为 [n]（n 为对应 Chunk 的 ID）。
3. 如果 Context 中不包含回答所需信息，直接回复："根据现有文档无法回答此问题。"
4. 如果 Context 标注了"可能不完整"，可说明信息不足并建议查阅原文。
5. 不得合并多个 Chunk 的内容进行推断，每条引用必须有直接支撑。

Context：
{context_blocks}

问题：{query}
```

### 3.3 引用验证 Pipeline（分级，不阻塞响应）

**同步验证（< 10ms，阻塞响应链路）：**

检查 LLM 输出中引用的所有 `[n]` ID 是否真实存在于本次检索到的 Chunk 列表。如发现无效 ID，自动剔除该引用标记并在响应中注明。

**异步验证（不阻塞，后台执行）：**

对回答中的关键名词、数字、版本号进行 token 级匹配，验证其是否出现在对应 Chunk 原文中。结果写入质量日志，在 UI 引用旁异步回填可信度标记：

- `✓`：关键内容在原文中找到支撑
- `?`：匹配不确定，建议核查原文

```python
async def verify_citations_async(answer: str, chunks: list[Chunk]):
    for citation_id, claim in extract_claims(answer):
        chunk = chunks[citation_id]
        key_tokens = extract_key_tokens(claim)  # 名词、数字、版本号
        matched = all(tok in chunk.raw_text for tok in key_tokens)
        await db.write_citation_quality(citation_id, matched)
        await ws.push_ui_update(citation_id, "✓" if matched else "?")
```

---

## 4. Web UI 层

前端 `Next.js`，后端 `FastAPI`

### 布局

```
┌─────────────────┬──────────────────────────────┬──────────────────┐
│   文档管理面板   │         对话区                │  Chunk 预览面板  │
│                 │                              │  （可折叠）       │
│ ▸ auth.md  ✓   │  Q: OAuth2 如何刷新 Token？   │ [Chunk #1]       │
│ ▸ deploy.md ✓  │                              │ Source: auth.md  │
│ ▸ config.pdf ⏳│  A: Token 刷新需在请求头携带  │ #4821            │
│   34% 预计2min  │  refresh_token [1]。有效期   │ score: 0.87      │
│                 │  默认 7 天 [2]。             │ ──────────────── │
│ [+ 上传文档]    │                              │ [Chunk #2]       │
│                 │  引用列表 ▼                  │ Source: ...      │
│ 状态图例：      │  [1] auth.md > OAuth2 >      │                  │
│ ✓ indexed       │      Token Refresh  ✓        │                  │
│ ⏳ pending      │  [2] auth.md > Token Expiry  │                  │
│ ✗ error(详情)   │      ?  ← 可信度待验证       │                  │
└─────────────────┴──────────────────────────────┴──────────────────┘
```

### 关键交互细节

- **引用链接**：点击 `[1]` 跳转原文，使用 `anchor_id` 精确定位（`file_path#char_offset`），展示 `title_path` 作为可读文本
- **可信度标记**：`✓` / `?` 异步回填，初始显示为灰色，验证完成后更新
- **错误状态**：`✗ error` 展示具体原因，例如"PDF 解析失败，请确认文件未加密"，可点击重试
- **进度展示**：`pending` 状态显示百分比 + 预计剩余时间
- **拒答展示**：拒答响应同样附带"召回得分不足（max: 0.31）"的调试信息，供评委验证检索质量
