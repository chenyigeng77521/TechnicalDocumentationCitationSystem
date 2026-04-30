# X1.5 严谨版：search 接口返回 section 全量 + 标题前缀

## 外行版摘要

**1. 做什么？**

改 `backend/ingestion` 检索 API 的 `_format_result` 一个函数，让海军 reranker 看到的 `content` 字段从"单个零碎片段"换成"标题路径 + 整 section 文字"。**契约变化**：

- **`chunk_id` 不变**：仍是 DB 真主键（组内分最高 chunk 代表），by-id 接口可反查
- **`anchor_id` / `char_offset_*` 跟着 content 走**：X1.5 路径时 anchor_id = `f"{file_path}#{win_start}"`，char_offset = `[win_start, win_end]`（window 范围）；X0/SINGLE 退化路径时仍是单 chunk 范围
- **返回数量按 section 合并后会收缩**：30 个候选可能合成 ~15-20 个 result（X1.5 的核心改动之一）
- **新增字段**：`metadata.markdown_anchor`（赛题 citation 用）+ `metadata.is_x15_truncated`（max_chars 截断标记）

**2. 为什么需要？**

当前痛点：海军 reranker 看零碎单 chunk 没标题信息（比如一个步骤列表 chunk 没"驱逐"二字），给低分，找不到答案。

POC 已验证：拼上 title_path + 整 section 内容，reranker 分数从 0.01 升到 0.99，两个长期跑不出答案的 query（K8s "API 发起驱逐的工作原理"、React "数据获取库"）都从 top-3 不含答案变成 top-3 含答案。

**3. 大致怎么做？**

- 改一个文件的一个函数：`backend/ingestion/api/routes_search.py::_format_result`
- 把命中 chunk 按 `(file_path, title_path)` 分组，每组合并成 1 个 result
- content = `title_path + "\n\n" + 源文件按 offset 切片`
- 长 section 居中截到 2000 字符（命中点居中）
- chunk_id 取组内分最高的（保 DB 主键契约）
- metadata 新增 `markdown_anchor` 字段（赛题判分用）
- 失败时退回单 chunk 原 content（API 永不挂）
- env var `INGESTION_X15_ENABLED` 默认 true，应急时改 false 重启回滚

**4. 主要风险**

| 风险 | 缓解措施 |
|---|---|
| 长 section 截断丢答案 | 命中点居中截，3 档策略覆盖所有长度场景 |
| 文件读不出 / DB drift | 抓异常退回 X0 行为 + WARNING 日志 |
| 跨 team 上线依赖 | 海军侧需同步把 `RetrievedChunk.anchor` 映射自 `metadata.markdown_anchor`，spec 写入"上线依赖"段 |
| POC 没覆盖的边角 case | env var feature flag 30 秒回滚 |

---

## 正文

### 1. 改造范围

**改动文件**：

| 文件 | 改动 |
|---|---|
| `backend/ingestion/api/routes_search.py` | `_format_result` 重写为 X1.5 化；env var flag；分组逻辑入口；`_row_to_metadata` 加 `markdown_anchor` + `is_x15_truncated`（默认 False）字段 |
| `backend/ingestion/api/x15.py`（新增） | 切片 / 分组 / 居中截 / LRU 缓存 等核心逻辑。**对外暴露的 helper**：`group_results` / `_format_result_x15` / `get_section_full_range` / `_read_raw_file` / `make_window`。baseline 脚本和单测都 import 这些 helper（不允许复制粘贴重新实现） |
| `backend/ingestion/INTERFACE.md` | 加 `metadata.markdown_anchor` / `metadata.is_x15_truncated` 字段说明 + Layer 2 映射注释 |

**不改动**：
- DB schema（`markdown_anchor` 列已在）
- `chunks_repo.py` SQL（已是 `SELECT *` / `SELECT c.*`，自动包含 markdown_anchor 列）
- chunker 逻辑
- `/chunks/{chunk_id}` by-id 接口（保持单 chunk 原文返回，不做 X1.5 化；但 metadata 也会暴露新增字段，因为复用 `_row_to_metadata`）
- 海军 retrieval.py / reasoning（spec 仅声明依赖，由对应 team 同步改）

### 2. 核心算法

#### 2.1 分组（Group）

```python
def assign_group_key(chunk: dict) -> tuple:
    title_path = chunk.get('title_path') or ''
    if not title_path:
        # title_path 空 ≡ markdown_anchor=#top（数据验证 100% 对应）
        # 单 chunk 退化路径，避免跨文件误并
        return ('SINGLE', chunk['chunk_id'])
    return ('SECTION', chunk['file_path'], title_path)
```

**为什么用 title_path 不用 markdown_anchor**：数据验证 `(file_path, title_path)` 分组 100% 物理连续；用 markdown_anchor 分组时 #top 组 46% 不连续（最大跨度 64K 字符）。详见名词解释。

**显式假设 + 数据校验脚本**：

> **假设**：`(file_path, title_path)` 在当前语料里**唯一标识同一个物理 section**（同 key 的 chunks 必然 chunk_index 连续 + offset 区间不重叠）。

**风险**：未来若 chunker 升级 / 文档新增 / reindex 引入边角 case（同文件下两个不同 section 共享相同 title_path 文本），分组逻辑会**静默误并**这两段。

**缓解**（写进 Phase 2 任务）：新增数据校验脚本 `backend/ingestion/scripts/verify_section_grouping.py`，启动时 / CI 跑：

```python
def verify_section_grouping(conn) -> list[str]:
    """检查所有 (file_path, title_path) 分组的 chunk_index 连续性。返回违规组列表。"""
    rows = conn.execute("""
        SELECT file_path, COALESCE(title_path,'') AS tp,
               GROUP_CONCAT(chunk_index ORDER BY chunk_index) AS idx_list,
               COUNT(*) AS cnt
        FROM chunks
        GROUP BY file_path, COALESCE(title_path,'')
        HAVING cnt > 1
    """).fetchall()
    violations = []
    for r in rows:
        indices = [int(x) for x in r['idx_list'].split(',')]
        if any(indices[i+1] - indices[i] != 1 for i in range(len(indices)-1)):
            violations.append(f"{r['file_path']} | {r['tp']}: {indices}")
    return violations
```

**用法**：
- CI / 单元测试调用：违反假设时 fail，强迫人工排查
- 上线前手动跑一次确认

#### 2.2 居中截窗口（Window）

```python
def make_window(section_start: int, section_end: int,
                hits: list[dict], max_chars: int = 2000) -> tuple[int, int, bool]:
    """返回 (win_start, win_end, is_truncated)。"""
    section_len = section_end - section_start
    if section_len <= max_chars:
        return section_start, section_end, False  # Case 1: 整 section 装得下

    hit_min = min(h['char_offset_start'] for h in hits)
    hit_max = max(h['char_offset_end'] for h in hits)

    if hit_max - hit_min <= max_chars:
        # Case 2: 命中点 union 装得下，按命中点居中
        center = (hit_min + hit_max) // 2
    else:
        # Case 3: 命中点跨度过大，按最高分命中点居中
        top_hit = max(hits, key=lambda h: h['score'])
        center = (top_hit['char_offset_start'] + top_hit['char_offset_end']) // 2

    half = max_chars // 2
    win_start = max(section_start, center - half)
    win_end = min(section_end, center + half)

    # 边界回弹：一边碰壁把空间补给另一边
    if win_end - win_start < max_chars:
        if win_start == section_start:
            win_end = min(section_end, win_start + max_chars)
        else:
            win_start = max(section_start, win_end - max_chars)

    return win_start, win_end, True
```

**heading duplication 问题（明确接受）**：raw_slice 切的是源文件原始字符（含 markdown 标题行如 `## API 发起驱逐`）。当 win_start 落在标题前时，`title_path + "\n\n" + raw_slice` 会出现 heading 重复（一份在 prefix，一份在 raw_slice 头部）。**这是允许的设计**，理由：
- reranker 对小量重复鲁棒（不会因为 heading 出现两次给负分）
- 主动去重需识别"标题在 raw_slice 起始处"的边界，引入复杂度且容易切错
- title_path 是层级路径形式（"K8s / 资源管理 / 驱逐"），跟原始 heading 文本（"## API 发起驱逐"）通常不完全一致，去重判断不平凡

如未来 reranker 实测受影响，再加 heading 去重逻辑（不在本 spec scope 内）。

**3 档分布预期**（基于 1598 section 数据）：
- Case 1 整 section 全保 ≈ 70%
- Case 2 命中点 union 居中 ≈ 25-29%
- Case 3 跨度过大用最高分居中 < 1%

#### 2.3 section 真边界查询

**关键设计点**：`section_start` / `section_end` 必须取**同 (file_path, title_path) 全部 chunks** 的 offset union，**不能只看召回命中的 chunks**。否则 section 内只有 1 个 chunk 被命中时，"section 全量" 退化成单 chunk 大小。

```python
def get_section_full_range(conn, file_path: str, title_path: str) -> tuple[int, int]:
    """查同 section 全部 chunks（含未命中的）的 offset union 范围。"""
    row = conn.execute(
        """SELECT MIN(char_offset_start) AS s, MAX(char_offset_end) AS e
           FROM chunks
           WHERE file_path = ?
             AND COALESCE(title_path, '') = COALESCE(?, '')""",
        (file_path, title_path),
    ).fetchone()
    if row is None or row["s"] is None:
        raise ValueError(f"no chunks for ({file_path}, {title_path!r})")
    return row["s"], row["e"]
```

**调用时机**：每个 SECTION group 一次（不是每个 result 一次）。可加进程级简易缓存（按 (file_path, title_path) key），key 数量上限 = section 总数 ~1600，全装内存可忽略。

**简易 LRU**：

```python
@functools.lru_cache(maxsize=2000)
def _cached_section_range(file_path: str, title_path: str) -> tuple[int, int]:
    # 注：必须传 conn，但 lru_cache 不能 hash conn；实际实现用 module-level dict 或在调用层传 conn
    ...
```

实际实现里因为 conn 不能作 lru_cache key，会用一个简单的 module-level `dict[tuple, tuple]` 缓存（启动时空，懒加载）+ 测试 fixture 显式 clear。

#### 2.4 raw 文件读取（LRU 缓存）

```python
import functools

@functools.lru_cache(maxsize=200)
def _read_raw_file(file_path: str) -> str:
    """读源文件，CRLF 归一化（跟 chunker 入口一致）。"""
    abs_path = RAW_DIR / file_path
    text = abs_path.read_text(encoding='utf-8')
    return text.replace('\r\n', '\n').replace('\r', '\n')
```

**maxsize=200**：当前 164 文件全装；未来扩到 10K+ 文件，LRU 自动只缓存 200 个热点。内存上限 ~10MB。

**测试 fixture 必须 cache_clear**：lru_cache 跨 test case 不自动清，否则测试间状态污染。

#### 2.5 X1.5 化 _format_result

```python
def _format_result_x15(conn, group_chunks: list[dict], title_path: str) -> dict:
    """每组返回 1 个 result。group_chunks 已按 score 降序排好。"""
    representative = group_chunks[0]  # 分最高的，作 chunk_id / anchor_id 代表
    metadata_x0 = _row_to_metadata(representative)  # 默认含 is_x15_truncated=False

    if not title_path:  # SINGLE 退化路径
        return {
            'chunk_id': representative['chunk_id'],
            'content': representative['content'],
            'score': representative['score'],
            'metadata': metadata_x0,
        }

    # SECTION 合并路径
    file_path = representative['file_path']
    try:
        # 关键：从 DB 查同 section 全部 chunks（含未召回的）的 offset union
        section_start, section_end = get_section_full_range(conn, file_path, title_path)
        win_start, win_end, is_truncated = make_window(
            section_start, section_end, group_chunks, max_chars=2000
        )
        raw_slice = _read_raw_file(file_path)[win_start:win_end]
        if not raw_slice.strip():
            raise ValueError("empty raw_slice")
        content = f"{title_path}\n\n{raw_slice}"
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as e:
        logger.warning(
            "x15 fallback for %s (title=%s): %s", file_path, title_path, e
        )
        return {  # 退回 X0 行为
            'chunk_id': representative['chunk_id'],
            'content': representative['content'],
            'score': representative['score'],
            'metadata': metadata_x0,
        }

    metadata = dict(metadata_x0)
    metadata['is_x15_truncated'] = is_truncated  # X1.5 真截断时为 True；其它路径保持 False
    # 注：metadata['is_truncated'] 保留 chunker 原语义不被覆盖
    # 关键：char_offset / anchor_id 跟着 content 走（content 是 [win_start, win_end] 的切片）
    metadata['char_offset_start'] = win_start
    metadata['char_offset_end'] = win_end
    metadata['anchor_id'] = f"{file_path}#{win_start}"
    return {
        'chunk_id': representative['chunk_id'],   # DB 真主键，不变
        'content': content,
        'score': representative['score'],
        'metadata': metadata,
    }
```

#### 2.6 入口：post_vector_search / post_text_search

```python
def post_vector_search(req):
    ...
    rows = vector_search(conn, req.embedding, top_k=req.top_k)
    if not X15_ENABLED:
        return {'results': [_format_result_legacy(r) for r in rows], 'total': len(rows)}

    # 分组
    groups = defaultdict(list)
    for r in rows:
        groups[assign_group_key(r)].append(r)

    # 组内按 score 降序
    for k in groups:
        groups[k].sort(key=lambda c: -c.get('score', 0))

    # 输出顺序保留：按"组内最高分"降序
    sorted_groups = sorted(groups.items(), key=lambda kv: -kv[1][0].get('score', 0))

    results = []
    for key, members in sorted_groups:
        title_path = members[0].get('title_path') if key[0] == 'SECTION' else ''
        results.append(_format_result_x15(conn, members, title_path))

    return {'results': results, 'total': len(results)}
```

**`total` 字段语义**：等于 `len(results)`，即**分组合并后的返回条数**（不是原始命中行数）。海军侧本来就用 `len(results)` 而非 `total` 作循环计数，无适配压力。

**排序契约**：
- **主排序**：按"组内最高分"降序（Python `sorted` 稳定排序保证）
- **tie 时（组内最高分相等）**：保留 DB 返回的原始顺序（vec_search/text_search 内部已按 score 排过，稳定排序透传该顺序）
- **不依赖 chunk_id 字典序**等其他兜底，避免引入 SQLite/Python 实现细节耦合

**注**：result 数量从原 top_k 收缩到 group 数（一般少 30-50%）。海军侧已不依赖固定数量，无需适配。

### 3. metadata 字段规范

```jsonc
{
  "chunk_id": "<DB sha256 主键>",        // **DB 真主键不变**，组内分最高 chunk 代表，by-id 接口可反查
  "content": "<section 全量化文本>",      // X1.5 输出（标题前缀 + window 切片）
  "score": 0.95,
  "metadata": {
    "file_path": "kubernetes/api-eviction.md",
    // ↓ char_offset / anchor_id 跟着 content 走（X1.5 时是 [win_start, win_end] 范围，X0 时是单 chunk 范围）
    "char_offset_start": 1234,            // = win_start (X1.5) / chunk.char_offset_start (X0)
    "char_offset_end": 3234,              // = win_end (X1.5) / chunk.char_offset_end (X0)
    "anchor_id": "kubernetes/api-eviction.md#1234",  // = f"{file_path}#{char_offset_start}"
    // ↓ 其它字段从代表 chunk 继承
    "title_path": "API 发起驱逐 / 工作原理",
    "is_truncated": false,                // 不变，chunker 切片 truncate 原语义（来自代表 chunk）
    "is_x15_truncated": false,            // 新增，**所有 chunk 接口都暴露**；X1.5 真发生 max_chars 截断时为 true，其它情况（X0 路径、SINGLE 退化、by-id 接口）一律 false
    "content_type": "markdown",
    "language": "zh",
    "last_modified": "2026-04-29T10:00:00",
    "markdown_anchor": "#api-发起驱逐"     // 新增，赛题 citation 输出用（section 标识，不随 window 变化）
  }
}
```

### 4. 失败 fallback 矩阵

| 场景 | 检测点 | 行为 |
|---|---|---|
| 源文件不存在 | `FileNotFoundError` | 退 X0 + WARNING |
| OS IO 错误 | `OSError` | 退 X0 + WARNING |
| 编码错误 | `UnicodeDecodeError` | 退 X0 + WARNING |
| offset 越界 | raw_slice 为空 → `ValueError` | 退 X0 + WARNING |
| DB 查不到邻居 | group_chunks 长度=1，正常处理 | 不算失败 |
| title_path 为空 | 显式 SINGLE 路径 | 不走合并，原 content 返回 |

**X0 fallback 行为**：返回单 chunk 原 content（DB 当前行为）。

**不暴露 fallback 状态**：metadata 不加 `is_x15_fallback` 字段（API 简洁，海军无需分清，问题靠日志 grep 定位）。

### 5. feature flag

```python
import os
X15_ENABLED = os.getenv("INGESTION_X15_ENABLED", "true").lower() == "true"
```

- 默认 `true` → 生产行为是 X1.5
- 应急 `false` → 退回 X0 行为，30 秒回滚
- 1-2 周稳定后，**清理项**：删除 flag 检查 + `_format_result_legacy` 函数 + env var 文档

### 6. 跨 team 上线依赖（**仅声明，不在本 spec 实施 scope**）

**本 spec 实施范围**：仅 `backend/ingestion/` 目录内文件 + `INTERFACE.md`。海军 / reasoning 的代码改动**全部不在本 spec 工作量内**，由对应 team 在本 spec 落地后**独立排期**完成。

**ingestion 输出**：`metadata.markdown_anchor` 字段

**海军 retrieval.py 同步改动**（参考说明，由海军 team 实施）：

```python
# backend/LLM/retrieval.py
def to_retrieved_chunk(api_result: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=api_result['chunk_id'],
        content=api_result['content'],
        doc_path=api_result['metadata']['file_path'],
        anchor=api_result['metadata']['markdown_anchor'],  # ← 改这一行
        score=api_result['score'],
        is_truncated=api_result['metadata']['is_truncated'],
        title_path=api_result['metadata'].get('title_path'),
    )
```

**reasoning**：`Citation.anchor` 透传，无需改。

**部署顺序**：
1. ingestion 上线（`metadata.markdown_anchor` 暴露，海军老代码忽略新字段，不挂）
2. 海军侧改 1 行映射 + 上线
3. reasoning 重启读海军输出

任意一步出问题 → ingestion env var 回滚 X0。

### 7. 测试策略

#### 7.1 单元测试（tests/unit/）

| 文件 | 测什么 | 关键 case |
|---|---|---|
| `test_x15_window.py` | `make_window` 函数 | section ≤ max_chars 不截 / Case 2 命中点 union 居中 / Case 3 max-score 居中 / 边界回弹 / 单点命中 / 多点命中跨度过大 |
| `test_x15_grouping.py` | `assign_group_key` + 分组逻辑 | title_path 非空合并 / title_path 空 SINGLE / 多命中同 group / 多命中跨 group / 排序保 score 顺序 |
| `test_x15_raw_reader.py` | `_read_raw_file` + LRU | 缓存命中 / 文件不存在 / CRLF 归一化 / 测试间 cache_clear |
| `test_x15_format_result.py` | `_format_result_x15` 端到端 | 合并 + title prefix / SINGLE 退化 / fallback 路径 / metadata.markdown_anchor 暴露 |

#### 7.2 集成测试（tests/integration/）

`test_x15_search_api.py`：
- POST `/chunks/vector-search` 返回 content 是 section 全量
- POST `/chunks/text-search` 同样工作
- `metadata.markdown_anchor` 字段存在
- `chunk_id` 是 DB 真主键（可用 by-id 接口反查）
- `INGESTION_X15_ENABLED=false` 时退 X0 行为

`test_x15_painpoints.py`（POC 痛点回归）：
- `"API 发起驱逐的工作原理是什么"` → top-3 含 "kubelet" / "宽限期" / "EndpointSlice"
- `"从大多数后端或 REST 风格 API 获取数据时，React 建议使用哪些库"` → top-3 含 "TanStack Query" / "SWR" / "RTK Query"

`test_x15_by_id_unchanged.py`：
- GET `/chunks/{chunk_id}` 返回 single chunk 原 content（不做 X1.5 化）

#### 7.3 baseline 对比脚本

`backend/ingestion/scripts/eval_x15_baseline.py`：

```bash
python backend/ingestion/scripts/eval_x15_baseline.py \
    --test-set docs/Public_Test_Set.jsonl \
    --output /tmp/x15_baseline_result.json
```

**Hit 规则（pin 死，避免 baseline 数据歧义）**：

赛题 gold_sources 结构：

```json
{
  "doc_path": "docs/react/build-a-react-app-from-scratch.md",
  "anchor": "#data-fetching",
  "evidence": "If you're fetching data from..."
}
```

**主指标 anchor_hit**（**release gate 用这个**）：

```python
def is_anchor_hit(top3_results, gold_source) -> bool:
    """top-3 中至少 1 个 result 同时命中 gold doc_path + anchor。"""
    return any(
        r['metadata']['file_path'] == gold_source['doc_path'].removeprefix('docs/')
        and r['metadata']['markdown_anchor'] == gold_source['anchor']
        for r in top3_results
    )
```

**辅助指标 evidence_hit**（仅诊断用，不进 release gate）：

```python
def is_evidence_hit(top3_results, gold_source) -> bool:
    """top-3 中至少 1 个 result content 包含 gold evidence 子串（前 50 字符匹配）。"""
    needle = gold_source['evidence'][:50]
    return any(needle in r['content'] for r in top3_results)
```

**为什么 anchor_hit 是主指标**：赛题判分等价于 anchor 命中，不是 evidence 文本相似度。

**baseline JSON 同时输出**两个指标，方便交叉看：

```json
{
  "summary": {
    "x0_anchor_hit": 145,
    "x15_anchor_hit": 158,
    "x0_evidence_hit": 152,
    "x15_evidence_hit": 165,
    "improvement_anchor": 13
  }
}
```

**注意 file_path 前缀差异**：赛题 gold_source.doc_path 是 `docs/react/...`，ingestion 内部 file_path 是 `react/...`（无 `docs/` 前缀，见 CLAUDE.md "File-path convention"）。比较时需 `removeprefix('docs/')` 对齐。

**X0 / X1.5 双模式切换机制（pin 死避免 plan 阶段歧义）**：

baseline 脚本**不**走 HTTP，**不**通过 env var 切 X1.5_ENABLED 重启服务。直接 import 并调用 ingestion 内部底层函数：

```python
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.chunks_repo import vector_search
from backend.ingestion.api.routes_search import _format_result_legacy
from backend.ingestion.api.x15 import _format_result_x15, group_results

# 跑同一份 raw rows 两次，分别走 X0 / X1.5 格式化
rows = vector_search(conn, query_embedding, top_k=30)

# X0 路径：每个 row 直接 _format_result_legacy
x0_results = [_format_result_legacy(r) for r in rows]

# X1.5 路径：先分组再 format
groups = group_results(rows)
x15_results = [_format_result_x15(conn, members, title_path) for ...]
```

**好处**：单进程内拿到双结果，不需要重启，完全可重现。

输出 JSON 结构：

```json
{
  "summary": {
    "x0_hit_count": 145,
    "x15_hit_count": 158,
    "improvement": 13,
    "x0_only_hit": ["react_010", ...],
    "x15_only_hit": ["k8s_042", ...],
    "both_miss": ["spring_073", ...]
  },
  "per_query": [
    {
      "id": "react_002",
      "query": "...",
      "gold_evidence": "...",
      "x0_top3": [...],
      "x15_top3": [...],
      "x0_hit": true,
      "x15_hit": true
    }
  ]
}
```

**验收门槛（单一 release bar）**：`x15_hit_count ≥ x0_hit_count`（**硬性：保底不变差**）

**期望目标（非门槛，仅参考）**：`x15_hit_count ≥ x0_hit_count + 5`。如未达期望但通过门槛，可上线，但需在 commit message 里分析未达期望的原因（哪些 query 没救活、是不是 max_chars 太短、是不是 chunker 边界问题等）。

**执行假设（pin 死，避免不可重现）**：

| 维度 | 假设 |
|---|---|
| 语料快照 | 当前 `backend/storage/raw/` + `backend/storage/index/knowledge.db`（commit 6570519 时的 11491 chunks / 164 文件 / 1598 sections）。后续若 reindex 改变 chunk 切分，baseline 数据**不可跨 commit 比较**，需各自重跑。 |
| reranker 模型 | `BAAI/bge-reranker-base`（项目当前用的版本）。换模型 → baseline 重跑。 |
| embedding 模型 | `BAAI/bge-m3`（1024 维，normalize=True）。同上。 |
| 痛点回归 | **本地手动 + CI 自动跑**：单元测试和集成测试自动跑（pytest），但**痛点 query 端到端测试需要 ingestion 服务在线 + bge-m3 模型已加载**。CI 环境如不便启服务，painpoint test 标 `@pytest.mark.integration`，CI 跳过，本地手动验证。|
| 上线前验收 | baseline 脚本必须在 ingestion 服务运行的本机执行，输出 JSON 落盘到 `/tmp/x15_baseline_result.json`，作为 commit 附件（或写进 commit message 摘要）。 |

#### 7.4 Codex 双引擎交叉验证

**新增 prompt 模板**：`.claude/skills/brainstorming/test-result-reviewer-prompt.md`，专审测试结果。

**调用**：

```bash
bash .claude/skills/brainstorming/scripts/cross-review.sh \
    backend/ingestion/scripts/eval_x15_baseline.py \
    /tmp/x15_baseline_result.json
```

**Codex review 重点**：
- 测试逻辑对吗？验收条件有没有漏洞？
- 召回率提升的可信度？
- `x15_only_hit` 救活的题是否真有意义（不是巧合）？
- `x0_only_hit` 搞砸的题为什么变差？
- 整体结论站得住吗？

**触发时机**：
- spec 写完 → Codex review 设计（本次）
- 代码完成 + baseline 跑完 → Codex review 测试结果
- 上线前最终确认 → Codex review 一次

### 8. 实施任务粒度（给 writing-plans 用）

按"最小可跑 / 质量增强 / 可维护性"三阶段拆：

**Phase 1 最小可跑**：
1. `_row_to_metadata` 新增 `markdown_anchor` / `is_x15_truncated` 字段暴露（SQL 因 `SELECT *` 已带，无需改）
2. 新建 `backend/ingestion/api/x15.py`：`_read_raw_file` / `make_window` / `assign_group_key` / `_format_result_x15`
3. 改造 `routes_search.py`：分组 + X1.5 化 + feature flag
4. 痛点回归 1：本地手动跑 2 个 query 验证

**Phase 2 质量增强**：
5. 单元测试 4 个文件
6. 集成测试 3 个文件（含 painpoints）
7. baseline 脚本 + 跑一次得 X1.5 vs X0 数据
8. 数据校验脚本 `verify_section_grouping.py`（防分组假设静默失效）

**Phase 3 可维护性 + Codex review**：
9. INTERFACE.md 更新（`markdown_anchor` / `is_x15_truncated` 字段 + Layer 2 映射注释 + char_offset 跟随 content 的语义说明）
10. baseline 结果走 cross-review.sh，Codex 审一遍
11. 提交 commit

**单独追踪（不在 X1.5 主线交付里）**：
- `test-result-reviewer-prompt.md` 模板（H.4 用，工具类增强，不阻塞主线上线，**作为后续 superpowers 工作流改进的独立任务**记入 follow-up）

**不在本 spec 任务列表里**（跨 team rollout，由海军 team 独立排期）：
- 海军 retrieval.py 把 `metadata.markdown_anchor` 映射到 `RetrievedChunk.anchor`
- 海军 / reasoning 重新部署
- 通知海军 team 的协调动作（属沟通，不属 plan 任务）

每个任务在 plan 里展开 4 字段（目标 / 输入输出 / 验收 / 是否当前必须）。

---

## 名词解释

### reranker（精排器，业内叫 cross-encoder reranker）

1. **解决什么**：给一批召回的 chunk 重新打分排序，把跟 query 最相关的排前面
2. **没它会怎样**：vec / BM25 召回精度差，top-3 经常没答案
3. **流程哪一步**：海军 retrieval.py 拿到 ingestion 返回的 30 个 chunk 后，对每个 chunk 用 reranker 算 (query, chunk) pair 的相关性分
4. **输入输出**：输入 (query, chunk_content)，输出 0-1 分
5. **本项目非要不可吗**：是。reranker 是赛题召回质量保证。**X1.5 整个改造的核心目的就是让 reranker 看到完整 section 上下文，不被零碎单 chunk 误导**

### bge-reranker-base

reranker 模型的具体型号（`BAAI/bge-reranker-base`）。token 上限 512，约对应 1000-1500 中文字符。这是 X1.5 设 max_chars=2000 的依据 —— 让 reranker 看的内容不超出它的"视野"太多。

### bge-m3

embedding 模型，1024 维，用于把 query 和 chunk 都转成向量做余弦相似度。本 spec 不动它。

### LRU 缓存（Least Recently Used）

1. **解决什么**：避免重复读相同文件
2. **没它会怎样**：单次 query 30 个 result 来自同 1 个文件 = 30 次磁盘 IO，30-150ms 浪费
3. **流程哪一步**：`_format_result_x15` 内部调 `_read_raw_file` 时
4. **输入输出**：输入文件相对路径，输出文件全文
5. **本项目非要不可吗**：是。X1.5 每个 result 都要切片，不缓存性能崩

### env var / feature flag

1. **解决什么**：代码不变的情况下切换行为
2. **没它会怎样**：上线后发现 bug，要 git revert + 重新打包 = 10 分钟回滚；有 flag = 改一个变量重启 = 30 秒
3. **流程哪一步**：服务启动时 `os.getenv("INGESTION_X15_ENABLED", "true")` 读取
4. **输入输出**：输入字符串 "true"/"false"，输出 X1.5 / X0 行为
5. **本项目非要不可吗**：强烈推荐。POC + Codex review + 数据验证三重保险但仍可能有未知边角 case，30 秒回滚能力值这 5 行代码

### markdown anchor（赛题 citation 用的 section 标识）

1. **解决什么**：标识 markdown 文档里的某个小标题（section）
2. **没它会怎样**：赛题判分按 anchor 粒度，没这个字段答案没法 citation
3. **流程哪一步**：chunker 给每个 chunk 绑定一个 markdown_anchor（leaf section anchor，无标题时 fallback 到 `#top`）；reasoning 输出 citation 时引用这个值
4. **输入输出**：输入 markdown section 标题文本（"### API 发起驱逐"），输出 anchor 字符串（`#api-发起驱逐`）
5. **本项目非要不可吗**：是。赛题 200 题的 gold_sources 全部用 anchor 维度判分，这是赛题输出格式的强制字段

### chunk / chunk_index / title_path / char_offset

| 字段 | 含义 | 例子 |
|---|---|---|
| `chunk` | chunker 切出来的一个内容片段 | 一段 200-500 字的文本 |
| `chunk_index` | 同文件内 chunk 的顺序号 | 0, 1, 2, ... |
| `title_path` | chunk 继承的标题层级路径 | "K8s 文档 / 资源管理 / 驱逐" |
| `char_offset_start/end` | chunk 在源文件里的字符位置 | 1234 → 1567 |
| `markdown_anchor` | chunk 所属 leaf section 的 anchor | `#api-发起驱逐` |
| `anchor_id` | 内部主键 / 前端跳转 | `"file.md#1234"` |

注意 `anchor_id`（char_offset 形式）和 `markdown_anchor`（section 形式）是**不同概念**，本 spec 同时保留两者。

### baseline 召回率

1. **解决什么**：量化 X1.5 比 X0 好多少
2. **没它会怎样**：只凭"感觉"上线，不知道是真好还是巧合
3. **流程哪一步**：开发完成后跑 `eval_x15_baseline.py`，对每题分别用 X0 / X1.5 跑一遍，看 top-3 有没有命中 gold evidence
4. **输入输出**：输入测试集 200 题 + 两个 mode，输出每题命中情况 + 汇总召回率
5. **本项目非要不可吗**：是。**没数据不上线**

### cross-review（双引擎交叉验证）

1. **解决什么**：用一个独立 AI 实例审另一个 AI 写的代码 / 设计 / 测试结果，抓"看习惯了所以没发现"的盲点
2. **没它会怎样**：单引擎设计可能有自洽但实际有问题的方案
3. **流程哪一步**：spec 写完 / 测试跑完时调用 `cross-review.sh`，把内容喂给 Codex (ChatGPT)，拿独立 review 报告
4. **输入输出**：输入 spec 文档 / 测试结果 JSON，输出 Codex 的 "Approved / Issues Found" 报告
5. **本项目非要不可吗**：推荐。这是 superpowers 工作流的标准做法，关键节点用一次

### Phase 1 / 2 / 3 三阶段

1. **解决什么**：把任务按"先跑通 → 再加质量 → 再加可维护性"分层，避免一上来就追求完美卡住
2. **没它会怎样**：要么过度设计交付不了，要么早早上线但测试不全后期债重
3. **流程哪一步**：writing-plans 阶段把任务按这三阶段分组
4. **输入输出**：输入需求清单，输出三组任务列表
5. **本项目非要不可吗**：是（白话 writing-plans 的强制结构）
