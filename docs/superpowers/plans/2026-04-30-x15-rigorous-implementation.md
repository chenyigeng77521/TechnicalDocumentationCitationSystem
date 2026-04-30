# X1.5 严谨版实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让海军 reranker 看到完整 section 上下文（含标题前缀）而不是零碎单 chunk，把"API 发起驱逐工作原理" / "React 数据获取库" 这类痛点 query 救回 top-3

**Architecture:** 改造 `backend/ingestion/api/routes_search.py::_format_result` 一个函数，新增 `backend/ingestion/api/x15.py` 模块封装核心逻辑（分组 / 居中截 / LRU 缓存 / section 边界查询）。chunk_id 保持 DB 真主键不变；anchor_id / char_offset 跟随 content 走（X1.5 时是 window 范围）；env var feature flag 默认开

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / SQLite / pytest（asyncio_mode=auto）

**Spec:** [docs/superpowers/specs/2026-04-30-x15-rigorous-design.md](../specs/2026-04-30-x15-rigorous-design.md)

---

## 外行版摘要

**1. 做什么？**

改 `backend/ingestion` 检索 API 一个函数，让海军 reranker 看到的 `content` 字段从"单个零碎片段"换成"标题路径 + 整 section 文字"。POC 已实测两个长期跑不出答案的 query 救活进 top-3。

**2. 为什么需要？**

当前 reranker 看零碎单 chunk 没标题信息（步骤列表 chunk 里没"驱逐"二字），打低分，找不到答案。POC 验证：拼标题前缀 + section 全量 → reranker 分数 0.01 升到 0.99。

**3. 大致怎么做？**

- 新建 `x15.py` 模块（5 个 helper：读文件 / 查 section 边界 / 居中截 / 分组 / 主格式化）
- 改造 `routes_search.py` 入口（分组 + 调主格式化 + feature flag）
- 加单元测试 / 集成测试 / 200 题 baseline 对比脚本 / 分组假设校验脚本
- env var 默认 true，应急时 false 重启 30 秒回滚
- INTERFACE.md 同步更新字段说明

**4. 主要风险**

| 风险 | 缓解 |
|---|---|
| 长 section 截断丢答案 | 命中点居中截，3 档策略覆盖 |
| 文件读不出 / DB drift | try/except 退回 X0 + WARNING 日志 |
| (file_path, title_path) 分组假设静默失效 | verify_section_grouping.py 数据校验脚本 |
| POC 没覆盖的边角 case | env var feature flag 30 秒回滚 |
| 跨 team 上线（海军 1 行映射）| spec 声明依赖，本 plan 不实施海军侧 |

---

## Phase 1: 最小可跑（MVP）

**Phase 1 验收**：本地手动用两个痛点 query 跑 vector-search，top-3 返回结果包含答案关键词（kubelet / TanStack Query 等），跑通即结束 Phase 1，进入 Phase 2 加测试。

---

### Task 1: 给 metadata 加两个新字段
📖 业内叫：API contract extension

- **目标：** 让 ingestion API 返回的 metadata 多出两个字段：`markdown_anchor`（赛题判分用）和 `is_x15_truncated`（X1.5 截断标记）
- **输入：** DB chunks 表（`markdown_anchor` 列已存在，commit a80cb85）
- **输出：** `_row_to_metadata` 函数返回的 dict 多两个 key；vector-search / text-search / by-id 三个接口的 metadata 都自动暴露这两个字段
- **验收标准：** 启动 ingestion 服务，curl `/chunks/{chunk_id}` 返回 JSON 的 metadata 段含 `markdown_anchor` 和 `is_x15_truncated`（默认 false）
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/routes_search.py:31-47`（`_row_to_metadata` 函数）

- [ ] **Step 1: 修改 `_row_to_metadata` 加两个字段**

打开 `backend/ingestion/api/routes_search.py`，把现有 `_row_to_metadata` 函数替换为：

```python
def _row_to_metadata(row: dict) -> dict:
    # doc_indexed_at 来自 search SQL 的 JOIN documents（vector/text-search 都带）
    # by-id 没 JOIN，没这字段时 fallback null
    last_modified = row.get("doc_indexed_at")
    if last_modified is not None:
        last_modified = str(last_modified)
    return {
        "file_path": row["file_path"],
        "anchor_id": row["anchor_id"],
        "title_path": row["title_path"],
        "char_offset_start": row["char_offset_start"],
        "char_offset_end": row["char_offset_end"],
        "is_truncated": bool(row["is_truncated"]),
        "is_x15_truncated": False,  # 新增：X1.5 max_chars 截断标记，默认 False，仅 X1.5 路径会改 True
        "content_type": row["content_type"],
        "language": row["language"],
        "last_modified": last_modified,
        "markdown_anchor": row.get("markdown_anchor") or "#top",  # 新增：section 标识，赛题 citation 用
    }
```

- [ ] **Step 2: 启动 ingestion 服务验证字段暴露**

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
backend/ingestion/start.sh --bg
sleep 3
# 找一个 chunk_id 试一下
CHUNK_ID=$(sqlite3 backend/storage/index/knowledge.db "SELECT chunk_id FROM chunks LIMIT 1")
curl -s "http://localhost:3003/chunks/$CHUNK_ID" | python3 -m json.tool | grep -E "markdown_anchor|is_x15_truncated"
```

Expected：返回两行包含 `"markdown_anchor": "#xxx"` 和 `"is_x15_truncated": false`

- [ ] **Step 3: 停服务**

```bash
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add backend/ingestion/api/routes_search.py
git commit -m "feat(ingestion): metadata 加 markdown_anchor + is_x15_truncated 字段

- _row_to_metadata 默认 is_x15_truncated=False，仅 X1.5 路径会改 True
- markdown_anchor fallback #top
- 为 X1.5 改造铺路（spec §1.改造范围）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 写 raw 文件读取 + LRU 缓存
📖 业内叫：file content cache helper

- **目标：** 实现 `_read_raw_file(file_path)` 读源 markdown 文件，做 CRLF 归一化，自动缓存（避免单 query 30 个 result 来自同文件时重复 IO）
- **输入：** file_path（DB 里的相对路径，如 `kubernetes/api-eviction.md`）
- **输出：** 文件全文字符串（CRLF → LF 归一化后）
- **验收标准：** 单元测试通过：`pytest backend/ingestion/tests/unit/test_x15_raw_reader.py -v`（Phase 2 写测试，本 task 只验证函数能 import + 跑一个手工调用 OK）
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/api/x15.py`

- [ ] **Step 1: 新建 x15.py 文件，写 _read_raw_file 函数**

创建 `backend/ingestion/api/x15.py`，内容：

```python
"""X1.5 search 接口 section 全量化辅助函数。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md
"""
import functools
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RAW_DIR = Path("backend/storage/raw")
DEFAULT_MAX_CHARS = 2000


@functools.lru_cache(maxsize=200)
def _read_raw_file(file_path: str) -> str:
    """读源 markdown 文件，CRLF 归一化（跟 chunker 入口一致）。

    file_path 是 DB 里存的相对路径（不含 raw/ 前缀）。
    LRU 缓存上限 200，覆盖当前 164 文件且对未来扩到 10K+ 文件也稳定（自动淘汰冷文件）。
    测试 fixture 必须显式调 _read_raw_file.cache_clear() 防跨测污染。
    """
    abs_path = RAW_DIR / file_path
    text = abs_path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")
```

- [ ] **Step 2: 手工验证函数能跑**

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python3 -c "
from backend.ingestion.api.x15 import _read_raw_file
content = _read_raw_file('kubernetes/api-eviction.md')
print(f'文件长度: {len(content)} chars')
print(f'前 100 字符: {content[:100]!r}')
print(f'\\\\r 个数（应 0）: {content.count(chr(13))}')
"
```

Expected：打印文件长度 > 0，前 100 字符是中文标题，`\r` 个数 = 0

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/api/x15.py
git commit -m "feat(ingestion/x15): 新建 x15.py + _read_raw_file LRU 缓存

- maxsize=200 覆盖当前 164 文件，扩展到 10K+ 文件也稳定
- CRLF 归一化跟 chunker 入口一致
- spec §2.4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 写 section 真边界查询函数
📖 业内叫：section boundary lookup with cache

- **目标：** 给定 (file_path, title_path)，从 DB 查同 section **全部** chunks（含未召回的）的 char_offset union 范围。**这是 X1.5 关键算法点**：section_start/end 必须取全量 chunks 的 union，不能只看召回的命中 chunks（否则 section 内只 1 个命中时退化成单 chunk 大小）
- **输入：** conn (sqlite3.Connection)、file_path (str)、title_path (str)
- **输出：** (section_start: int, section_end: int) tuple；查不到时 raise ValueError
- **验收标准：** 手工验证：传入 `kubernetes/api-eviction.md` + `API 发起驱逐 / 工作原理`（或其它真实 title_path），返回的 (start, end) 跨度大于单个 chunk
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/x15.py`（追加函数）

- [ ] **Step 1: 在 x15.py 追加 get_section_full_range 函数 + 进程级缓存**

在 `backend/ingestion/api/x15.py` 末尾追加：

```python
# 进程级 section 边界缓存（key 不能用 conn，所以单独 dict）
# section 总数 ~1600，全装内存可忽略；测试 fixture 显式 clear
_section_range_cache: dict[tuple[str, str], tuple[int, int]] = {}


def get_section_full_range(conn, file_path: str, title_path: str) -> tuple[int, int]:
    """查同 section 全部 chunks（含未命中的）的 offset union 范围。

    关键设计点：必须查全部 chunks 的 union，不能只看召回的命中。
    否则 section 内只有 1 个 chunk 被命中时，"section 全量" 退化成单 chunk 大小。
    """
    cache_key = (file_path, title_path or "")
    if cache_key in _section_range_cache:
        return _section_range_cache[cache_key]

    row = conn.execute(
        """SELECT MIN(char_offset_start) AS s, MAX(char_offset_end) AS e
           FROM chunks
           WHERE file_path = ?
             AND COALESCE(title_path, '') = COALESCE(?, '')""",
        (file_path, title_path or ""),
    ).fetchone()
    if row is None or row["s"] is None:
        raise ValueError(f"no chunks for ({file_path}, {title_path!r})")

    result = (row["s"], row["e"])
    _section_range_cache[cache_key] = result
    return result


def clear_section_range_cache():
    """测试用，清空 section 边界缓存。"""
    _section_range_cache.clear()
```

- [ ] **Step 2: 手工验证函数能跑 + 缓存生效**

```bash
python3 -c "
from backend.ingestion.db.connection import get_connection
from backend.ingestion.api.x15 import get_section_full_range, _section_range_cache

conn = get_connection('backend/storage/index/knowledge.db')
# 找一个真实有多 chunk 的 section
row = conn.execute('''SELECT file_path, title_path FROM chunks
    WHERE title_path IS NOT NULL AND title_path != ''
    GROUP BY file_path, title_path
    HAVING COUNT(*) > 3 LIMIT 1''').fetchone()

fp, tp = row['file_path'], row['title_path']
print(f'测试 section: {fp} | {tp[:40]}')

s, e = get_section_full_range(conn, fp, tp)
print(f'第一次查: ({s}, {e}) 跨度 {e-s} chars')
print(f'缓存条数: {len(_section_range_cache)}')

# 第二次查走缓存
s2, e2 = get_section_full_range(conn, fp, tp)
print(f'第二次查同 section: 命中缓存 → 仍 ({s2}, {e2})')
conn.close()
"
```

Expected：跨度 > 500 字符，缓存条数 = 1，两次查结果一致

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/api/x15.py
git commit -m "feat(ingestion/x15): get_section_full_range 查 section 全量 offset union

- 进程级 dict 缓存（section 总数 ~1600，无内存压力）
- 关键设计：查同 (file_path, title_path) 全部 chunks 的 union，不限召回命中
- spec §2.3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 写居中截窗口算法
📖 业内叫：centered windowing

- **目标：** 实现 `make_window` 函数，给定 section 范围 + 命中 chunks，返回 [win_start, win_end] 切片范围。3 档策略：① section ≤ max_chars 不截 / ② 命中点 union 居中 / ③ 跨度过大用最高分居中。边界回弹保证总是切满 max_chars（除非 section 本身更小）
- **输入：** section_start, section_end, hits（命中 chunks 列表，每个含 char_offset_start/end + score），max_chars
- **输出：** (win_start: int, win_end: int, is_truncated: bool)
- **验收标准：** 手工跑 3 个 case 都对：短 section 不截 / 命中点居中正确 / 边界回弹正确
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/x15.py`（追加函数）

- [ ] **Step 1: 在 x15.py 追加 make_window 函数**

在 `x15.py` 末尾追加：

```python
def make_window(
    section_start: int,
    section_end: int,
    hits: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[int, int, bool]:
    """居中截窗口算法。返回 (win_start, win_end, is_truncated)。

    3 档策略：
    - Case 1: section 长度 ≤ max_chars → 整 section 全保
    - Case 2: 命中点 union 跨度 ≤ max_chars → 命中点 union 居中
    - Case 3: 命中点跨度 > max_chars → 取分最高命中点居中（罕见）

    边界回弹：window 撞 section 边界时把空间补给另一边，保证 win_end - win_start = max_chars。
    """
    section_len = section_end - section_start
    if section_len <= max_chars:
        return section_start, section_end, False  # Case 1

    hit_min = min(h["char_offset_start"] for h in hits)
    hit_max = max(h["char_offset_end"] for h in hits)

    if hit_max - hit_min <= max_chars:
        # Case 2: 命中点 union 装得下
        center = (hit_min + hit_max) // 2
    else:
        # Case 3: 跨度过大，按最高分居中
        top_hit = max(hits, key=lambda h: h.get("score", 0))
        center = (top_hit["char_offset_start"] + top_hit["char_offset_end"]) // 2

    half = max_chars // 2
    win_start = max(section_start, center - half)
    win_end = min(section_end, center + half)

    # 边界回弹：一边碰壁就把空间补给另一边
    if win_end - win_start < max_chars:
        if win_start == section_start:
            win_end = min(section_end, win_start + max_chars)
        else:
            win_start = max(section_start, win_end - max_chars)

    return win_start, win_end, True
```

- [ ] **Step 2: 手工验证 3 个 case**

```bash
python3 -c "
from backend.ingestion.api.x15 import make_window

# Case 1: 短 section（< max_chars）整段保留
s, e, t = make_window(0, 500, [{'char_offset_start': 100, 'char_offset_end': 200, 'score': 0.9}], max_chars=2000)
assert (s, e, t) == (0, 500, False), f'Case 1 失败: ({s}, {e}, {t})'
print('Case 1 OK: 短 section 不截')

# Case 2: 长 section + 命中点居中
s, e, t = make_window(0, 5000, [{'char_offset_start': 2400, 'char_offset_end': 2600, 'score': 0.9}], max_chars=2000)
# 命中中点 = 2500，window = [1500, 3500]，长度 2000，is_truncated=True
assert (s, e, t) == (1500, 3500, True), f'Case 2 失败: ({s}, {e}, {t})'
print('Case 2 OK: 命中居中')

# Case 3: 边界回弹（命中靠近 section 起点）
s, e, t = make_window(0, 5000, [{'char_offset_start': 100, 'char_offset_end': 200, 'score': 0.9}], max_chars=2000)
# 中点 = 150，本应 [-850, 1150] → 撞 0 → 回弹到 [0, 2000]
assert (s, e, t) == (0, 2000, True), f'Case 3 失败: ({s}, {e}, {t})'
print('Case 3 OK: 左边回弹')

print('全部通过')
"
```

Expected: 三个 OK 都打印，最后"全部通过"

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/api/x15.py
git commit -m "feat(ingestion/x15): make_window 居中截窗口算法

- 3 档策略：短 section 全保 / 命中 union 居中 / 跨度过大用 max-score 居中
- 边界回弹保证总长 = max_chars（除非 section 更小）
- DEFAULT_MAX_CHARS=2000，对齐 reranker 容量
- spec §2.2

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 写分组函数
📖 业内叫：grouping by section key

- **目标：** 实现 `assign_group_key` 和 `group_results` 两个函数。分组规则：title_path 非空按 (file_path, title_path) 合并；title_path 空走 SINGLE 退化路径每 chunk 自己一组
- **输入：** results 列表（vec_search/text_search 返回的原始 row dicts）
- **输出：** dict[group_key, list[chunk]]，组内按 score 降序
- **验收标准：** 手工跑：构造一组 mock chunks（混合 SINGLE 和 SECTION 路径），分组结果对
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/x15.py`（追加函数）

- [ ] **Step 1: 追加 assign_group_key + group_results 函数**

```python
GroupKey = tuple  # ('SINGLE', chunk_id) 或 ('SECTION', file_path, title_path)


def assign_group_key(chunk: dict) -> GroupKey:
    """决定 chunk 属于 SINGLE 还是 SECTION 路径。

    title_path 空 ≡ markdown_anchor=#top（数据验证 100% 对应），走 SINGLE 退化避免跨文件误并。
    """
    title_path = chunk.get("title_path") or ""
    if not title_path:
        return ("SINGLE", chunk["chunk_id"])
    return ("SECTION", chunk["file_path"], title_path)


def group_results(results: list[dict]) -> dict[GroupKey, list[dict]]:
    """把 search 返回的 rows 按 group_key 分组，组内按 score 降序排。

    输出顺序由调用方按"组内最高分"再排（这里只做分组）。
    """
    groups: dict[GroupKey, list[dict]] = defaultdict(list)
    for r in results:
        groups[assign_group_key(r)].append(r)
    for k in groups:
        groups[k].sort(key=lambda c: -c.get("score", 0))
    return groups
```

- [ ] **Step 2: 手工验证分组逻辑**

```bash
python3 -c "
from backend.ingestion.api.x15 import group_results, assign_group_key

# 构造 4 个 mock chunks：3 个属同 section，1 个 title_path 空
chunks = [
    {'chunk_id': 'c1', 'file_path': 'k.md', 'title_path': 'A/B', 'score': 0.9},
    {'chunk_id': 'c2', 'file_path': 'k.md', 'title_path': 'A/B', 'score': 0.7},
    {'chunk_id': 'c3', 'file_path': 'k.md', 'title_path': 'A/B', 'score': 0.5},
    {'chunk_id': 'c4', 'file_path': 'k.md', 'title_path': '',    'score': 0.6},  # SINGLE 退化
]
groups = group_results(chunks)
print(f'分组数: {len(groups)} (应 2)')
for key, members in groups.items():
    ids = [m['chunk_id'] for m in members]
    print(f'  {key}: {ids}')

# Section 组应只有 1 个（c1/c2/c3 合并），SINGLE 组 1 个（c4）
assert len(groups) == 2
section_key = ('SECTION', 'k.md', 'A/B')
single_key = ('SINGLE', 'c4')
assert section_key in groups
assert single_key in groups
# Section 组按 score 降序：c1, c2, c3
assert [m['chunk_id'] for m in groups[section_key]] == ['c1', 'c2', 'c3']
print('全部通过')
"
```

Expected：分组数 = 2，section 组按 c1/c2/c3 排，最后"全部通过"

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/api/x15.py
git commit -m "feat(ingestion/x15): assign_group_key + group_results 分组逻辑

- title_path 非空走 SECTION 路径 (file_path, title_path) 合并
- title_path 空走 SINGLE 退化（避免跨文件误并）
- 组内按 score 降序
- spec §2.1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 写 _format_result_x15 主函数
📖 业内叫：result formatter (X1.5 path)

- **目标：** 把分组后的 chunks 转成 1 个 result dict。SECTION 路径合并 section + 标题前缀 + 居中截 + 失败 fallback；SINGLE 路径退化返回单 chunk 原内容
- **输入：** conn, group_chunks（已按 score 降序）, title_path（'' 表示 SINGLE 路径）
- **输出：** dict（含 chunk_id / content / score / metadata）
- **验收标准：** 手工跑 3 个 case：SECTION 路径合并正常 / SINGLE 退化路径正常 / 文件不存在 fallback 退回 X0
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/x15.py`（追加 + import _row_to_metadata）

- [ ] **Step 1: 在 x15.py 顶部加 import 注释，末尾追加 _format_result_x15**

在 `x15.py` 顶部 imports 之后加注释（说明 _row_to_metadata 在 routes_search.py，避免循环 import）：

```python
# 注：_row_to_metadata 来自 backend.ingestion.api.routes_search
# 调用方负责传入 metadata（避免 x15 ↔ routes_search 循环 import）
```

末尾追加：

```python
def _format_result_x15(
    conn,
    group_chunks: list[dict],
    title_path: str,
    metadata_x0: dict,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict:
    """X1.5 化主函数。每组返回 1 个 result。

    Args:
        conn: SQLite connection（用于 get_section_full_range）
        group_chunks: 已按 score 降序的命中 chunks
        title_path: SECTION 路径的标题路径；'' 触发 SINGLE 退化
        metadata_x0: 由调用方用 _row_to_metadata(group_chunks[0]) 算好传入

    Returns:
        result dict 含 chunk_id / content / score / metadata
    """
    representative = group_chunks[0]

    if not title_path:
        # SINGLE 退化路径：原 chunk content，metadata 不变
        return {
            "chunk_id": representative["chunk_id"],
            "content": representative["content"],
            "score": representative.get("score", 0.0),
            "metadata": metadata_x0,
        }

    # SECTION 合并路径
    file_path = representative["file_path"]
    try:
        section_start, section_end = get_section_full_range(conn, file_path, title_path)
        win_start, win_end, is_truncated = make_window(
            section_start, section_end, group_chunks, max_chars=max_chars
        )
        raw_slice = _read_raw_file(file_path)[win_start:win_end]
        if not raw_slice.strip():
            raise ValueError("empty raw_slice")
        content = f"{title_path}\n\n{raw_slice}"
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as e:
        logger.warning(
            "x15 fallback for %s (title=%s): %s", file_path, title_path, e
        )
        # 退回 X0 行为：单 chunk 原 content，metadata 不变
        return {
            "chunk_id": representative["chunk_id"],
            "content": representative["content"],
            "score": representative.get("score", 0.0),
            "metadata": metadata_x0,
        }

    # X1.5 成功路径：metadata 跟着 content 走
    metadata = dict(metadata_x0)
    metadata["is_x15_truncated"] = is_truncated
    metadata["char_offset_start"] = win_start
    metadata["char_offset_end"] = win_end
    metadata["anchor_id"] = f"{file_path}#{win_start}"
    return {
        "chunk_id": representative["chunk_id"],
        "content": content,
        "score": representative.get("score", 0.0),
        "metadata": metadata,
    }
```

- [ ] **Step 2: 手工验证 3 个 case**

```bash
python3 -c "
from backend.ingestion.db.connection import get_connection
from backend.ingestion.api.routes_search import _row_to_metadata
from backend.ingestion.api.x15 import _format_result_x15, clear_section_range_cache, _read_raw_file

clear_section_range_cache()
_read_raw_file.cache_clear()
conn = get_connection('backend/storage/index/knowledge.db')

# Case A: SECTION 路径
row = conn.execute('''SELECT * FROM chunks
    WHERE title_path IS NOT NULL AND title_path != ''
    LIMIT 1''').fetchone()
chunk = dict(row)
metadata_x0 = _row_to_metadata(chunk)
result = _format_result_x15(conn, [chunk], chunk['title_path'], metadata_x0)
print(f'Case A SECTION:')
print(f'  content 含 title_path? {chunk[\"title_path\"] in result[\"content\"]}')
print(f'  content 长度: {len(result[\"content\"])}')
print(f'  metadata.is_x15_truncated: {result[\"metadata\"][\"is_x15_truncated\"]}')
assert chunk['title_path'] in result['content'], 'content 应含 title_path'

# Case B: SINGLE 退化
row = conn.execute('''SELECT * FROM chunks
    WHERE title_path IS NULL OR title_path = ''
    LIMIT 1''').fetchone()
if row:
    chunk = dict(row)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], '', metadata_x0)
    print(f'Case B SINGLE:')
    print(f'  content == 原 chunk content? {result[\"content\"] == chunk[\"content\"]}')
    assert result['content'] == chunk['content']

# Case C: fallback (file 不存在)
fake_chunk = {
    'chunk_id': 'fake', 'file_path': 'NOT_EXIST.md', 'title_path': 'A/B',
    'char_offset_start': 0, 'char_offset_end': 100, 'score': 0.5,
    'content': 'fake content',
}
metadata_fake = {'file_path': 'NOT_EXIST.md', 'is_x15_truncated': False}
result = _format_result_x15(conn, [fake_chunk], 'A/B', metadata_fake)
print(f'Case C fallback:')
print(f'  content == 原 fake content? {result[\"content\"] == \"fake content\"}')
assert result['content'] == 'fake content', 'fallback 应退原 content'

conn.close()
print('全部通过')
"
```

Expected：3 个 case 都通过，最后"全部通过"

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/api/x15.py
git commit -m "feat(ingestion/x15): _format_result_x15 主函数 + 失败 fallback

- SECTION 路径：title_path + 居中截 raw_slice + metadata.char_offset 跟随 window
- SINGLE 退化：原 chunk content 不变
- 失败 fallback：try/except 退回 X0 + WARNING 日志
- spec §2.5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 改造 routes_search.py 入口（分组 + flag + 调用）
📖 业内叫：API entrypoint refactor

- **目标：** 把 vector-search / text-search 入口改成 X1.5 流程：env var flag 判断 → 分组 → 排序 → _format_result_x15。`/chunks/{chunk_id}` by-id 接口保持原样不动
- **输入：** Task 1-6 的 _row_to_metadata、x15.py 模块
- **输出：** 改造后的 routes_search.py，env var INGESTION_X15_ENABLED=true 时走 X1.5；=false 退回 X0 行为
- **验收标准：** 启动服务，curl `/chunks/vector-search` 返回的 result 数量 ≤ 30，content 含 title_path 前缀（针对有 title 的命中）；env var 设 false 重启，return 原行为
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/api/routes_search.py`（_format_result + post_vector_search + post_text_search 三段）

- [ ] **Step 1: 改造 routes_search.py，加 import + flag + 重写入口**

打开 `backend/ingestion/api/routes_search.py`，在 imports 区域追加：

```python
import os
from collections import defaultdict
from backend.ingestion.api.x15 import (
    group_results,
    _format_result_x15,
)

X15_ENABLED = os.getenv("INGESTION_X15_ENABLED", "true").lower() == "true"
```

把现有的 `_format_result` 函数**改名**为 `_format_result_legacy`（X0 路径，保留作 fallback / flag off 时的备用），不改函数体。

把 `post_vector_search` 替换为：

```python
@router.post("/chunks/vector-search")
async def post_vector_search(req: VectorSearchRequest):
    if len(req.embedding) != 1024:
        raise HTTPException(400, "embedding must be 1024-dim")
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        rows = vector_search(conn, req.embedding, top_k=req.top_k)

        if not X15_ENABLED:
            return {
                "results": [_format_result_legacy(r) for r in rows],
                "total": len(rows),
            }

        # X1.5 路径：分组 → 排序 → 格式化
        groups = group_results(rows)
        # 输出顺序：按"组内最高分"降序
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: -kv[1][0].get("score", 0),
        )

        results = []
        for key, members in sorted_groups:
            title_path = members[0].get("title_path") if key[0] == "SECTION" else ""
            metadata_x0 = _row_to_metadata(members[0])
            results.append(
                _format_result_x15(conn, members, title_path or "", metadata_x0)
            )

        return {"results": results, "total": len(results)}
    finally:
        conn.close()
```

把 `post_text_search` 同样替换（结构一致，只是 SQL 来源不同）：

```python
@router.post("/chunks/text-search")
async def post_text_search(req: TextSearchRequest):
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        rows = text_search(conn, req.query, top_k=req.top_k)

        if not X15_ENABLED:
            return {
                "results": [_format_result_legacy(r, include_bm25=True) for r in rows],
                "total": len(rows),
            }

        groups = group_results(rows)
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: -kv[1][0].get("score", 0),
        )

        results = []
        for key, members in sorted_groups:
            title_path = members[0].get("title_path") if key[0] == "SECTION" else ""
            metadata_x0 = _row_to_metadata(members[0])
            results.append(
                _format_result_x15(conn, members, title_path or "", metadata_x0)
            )

        return {"results": results, "total": len(results)}
    finally:
        conn.close()
```

`/chunks/{chunk_id}` by-id 接口（`get_chunk_by_id` 函数）**完全不动**。

- [ ] **Step 2: 启动服务，curl 验证 X1.5 路径生效**

```bash
backend/ingestion/start.sh --bg
sleep 3

# 用一个真实 query 调 vector-search
EMBEDDING=$(python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-m3')
import json
print(json.dumps(m.encode('API 发起驱逐的工作原理是什么', normalize_embeddings=True).tolist()))
")

RESULT=$(curl -s -X POST "http://localhost:3003/chunks/vector-search" \
    -H "Content-Type: application/json" \
    -d "{\"embedding\": $EMBEDDING, \"top_k\": 30}")

echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'result 数量: {data[\"total\"]} (应 ≤ 30，X1.5 收缩后)')
print(f'前 3 个 result 的 content 头部:')
for i, r in enumerate(data['results'][:3]):
    print(f'  [{i}] chunk_id={r[\"chunk_id\"][:16]}... markdown_anchor={r[\"metadata\"][\"markdown_anchor\"]}')
    print(f'      content[:80]: {r[\"content\"][:80]!r}')
    print(f'      is_x15_truncated: {r[\"metadata\"][\"is_x15_truncated\"]}')
"
```

Expected：`total ≤ 30`；前 3 个 result 的 content 头部含 title_path 前缀（除非 title_path 空走 SINGLE）；`markdown_anchor` 字段存在

- [ ] **Step 3: 验证 X0 fallback（feature flag = false）**

```bash
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null
INGESTION_X15_ENABLED=false backend/ingestion/start.sh --bg
sleep 3

RESULT=$(curl -s -X POST "http://localhost:3003/chunks/vector-search" \
    -H "Content-Type: application/json" \
    -d "{\"embedding\": $EMBEDDING, \"top_k\": 30}")

echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'X0 路径 result 数量: {data[\"total\"]} (应 = 30，未收缩)')
# X0 不会有 title_path 前缀
print(f'前 1 个 result content[:80]: {data[\"results\"][0][\"content\"][:80]!r}')
"

kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null
```

Expected：X0 路径 total = 30（未收缩）

- [ ] **Step 4: 启回 X1.5 默认状态 + Commit**

```bash
backend/ingestion/start.sh --bg  # 不带 env var = 默认 true
sleep 2
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null

git add backend/ingestion/api/routes_search.py
git commit -m "feat(ingestion/routes_search): X1.5 入口改造 + env var feature flag

- INGESTION_X15_ENABLED 默认 true，应急 false 重启 30 秒回滚
- X1.5 路径：分组 + 按组内最高分排 + _format_result_x15
- X0 路径：保留 _format_result_legacy 不变
- by-id 接口完全不改
- spec §2.6 + §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 痛点 query 手动验证（Phase 1 验收门槛）
📖 业内叫：smoke test for painpoints

- **目标：** 用 spec 提到的 2 个痛点 query 手动跑端到端，确认 top-3 含答案关键词
- **输入：** ingestion 服务运行中（X1.5 默认开）
- **输出：** 屏幕打印两个 query 的 top-3 result 摘要 + 是否含关键词
- **验收标准：** **两个 query 的 top-3 都至少有 1 个 result content 含答案关键词**（kubelet/宽限期/EndpointSlice 任一 / TanStack Query/SWR/RTK Query 任一）
- **是否当前必须：** 是
- **关键节点：** 是（Phase 1 验收门槛，未通过不进 Phase 2）

**Files:**
- 无新文件，纯手动验证

- [ ] **Step 1: 写一次性验证脚本（不入库，仅本地跑）**

把下面脚本存到 `/tmp/x15_smoke_test.py`：

```python
"""X1.5 Phase 1 痛点 query 烟雾测试。本地一次性跑，不入库。"""
import json
import requests
from sentence_transformers import SentenceTransformer

QUERIES = [
    {
        "name": "K8s API 发起驱逐",
        "q": "API 发起驱逐的工作原理是什么",
        "answer_kw": ["kubelet", "宽限期", "EndpointSlice"],
    },
    {
        "name": "React 数据获取库",
        "q": "从大多数后端或 REST 风格 API 获取数据时，React 建议使用哪些库？",
        "answer_kw": ["TanStack Query", "SWR", "RTK Query"],
    },
]

print("Loading bge-m3...")
m = SentenceTransformer("BAAI/bge-m3")
print("loaded\n")

all_pass = True
for q_info in QUERIES:
    print(f"=== {q_info['name']} ===")
    print(f"  Q: {q_info['q']}")
    emb = m.encode(q_info["q"], normalize_embeddings=True).tolist()
    resp = requests.post(
        "http://localhost:3003/chunks/vector-search",
        json={"embedding": emb, "top_k": 30},
        timeout=30,
    ).json()

    top3 = resp["results"][:3]
    print(f"  total={resp['total']}, top-3 摘要:")
    hit_in_top3 = False
    for i, r in enumerate(top3):
        anchor = r["metadata"]["markdown_anchor"]
        fp = r["metadata"]["file_path"]
        kws_hit = [kw for kw in q_info["answer_kw"] if kw in r["content"]]
        mark = " ★含关键词:" + ",".join(kws_hit) if kws_hit else ""
        print(f"    [{i}] {fp}#{anchor[:30]}{mark}")
        if kws_hit:
            hit_in_top3 = True

    if hit_in_top3:
        print(f"  ✅ {q_info['name']}: top-3 含答案关键词\n")
    else:
        print(f"  ❌ {q_info['name']}: top-3 不含答案关键词，Phase 1 验收失败！\n")
        all_pass = False

print("===" * 20)
if all_pass:
    print("🎉 全部通过 Phase 1 验收，可进 Phase 2")
else:
    print("⚠️ 验收未通过，需排查 X1.5 实现是否符合 spec")
```

- [ ] **Step 2: 启动 ingestion 服务**

```bash
conda activate sqllineage
backend/ingestion/start.sh --bg
sleep 5  # 等 bge-m3 load 完
curl -s http://localhost:3003/health | python3 -m json.tool | grep embedding_model_loaded
# 应输出 "embedding_model_loaded": true
```

- [ ] **Step 3: 跑烟雾测试，**人工**判断验收通过**

```bash
python3 /tmp/x15_smoke_test.py
```

Expected：
- 两个 query 的 top-3 都打印 "★含关键词:..."
- 最后 "🎉 全部通过 Phase 1 验收，可进 Phase 2"

**如果验收失败**：停下来排查（可能是 spec 的边角 case 没覆盖到，或 X1.5 实现走了错路）。**不强行推进 Phase 2**。

- [ ] **Step 4: 关服务**

```bash
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null
```

- [ ] **Step 5: 在 progress 文件记一笔（不 commit 代码，只记验收结果）**

把 smoke test 输出贴到 `docs/superpowers/progress/2026-04-30-x15-phase1-smoke.md`：

```bash
mkdir -p docs/superpowers/progress
cat > docs/superpowers/progress/2026-04-30-x15-phase1-smoke.md <<'EOF'
# X1.5 Phase 1 烟雾测试

**时间**: 2026-04-30
**操作者**: 人工跑 /tmp/x15_smoke_test.py

## 测试结果

[把上面脚本的完整输出贴这里]

## 验收结论

- [x] K8s API 发起驱逐: top-3 含 kubelet
- [x] React 数据获取库: top-3 含 TanStack Query

✅ Phase 1 验收通过，进入 Phase 2 加测试和 baseline。
EOF

git add docs/superpowers/progress/2026-04-30-x15-phase1-smoke.md
git commit -m "docs(progress): X1.5 Phase 1 烟雾测试通过

两个痛点 query top-3 都含答案关键词，可进 Phase 2。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: 质量增强

**Phase 2 验收**：单元 + 集成测试全绿；baseline 200 题 X1.5 召回率 ≥ X0（硬性门槛）；分组假设校验脚本能跑且当前数据无违规。

---

### Task 9: 单元测试 - make_window 居中截算法
📖 业内叫：unit test for windowing

- **目标：** 验证 make_window 3 档策略 + 边界回弹的所有行为
- **输入：** Task 4 的 make_window 函数
- **输出：** `backend/ingestion/tests/unit/test_x15_window.py`，pytest 跑全绿
- **验收标准：** `pytest backend/ingestion/tests/unit/test_x15_window.py -v` 全绿，至少 8 个测试用例
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/unit/test_x15_window.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | 长 section + 单点命中居中 | ✅ | test_long_section_single_hit_center |
| 边界值 | section 长度 == max_chars | ✅ | test_section_equal_max_chars |
| 边界值 | section 长度 < max_chars 不截 | ✅ | test_short_section_no_truncate |
| 异常输入 | hits 为空 | ❌ | 调用层保证 hits 非空（group_results 输出至少 1 个） |
| 状态相关 | 多次调用同参数 | ❌ | 函数无状态 |
| 业务规则 | Case 2 命中 union 居中 | ✅ | test_case2_hit_union_center |
| 业务规则 | Case 3 跨度过大用 max-score | ✅ | test_case3_max_score_center |
| 业务规则 | 边界回弹（左碰壁）| ✅ | test_boundary_rebound_left |
| 业务规则 | 边界回弹（右碰壁）| ✅ | test_boundary_rebound_right |
| 业务规则 | is_truncated 标记正确 | ✅ | test_is_truncated_flag |

- [ ] **Step 1: 写失败测试**

创建 `backend/ingestion/tests/unit/test_x15_window.py`：

```python
"""make_window 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.2
"""
import pytest
from backend.ingestion.api.x15 import make_window


def _hit(start, end, score=0.5):
    return {"char_offset_start": start, "char_offset_end": end, "score": score}


# 测什么行为：section 长度 < max_chars 时整 section 全保，不截
# 输入：section [0, 500]，命中 chunk [100, 200]，max_chars=2000
# 期望：返回 (0, 500, False)，is_truncated 为 False
# 为什么必须测：这是 Case 1 主路径，70% 真实 section 走这条路（数据：1598 sections P50=1278 < 2000）
def test_short_section_no_truncate():
    s, e, t = make_window(0, 500, [_hit(100, 200)], max_chars=2000)
    assert (s, e, t) == (0, 500, False)


# 测什么行为：section 长度恰好等于 max_chars 时也走 Case 1（不截）
# 输入：section [0, 2000]，max_chars=2000
# 期望：(0, 2000, False)
# 为什么必须测：边界值 == 容易写成 < 漏掉等号
def test_section_equal_max_chars():
    s, e, t = make_window(0, 2000, [_hit(500, 600)], max_chars=2000)
    assert (s, e, t) == (0, 2000, False)


# 测什么行为：长 section + 单点命中，命中点居中切 max_chars 窗口
# 输入：section [0, 5000]，命中 [2400, 2600] (中点 2500)，max_chars=2000
# 期望：window [1500, 3500]，is_truncated=True
# 为什么必须测：Case 2 主路径，覆盖大部分需要截断的 section
def test_long_section_single_hit_center():
    s, e, t = make_window(0, 5000, [_hit(2400, 2600)], max_chars=2000)
    assert (s, e, t) == (1500, 3500, True)


# 测什么行为：多个命中点 union 装得下 max_chars 时按 union 居中
# 输入：section [0, 5000]，命中 [1000, 1100] 和 [3000, 3100] (union [1000, 3100], 跨度 2100 > 2000?)
# 等等，2100 > 2000，触发 Case 3。改成两点更近：[1500, 1600] 和 [2400, 2500]，union [1500, 2500]，跨度 1000 ≤ 2000
# 期望：union 中点 = 2000，window [1000, 3000]，is_truncated=True
# 为什么必须测：Case 2 多命中场景
def test_case2_hit_union_center():
    s, e, t = make_window(
        0, 5000,
        [_hit(1500, 1600, 0.9), _hit(2400, 2500, 0.7)],
        max_chars=2000,
    )
    assert (s, e, t) == (1000, 3000, True)


# 测什么行为：命中点跨度 > max_chars 时退回 Case 3 用最高分居中
# 输入：section [0, 10000]，命中 [500, 600] (score 0.9) 和 [8000, 8100] (score 0.7)，跨度 7600 > 2000
# 期望：以 max_score 命中点 [500, 600] 中点 550 居中 → window [-450, 1550] → 左回弹到 [0, 2000]
# 为什么必须测：Case 3 罕见但必须正确（spec §2.2 数据预测 < 1%，仍要保证不崩）
def test_case3_max_score_center():
    s, e, t = make_window(
        0, 10000,
        [_hit(500, 600, 0.9), _hit(8000, 8100, 0.7)],
        max_chars=2000,
    )
    # 最高分中点 550, half=1000，本应 [-450, 1550]，左碰壁回弹到 [0, 2000]
    assert (s, e, t) == (0, 2000, True)


# 测什么行为：命中点靠近 section 起点时左边回弹
# 输入：section [0, 5000]，命中 [100, 200]（中点 150），max_chars=2000
# 期望：本应 [-850, 1150]，左碰 0 → 回弹 [0, 2000]
# 为什么必须测：边界 case 容易漏，spec §2.2 算法显式处理
def test_boundary_rebound_left():
    s, e, t = make_window(0, 5000, [_hit(100, 200)], max_chars=2000)
    assert (s, e, t) == (0, 2000, True)


# 测什么行为：命中点靠近 section 末尾时右边回弹
# 输入：section [0, 5000]，命中 [4800, 4900] (中点 4850)，max_chars=2000
# 期望：本应 [3850, 5850]，右碰 5000 → 回弹 [3000, 5000]
# 为什么必须测：边界 case 对称
def test_boundary_rebound_right():
    s, e, t = make_window(0, 5000, [_hit(4800, 4900)], max_chars=2000)
    assert (s, e, t) == (3000, 5000, True)


# 测什么行为：is_truncated 标记跟实际是否截断一致
# 输入：两个 case，一截一不截
# 期望：短 section is_truncated=False，长 section True
# 为什么必须测：metadata.is_x15_truncated 字段值依赖这个 flag
def test_is_truncated_flag():
    _, _, t1 = make_window(0, 500, [_hit(100, 200)], max_chars=2000)
    _, _, t2 = make_window(0, 5000, [_hit(2400, 2600)], max_chars=2000)
    assert t1 is False
    assert t2 is True
```

- [ ] **Step 2: 跑测试 verify 它们 fail（如果是新写的应该全绿，因为 make_window 已实现）**

```bash
cd backend/ingestion
pytest tests/unit/test_x15_window.py -v
```

Expected：8 个测试全绿（make_window 在 Task 4 已实现）

- [ ] **Step 3: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/ingestion/tests/unit/test_x15_window.py
git commit -m "test(ingestion/x15): 单元测试 make_window 居中截算法

8 个测试覆盖 3 档策略 + 边界回弹 + is_truncated flag。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: 单元测试 - 分组逻辑
📖 业内叫：unit test for grouping

- **目标：** 验证 assign_group_key + group_results 的分组行为
- **输入：** Task 5 的两个函数
- **输出：** `backend/ingestion/tests/unit/test_x15_grouping.py`
- **验收标准：** `pytest tests/unit/test_x15_grouping.py -v` 全绿
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/unit/test_x15_grouping.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | 同 (file_path, title_path) 多 chunks 合并到 1 组 | ✅ | test_section_path_merge |
| 边界值 | title_path 空字符串走 SINGLE | ✅ | test_empty_title_to_single |
| 边界值 | title_path None 走 SINGLE | ✅ | test_none_title_to_single |
| 异常输入 | results 为空 | ✅ | test_empty_results |
| 状态相关 | 多次调用 | ❌ | 函数无状态 |
| 业务规则 | 不同 file_path 不合并 | ✅ | test_different_files_not_merged |
| 业务规则 | 同 file 不同 title 不合并 | ✅ | test_same_file_diff_title_not_merged |
| 业务规则 | 组内按 score 降序 | ✅ | test_group_sorted_by_score_desc |

- [ ] **Step 1: 写失败测试**

创建 `backend/ingestion/tests/unit/test_x15_grouping.py`：

```python
"""分组逻辑单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.1
"""
from backend.ingestion.api.x15 import assign_group_key, group_results


def _chunk(chunk_id, file_path, title_path, score):
    return {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "title_path": title_path,
        "score": score,
    }


# 测什么行为：同 (file_path, title_path) 的 chunks 合并到 1 组
# 输入：3 个 chunks 同 file 同 title
# 期望：groups 长度 = 1，组内 3 个 chunks
# 为什么必须测：核心合并行为，spec §2.1 主路径
def test_section_path_merge():
    chunks = [
        _chunk("a", "k.md", "X/Y", 0.9),
        _chunk("b", "k.md", "X/Y", 0.7),
        _chunk("c", "k.md", "X/Y", 0.5),
    ]
    g = group_results(chunks)
    assert len(g) == 1
    key = ("SECTION", "k.md", "X/Y")
    assert key in g
    assert len(g[key]) == 3


# 测什么行为：title_path 为空字符串时走 SINGLE 退化路径
# 输入：title_path=""
# 期望：group_key 是 ('SINGLE', chunk_id)
# 为什么必须测：避免跨文件误并（4% chunks 走这路径）
def test_empty_title_to_single():
    chunk = _chunk("c1", "k.md", "", 0.5)
    assert assign_group_key(chunk) == ("SINGLE", "c1")


# 测什么行为：title_path 为 None 时走 SINGLE
# 输入：title_path=None
# 期望：('SINGLE', chunk_id)
# 为什么必须测：DB 字段可能 NULL，None 跟空字符串语义等价
def test_none_title_to_single():
    chunk = _chunk("c2", "k.md", None, 0.5)
    assert assign_group_key(chunk) == ("SINGLE", "c2")


# 测什么行为：results 为空时返回空 dict
# 输入：[]
# 期望：{}
# 为什么必须测：避免函数 crash 在边界值（实际 vec_search 可能返回 0 results）
def test_empty_results():
    assert group_results([]) == {}


# 测什么行为：不同 file_path 的同 title_path chunks 不合并
# 输入：file=a.md/b.md，title 都是 "X"
# 期望：2 个组
# 为什么必须测：避免跨文件误并
def test_different_files_not_merged():
    chunks = [
        _chunk("a", "a.md", "X", 0.9),
        _chunk("b", "b.md", "X", 0.7),
    ]
    g = group_results(chunks)
    assert len(g) == 2


# 测什么行为：同 file 不同 title 不合并
# 输入：同 file，title=X 和 Y
# 期望：2 个组
# 为什么必须测：title_path 是分组关键 key
def test_same_file_diff_title_not_merged():
    chunks = [
        _chunk("a", "k.md", "X", 0.9),
        _chunk("b", "k.md", "Y", 0.7),
    ]
    g = group_results(chunks)
    assert len(g) == 2


# 测什么行为：组内 chunks 按 score 降序排
# 输入：score=[0.3, 0.9, 0.5] 同 group
# 期望：组内顺序 [0.9, 0.5, 0.3]
# 为什么必须测：spec §2.5 _format_result_x15 取 group_chunks[0] 作为 representative，必须是分最高的
def test_group_sorted_by_score_desc():
    chunks = [
        _chunk("a", "k.md", "X", 0.3),
        _chunk("b", "k.md", "X", 0.9),
        _chunk("c", "k.md", "X", 0.5),
    ]
    g = group_results(chunks)
    members = g[("SECTION", "k.md", "X")]
    assert [m["score"] for m in members] == [0.9, 0.5, 0.3]
```

- [ ] **Step 2: 跑测试**

```bash
cd backend/ingestion
pytest tests/unit/test_x15_grouping.py -v
```

Expected：7 个测试全绿

- [ ] **Step 3: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/ingestion/tests/unit/test_x15_grouping.py
git commit -m "test(ingestion/x15): 单元测试分组逻辑

7 个测试覆盖 SECTION/SINGLE 路径 + 跨文件/标题边界 + score 降序。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: 单元测试 - raw 文件读取 + LRU
📖 业内叫：unit test for file cache

- **目标：** 验证 _read_raw_file 缓存命中、CRLF 归一化、文件不存在时抛 FileNotFoundError
- **输入：** Task 2 的 _read_raw_file
- **输出：** `backend/ingestion/tests/unit/test_x15_raw_reader.py`
- **验收标准：** pytest 全绿
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/unit/test_x15_raw_reader.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | 真文件能读出来 | ✅ | test_read_real_file |
| 边界值 | LRU maxsize 上限 | ❌ | maxsize=200，测起来需要 mock 文件系统，工程性价比低 |
| 异常输入 | 文件不存在抛 FileNotFoundError | ✅ | test_missing_file_raises |
| 错误处理 | 编码错误（非 utf-8）| ❌ | 当前语料全 utf-8，加测要 mock 文件，留 fallback 在 _format_result_x15 兜底 |
| 状态相关 | 缓存跨调用复用 | ✅ | test_cache_hit |
| 状态相关 | cache_clear 后重新读 | ✅ | test_cache_clear |
| 业务规则 | CRLF → LF 归一化 | ✅ | test_crlf_normalized（用 tmp_path 写测试文件） |

- [ ] **Step 1: 写失败测试**

创建 `backend/ingestion/tests/unit/test_x15_raw_reader.py`：

```python
"""_read_raw_file 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.4
"""
import pytest
from pathlib import Path
from unittest.mock import patch
from backend.ingestion.api.x15 import _read_raw_file
from backend.ingestion.api import x15


@pytest.fixture(autouse=True)
def clear_cache():
    """每个测试前后清缓存，防跨测污染。"""
    _read_raw_file.cache_clear()
    yield
    _read_raw_file.cache_clear()


# 测什么行为：能读真实存在的 markdown 文件
# 输入：当前语料里任一文件
# 期望：返回非空字符串
# 为什么必须测：核心读文件能力
def test_read_real_file():
    # 用一个实际存在的小文件
    text = _read_raw_file("kubernetes/api-eviction.md")
    assert isinstance(text, str)
    assert len(text) > 0


# 测什么行为：文件不存在时抛 FileNotFoundError（让 _format_result_x15 catch 走 fallback）
# 输入：不存在的 file_path
# 期望：raise FileNotFoundError
# 为什么必须测：fallback 路径依赖这个异常
def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        _read_raw_file("DOES_NOT_EXIST.md")


# 测什么行为：第二次读同文件命中缓存（不再调 read_text）
# 输入：连续两次读
# 期望：cache_info hits 增加
# 为什么必须测：避免性能回归（缓存失效会让单 query 30 次重复 IO）
def test_cache_hit():
    _read_raw_file("kubernetes/api-eviction.md")
    info1 = _read_raw_file.cache_info()
    _read_raw_file("kubernetes/api-eviction.md")
    info2 = _read_raw_file.cache_info()
    assert info2.hits == info1.hits + 1


# 测什么行为：cache_clear 后重新读
# 输入：read → clear → read
# 期望：第二次 misses 增加
# 为什么必须测：测试 fixture 用 cache_clear 隔离测试，必须可靠
def test_cache_clear():
    _read_raw_file("kubernetes/api-eviction.md")
    _read_raw_file.cache_clear()
    info_before = _read_raw_file.cache_info()
    _read_raw_file("kubernetes/api-eviction.md")
    info_after = _read_raw_file.cache_info()
    assert info_after.misses == info_before.misses + 1


# 测什么行为：CRLF (\r\n) 和单独 \r 都被归一化成 \n
# 输入：tmp_path 下放一个含 \r\n 的文件，patch RAW_DIR 指向 tmp_path
# 期望：返回的字符串里没有 \r
# 为什么必须测：跟 chunker 入口一致是必要前提，否则 char_offset 算错位置
def test_crlf_normalized(tmp_path, monkeypatch):
    # 准备一个含 CRLF 的测试文件
    test_file = tmp_path / "test.md"
    test_file.write_bytes(b"line1\r\nline2\rline3\nline4")

    # patch RAW_DIR
    monkeypatch.setattr(x15, "RAW_DIR", tmp_path)
    _read_raw_file.cache_clear()

    text = _read_raw_file("test.md")
    assert "\r" not in text
    assert text == "line1\nline2\nline3\nline4"
```

- [ ] **Step 2: 跑测试**

```bash
cd backend/ingestion
pytest tests/unit/test_x15_raw_reader.py -v
```

Expected：5 个测试全绿

- [ ] **Step 3: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/ingestion/tests/unit/test_x15_raw_reader.py
git commit -m "test(ingestion/x15): 单元测试 _read_raw_file LRU 缓存

5 个测试覆盖正常读、不存在抛错、缓存命中、cache_clear、CRLF 归一化。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: 单元测试 - _format_result_x15 主函数
📖 业内叫：unit test for X1.5 formatter

- **目标：** 验证 SECTION 路径合并 / SINGLE 退化 / fallback 三条主路径
- **输入：** Task 6 的 _format_result_x15
- **输出：** `backend/ingestion/tests/unit/test_x15_format_result.py`
- **验收标准：** pytest 全绿
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/unit/test_x15_format_result.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | SECTION 路径合并 + title prefix + window | ✅ | test_section_path_with_title_and_window |
| 边界值 | title_path 空走 SINGLE 退化 | ✅ | test_single_path_returns_chunk_content |
| 异常输入 | 文件不存在 fallback | ✅ | test_fallback_on_missing_file |
| 异常输入 | section 查不到（DB drift）| ✅ | test_fallback_on_no_section |
| 错误处理 | empty raw_slice fallback | ✅ | test_fallback_on_empty_slice |
| 状态相关 | 多次调用 | ❌ | 函数本身无状态（缓存独立测） |
| 业务规则 | metadata.is_x15_truncated 标记 | ✅ | test_metadata_is_x15_truncated_set |
| 业务规则 | metadata.char_offset/anchor_id 跟 window 走 | ✅ | test_metadata_offset_follows_window |
| 业务规则 | chunk_id 是组内分最高 chunk 真主键 | ✅ | test_chunk_id_is_max_score_representative |

- [ ] **Step 1: 写失败测试**

创建 `backend/ingestion/tests/unit/test_x15_format_result.py`：

```python
"""_format_result_x15 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.5
"""
import pytest
from pathlib import Path
from backend.ingestion.api.x15 import (
    _format_result_x15,
    _read_raw_file,
    clear_section_range_cache,
)
from backend.ingestion.api import x15
from backend.ingestion.db.connection import get_connection
from backend.ingestion.api.routes_search import _row_to_metadata


@pytest.fixture(autouse=True)
def reset_caches():
    _read_raw_file.cache_clear()
    clear_section_range_cache()
    yield
    _read_raw_file.cache_clear()
    clear_section_range_cache()


@pytest.fixture
def conn():
    c = get_connection(Path("backend/storage/index/knowledge.db"))
    yield c
    c.close()


def _real_section_chunk(conn):
    """从 DB 拿一个真实有 title_path 的 chunk。"""
    return dict(conn.execute(
        """SELECT * FROM chunks
        WHERE title_path IS NOT NULL AND title_path != ''
        LIMIT 1"""
    ).fetchone())


# 测什么行为：SECTION 路径返回 content = title_path + raw_slice
# 输入：真实 chunk + 它的 title_path
# 期望：content 含 title_path 字符串，长度 > 单 chunk 长度（因为是整 section 切片）
# 为什么必须测：核心 X1.5 行为，赛题判分等价
def test_section_path_with_title_and_window(conn):
    chunk = _real_section_chunk(conn)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], chunk["title_path"], metadata_x0)
    assert chunk["title_path"] in result["content"]
    # X1.5 内容应至少跟单 chunk content 一样长（往往更长，因为整 section）
    assert len(result["content"]) >= len(chunk["content"])


# 测什么行为：title_path 为空走 SINGLE 退化，content == 原 chunk content
# 输入：chunk + title_path=""
# 期望：result["content"] 等于 chunk["content"]，metadata 不变
# 为什么必须测：4% chunks 走这路径，不能动它
def test_single_path_returns_chunk_content(conn):
    chunk = dict(conn.execute("""SELECT * FROM chunks
        WHERE title_path IS NULL OR title_path = '' LIMIT 1""").fetchone())
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], "", metadata_x0)
    assert result["content"] == chunk["content"]


# 测什么行为：源文件不存在时 fallback 退回单 chunk content
# 输入：fake chunk file_path 不存在
# 期望：result content == chunk content（X0 行为）
# 为什么必须测：保 API 永不挂的核心契约
def test_fallback_on_missing_file(conn):
    fake_chunk = {
        "chunk_id": "fake_chunk_id",
        "file_path": "DOES_NOT_EXIST.md",
        "title_path": "Some/Title",
        "char_offset_start": 0,
        "char_offset_end": 100,
        "score": 0.5,
        "content": "fake original content",
    }
    metadata_fake = {"file_path": "DOES_NOT_EXIST.md", "is_x15_truncated": False}
    result = _format_result_x15(conn, [fake_chunk], "Some/Title", metadata_fake)
    assert result["content"] == "fake original content"


# 测什么行为：section 边界查不到时 fallback
# 输入：title_path 不存在于 DB
# 期望：fallback 退回单 chunk content
# 为什么必须测：DB drift 防御
def test_fallback_on_no_section(conn):
    chunk = {
        "chunk_id": "x", "file_path": "kubernetes/api-eviction.md",
        "title_path": "NOT_EXIST_TITLE_xyz",
        "char_offset_start": 0, "char_offset_end": 100, "score": 0.5,
        "content": "original",
    }
    metadata_x0 = {"file_path": "kubernetes/api-eviction.md", "is_x15_truncated": False}
    result = _format_result_x15(conn, [chunk], "NOT_EXIST_TITLE_xyz", metadata_x0)
    assert result["content"] == "original"


# 测什么行为：raw_slice 空白时 fallback（offset 越界 → 切片为空）
# 输入：title_path 真实但 chunk char_offset 越界（虚构）
# 期望：fallback
# 为什么必须测：offset 防御
def test_fallback_on_empty_slice(conn, monkeypatch):
    # 直接 mock get_section_full_range 返回越界 offset
    def fake_range(conn, fp, tp):
        return (99999999, 100000000)  # 文件根本没这么长
    monkeypatch.setattr(x15, "get_section_full_range", fake_range)
    chunk = {
        "chunk_id": "x", "file_path": "kubernetes/api-eviction.md",
        "title_path": "XX", "char_offset_start": 99999999, "char_offset_end": 100000000,
        "score": 0.5, "content": "original",
    }
    result = _format_result_x15(conn, [chunk], "XX", {"is_x15_truncated": False})
    assert result["content"] == "original"


# 测什么行为：X1.5 路径下 metadata.is_x15_truncated 反映实际是否截断
# 输入：长 section（已知 > 2000 字符）
# 期望：is_x15_truncated=True；短 section 时 False
# 为什么必须测：metadata 字段语义对外 contract
def test_metadata_is_x15_truncated_set(conn):
    # 找一个 section 长度 > 2000 字符的
    row = conn.execute("""
        SELECT file_path, title_path, MAX(char_offset_end)-MIN(char_offset_start) AS span
        FROM chunks
        WHERE title_path IS NOT NULL AND title_path != ''
        GROUP BY file_path, title_path
        HAVING span > 2500
        LIMIT 1
    """).fetchone()
    long_chunk = dict(conn.execute(
        "SELECT * FROM chunks WHERE file_path=? AND title_path=? LIMIT 1",
        (row["file_path"], row["title_path"])
    ).fetchone())
    metadata_x0 = _row_to_metadata(long_chunk)
    result = _format_result_x15(conn, [long_chunk], row["title_path"], metadata_x0)
    assert result["metadata"]["is_x15_truncated"] is True


# 测什么行为：X1.5 路径下 char_offset_start/end + anchor_id 跟随 window 范围（不是单 chunk）
# 输入：长 section 命中
# 期望：metadata 的 char_offset 范围 == win_start/win_end，anchor_id 含 win_start
# 为什么必须测：spec §3 字段契约
def test_metadata_offset_follows_window(conn):
    chunk = _real_section_chunk(conn)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], chunk["title_path"], metadata_x0)
    # X1.5 metadata.char_offset 应基于 window 而不是原 chunk
    md = result["metadata"]
    expected_anchor = f"{chunk['file_path']}#{md['char_offset_start']}"
    assert md["anchor_id"] == expected_anchor


# 测什么行为：组内多 chunks 时 chunk_id 是 score 最高那个的真 DB 主键
# 输入：3 chunks 已按 score 降序，分最高的 chunk_id="winner"
# 期望：result["chunk_id"] == "winner"
# 为什么必须测：spec §1.1a chunk_id 契约（保 by-id 反查）
def test_chunk_id_is_max_score_representative(conn):
    # 直接构造（不依赖真实 DB）
    members = [
        {"chunk_id": "winner", "file_path": "kubernetes/api-eviction.md",
         "title_path": "X", "char_offset_start": 100, "char_offset_end": 200,
         "score": 0.9, "content": "high"},
        {"chunk_id": "loser", "file_path": "kubernetes/api-eviction.md",
         "title_path": "X", "char_offset_start": 300, "char_offset_end": 400,
         "score": 0.5, "content": "low"},
    ]
    metadata_fake = {"file_path": "kubernetes/api-eviction.md", "is_x15_truncated": False}
    result = _format_result_x15(conn, members, "X", metadata_fake)
    # 即使 fallback（title 不存在），chunk_id 仍取 group_chunks[0]
    assert result["chunk_id"] == "winner"
```

- [ ] **Step 2: 跑测试**

```bash
cd backend/ingestion
pytest tests/unit/test_x15_format_result.py -v
```

Expected：8 个测试全绿

- [ ] **Step 3: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/ingestion/tests/unit/test_x15_format_result.py
git commit -m "test(ingestion/x15): 单元测试 _format_result_x15

8 个测试覆盖 SECTION/SINGLE/fallback 三条路径 + metadata 契约。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: 集成测试 - search API X1.5 路径
📖 业内叫：integration test for search endpoints

- **目标：** 端到端测 vector-search / text-search API 在 X1.5 模式下返回正确字段；by-id 接口保持原行为
- **输入：** ingestion 服务运行中
- **输出：** `backend/ingestion/tests/integration/test_x15_search_api.py`
- **验收标准：** pytest 全绿
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/integration/test_x15_search_api.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | vector-search 返回结果含 markdown_anchor | ✅ | test_vector_search_has_markdown_anchor |
| 正常路径 | text-search 同 | ✅ | test_text_search_has_markdown_anchor |
| 正常路径 | by-id 返回单 chunk 不做 X1.5 化 | ✅ | test_by_id_returns_chunk_content |
| 边界值 | top_k 较小（=3）也工作 | ❌ | top_k 是 vec_search 入参，X1.5 不改它，重复测 |
| 异常输入 | embedding 维度错误 | ❌ | 已有路由层 422 校验，跟 X1.5 无关 |
| 状态相关 | 连续两次同 query 返回一致 | ✅ | test_consecutive_queries_consistent |
| 业务规则 | result 数量 ≤ top_k（X1.5 收缩）| ✅ | test_result_count_shrinks |
| 业务规则 | content 含 title_path（非 SINGLE 路径）| ✅ | test_content_has_title_prefix |

- [ ] **Step 1: 写测试**

创建 `backend/ingestion/tests/integration/test_x15_search_api.py`：

```python
"""X1.5 search API 集成测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.2

注意：这些测试需要 ingestion 服务运行 + bge-m3 模型加载。
本地手动跑：先 backend/ingestion/start.sh --bg 等模型 load，再 pytest。
CI 跳过：标记 @pytest.mark.integration，运行 pytest 时加 --no-integration 跳过。
"""
import pytest
import requests
import sqlite3

INGESTION_URL = "http://localhost:3003"


@pytest.fixture(scope="module")
def health_check():
    """跑前确认服务在 + 模型已 load。"""
    try:
        r = requests.get(f"{INGESTION_URL}/health", timeout=2)
        if r.status_code != 200 or not r.json().get("embedding_model_loaded"):
            pytest.skip("ingestion service not up or bge-m3 not loaded")
    except requests.exceptions.RequestException:
        pytest.skip("ingestion service not reachable")


@pytest.fixture(scope="module")
def query_embedding():
    """生成一个真实 query 的 embedding。"""
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-m3")
    return m.encode("React 数据获取库", normalize_embeddings=True).tolist()


# 测什么行为：vector-search 返回的每个 result.metadata 都含 markdown_anchor 字段
# 输入：真实 query embedding
# 期望：所有 result metadata 含 'markdown_anchor' key（值非空）
# 为什么必须测：赛题 citation 输出依赖这字段
def test_vector_search_has_markdown_anchor(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
        timeout=30,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) > 0
    for x in results:
        assert "markdown_anchor" in x["metadata"]
        assert x["metadata"]["markdown_anchor"]


# 测什么行为：text-search 同样含 markdown_anchor
# 输入：真实 query 文本
# 期望：同上
# 为什么必须测：text-search 跟 vector-search 同走 X1.5 路径
def test_text_search_has_markdown_anchor(health_check):
    r = requests.post(
        f"{INGESTION_URL}/chunks/text-search",
        json={"query": "React 数据获取", "top_k": 20},
        timeout=10,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) > 0
    for x in results:
        assert "markdown_anchor" in x["metadata"]


# 测什么行为：by-id 接口返回单 chunk 原 content（不做 X1.5 化）
# 输入：DB 里随便一个 chunk_id
# 期望：返回的 content 等于 DB 该 chunk 的 content（不含 title_path 前缀）
# 为什么必须测：spec 明确 by-id 不改，海军 / debug 工具依赖
def test_by_id_returns_chunk_content(health_check):
    conn = sqlite3.connect("backend/storage/index/knowledge.db")
    conn.row_factory = sqlite3.Row
    chunk = dict(conn.execute(
        "SELECT chunk_id, content, title_path FROM chunks LIMIT 1"
    ).fetchone())
    conn.close()

    r = requests.get(f"{INGESTION_URL}/chunks/{chunk['chunk_id']}", timeout=5)
    assert r.status_code == 200
    body = r.json()
    # by-id 的 content 是原 chunk content（不做 X1.5 化）
    assert body["content"] == chunk["content"]
    # 但 metadata 仍含 markdown_anchor 字段（因为复用 _row_to_metadata）
    assert "markdown_anchor" in body["metadata"]


# 测什么行为：连续两次同 query 返回一致
# 输入：跑两次 vector-search 相同 embedding
# 期望：results 长度和 top-3 chunk_id 一致
# 为什么必须测：缓存正确性 + 无随机性
def test_consecutive_queries_consistent(health_check, query_embedding):
    r1 = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    r2 = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    assert r1["total"] == r2["total"]
    assert [x["chunk_id"] for x in r1["results"][:3]] == \
           [x["chunk_id"] for x in r2["results"][:3]]


# 测什么行为：result 数量 ≤ top_k（X1.5 合并后收缩）
# 输入：top_k=30
# 期望：total ≤ 30
# 为什么必须测：spec 摘要承诺（30 → ~15-20）
def test_result_count_shrinks(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    assert r["total"] <= 30


# 测什么行为：返回的 content 含 title_path 前缀（针对非 SINGLE 路径）
# 输入：真实 query
# 期望：top-3 至少 1 个 result 的 content 以 title_path 开头
# 为什么必须测：核心 X1.5 行为，spec §2.5
def test_content_has_title_prefix(health_check, query_embedding):
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": query_embedding, "top_k": 30},
    ).json()
    has_title_prefix = any(
        x["metadata"]["title_path"]
        and x["content"].startswith(x["metadata"]["title_path"])
        for x in r["results"][:3]
    )
    assert has_title_prefix, "top-3 至少 1 个 result content 应以 title_path 开头"
```

- [ ] **Step 2: 启服务后跑测试**

```bash
backend/ingestion/start.sh --bg
sleep 5
cd backend/ingestion
pytest tests/integration/test_x15_search_api.py -v
```

Expected：6 个测试全绿（如果服务没起会 skip 而非 fail）

- [ ] **Step 3: 关服务 + Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null
git add backend/ingestion/tests/integration/test_x15_search_api.py
git commit -m "test(ingestion/x15): 集成测试 search API + by-id 不变

6 个端到端测试覆盖 markdown_anchor 字段、by-id 不做 X1.5、result 收缩、title_path 前缀。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: 集成测试 - 痛点 query 回归
📖 业内叫：painpoint regression test

- **目标：** 把 Phase 1 手动跑的 2 个痛点 query 转成 pytest，未来每次提交都跑
- **输入：** ingestion 服务运行
- **输出：** `backend/ingestion/tests/integration/test_x15_painpoints.py`
- **验收标准：** pytest 通过
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/tests/integration/test_x15_painpoints.py`

**测试场景清单**

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | K8s 驱逐 query top-3 含 kubelet 任一关键词 | ✅ | test_k8s_eviction_painpoint |
| 正常路径 | React 数据获取 query top-3 含 TanStack Query 任一关键词 | ✅ | test_react_data_fetching_painpoint |
| 边界值 | 全测试集 200 题 | ❌ | 留给 baseline 脚本（task 16），不在 unit 跑 |
| 异常输入 | 空 query | ❌ | 跟 X1.5 无关，路由层处理 |
| 状态相关 | 连续重跑稳定 | ❌ | 已在 task 13 测过 |
| 业务规则 | 痛点 query 必含答案关键词 | ✅ | 主目标 |

- [ ] **Step 1: 写测试**

创建 `backend/ingestion/tests/integration/test_x15_painpoints.py`：

```python
"""X1.5 痛点 query 回归测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.2

这两题在 X0 路径下 top-3 不含答案；X1.5 必须救回 top-3。
"""
import pytest
import requests
from sentence_transformers import SentenceTransformer

INGESTION_URL = "http://localhost:3003"


@pytest.fixture(scope="module")
def health_check():
    try:
        r = requests.get(f"{INGESTION_URL}/health", timeout=2)
        if r.status_code != 200 or not r.json().get("embedding_model_loaded"):
            pytest.skip("ingestion not up")
    except requests.exceptions.RequestException:
        pytest.skip("ingestion not reachable")


@pytest.fixture(scope="module")
def embed_model():
    return SentenceTransformer("BAAI/bge-m3")


def _retrieve_top3(model, query):
    emb = model.encode(query, normalize_embeddings=True).tolist()
    r = requests.post(
        f"{INGESTION_URL}/chunks/vector-search",
        json={"embedding": emb, "top_k": 30},
        timeout=30,
    )
    return r.json()["results"][:3]


# 测什么行为：K8s "API 发起驱逐" query 在 X1.5 下 top-3 含 kubelet/宽限期/EndpointSlice 任一关键词
# 输入：真实 query
# 期望：top-3 至少 1 个 result content 含答案关键词
# 为什么必须测：X1.5 设计的核心痛点，回归测试防退化
def test_k8s_eviction_painpoint(health_check, embed_model):
    top3 = _retrieve_top3(embed_model, "API 发起驱逐的工作原理是什么")
    keywords = ["kubelet", "宽限期", "EndpointSlice"]
    hit = any(any(kw in r["content"] for kw in keywords) for r in top3)
    assert hit, f"top-3 不含 {keywords} 任一关键词，X1.5 退化！"


# 测什么行为：React 数据获取库 query 在 X1.5 下 top-3 含 TanStack Query/SWR/RTK Query 任一
# 输入：真实 query
# 期望：top-3 至少 1 个 result content 含关键词
# 为什么必须测：第二个痛点，回归测试
def test_react_data_fetching_painpoint(health_check, embed_model):
    top3 = _retrieve_top3(
        embed_model,
        "从大多数后端或 REST 风格 API 获取数据时，React 建议使用哪些库？",
    )
    keywords = ["TanStack Query", "SWR", "RTK Query"]
    hit = any(any(kw in r["content"] for kw in keywords) for r in top3)
    assert hit, f"top-3 不含 {keywords} 任一关键词，X1.5 退化！"
```

- [ ] **Step 2: 启服务跑测试**

```bash
backend/ingestion/start.sh --bg
sleep 5
cd backend/ingestion
pytest tests/integration/test_x15_painpoints.py -v
```

Expected：2 个测试全绿

- [ ] **Step 3: 关服务 + Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
kill $(cat backend/ingestion/logs/server.pid) 2>/dev/null
git add backend/ingestion/tests/integration/test_x15_painpoints.py
git commit -m "test(ingestion/x15): 集成测试痛点 query 回归

K8s 驱逐 + React 数据获取两题，X1.5 必须救回 top-3。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: baseline 对比脚本（200 题 X0 vs X1.5）
📖 业内叫：retrieval recall baseline evaluation

- **目标：** 写一个脚本跑赛题 200 题，对比 X0 和 X1.5 的召回率（按 anchor_hit + evidence_hit 两指标）
- **输入：** `docs/Public_Test_Set.jsonl`（200 题）+ ingestion 内部底层函数
- **输出：** `backend/ingestion/scripts/eval_x15_baseline.py` + `/tmp/x15_baseline_result.json`
- **验收标准：** 脚本能跑通输出 JSON，**X1.5 anchor_hit ≥ X0 anchor_hit**（硬性 release gate）
- **是否当前必须：** 是
- **关键节点：** 是（数据决定 X1.5 是否值得上线）

**Files:**
- Create: `backend/ingestion/scripts/eval_x15_baseline.py`

- [ ] **Step 1: 写脚本**

创建 `backend/ingestion/scripts/eval_x15_baseline.py`：

```python
"""X1.5 vs X0 召回率 baseline 对比脚本。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §7.3

直接调内部底层函数（不走 HTTP，无需重启服务）。
跑 200 题，分别走 X0 和 X1.5 路径，输出 JSON。
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.chunks_repo import vector_search
from backend.ingestion.api.routes_search import _format_result_legacy, _row_to_metadata
from backend.ingestion.api.x15 import (
    group_results,
    _format_result_x15,
    _read_raw_file,
    clear_section_range_cache,
)

DB_PATH = Path("backend/storage/index/knowledge.db")


def x0_retrieve(conn, embedding, top_k):
    """X0 路径：直接 _format_result_legacy 每个 row。"""
    rows = vector_search(conn, embedding, top_k=top_k)
    return [_format_result_legacy(r) for r in rows]


def x15_retrieve(conn, embedding, top_k):
    """X1.5 路径：分组 + _format_result_x15。"""
    rows = vector_search(conn, embedding, top_k=top_k)
    groups = group_results(rows)
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -kv[1][0].get("score", 0),
    )
    results = []
    for key, members in sorted_groups:
        title_path = members[0].get("title_path") if key[0] == "SECTION" else ""
        metadata_x0 = _row_to_metadata(members[0])
        results.append(
            _format_result_x15(conn, members, title_path or "", metadata_x0)
        )
    return results


def is_anchor_hit(top_results, gold):
    """主指标：top-3 中至少 1 个 result 同时命中 gold doc_path + anchor。"""
    gold_doc = gold["doc_path"].removeprefix("docs/")
    gold_anchor = gold["anchor"]
    return any(
        r["metadata"]["file_path"] == gold_doc
        and r["metadata"]["markdown_anchor"] == gold_anchor
        for r in top_results
    )


def is_evidence_hit(top_results, gold):
    """辅助指标：top-3 中至少 1 个 result content 含 gold evidence 子串（前 50 字符）。"""
    needle = gold["evidence"][:50]
    return any(needle in r["content"] for r in top_results)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-set", default="docs/Public_Test_Set.jsonl")
    ap.add_argument("--output", default="/tmp/x15_baseline_result.json")
    ap.add_argument("--top-k", type=int, default=30)
    args = ap.parse_args()

    print(f"Loading bge-m3...")
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-m3")

    print(f"Loading test set: {args.test_set}")
    test_items = [json.loads(line) for line in open(args.test_set)]
    print(f"  {len(test_items)} 题")

    conn = get_connection(DB_PATH)
    _read_raw_file.cache_clear()
    clear_section_range_cache()

    summary = {
        "x0_anchor_hit": 0, "x15_anchor_hit": 0,
        "x0_evidence_hit": 0, "x15_evidence_hit": 0,
        "x0_only_anchor_hit": [], "x15_only_anchor_hit": [],
        "both_anchor_hit": [], "both_anchor_miss": [],
    }
    per_query = []

    t0 = time.time()
    for i, item in enumerate(test_items, 1):
        if i % 20 == 0:
            print(f"  [{i}/{len(test_items)}] elapsed {time.time()-t0:.1f}s")

        emb = m.encode(item["question"], normalize_embeddings=True).tolist()
        x0_top3 = x0_retrieve(conn, emb, args.top_k)[:3]
        x15_top3 = x15_retrieve(conn, emb, args.top_k)[:3]

        gold = item["gold_sources"][0]
        x0_a = is_anchor_hit(x0_top3, gold)
        x15_a = is_anchor_hit(x15_top3, gold)
        x0_e = is_evidence_hit(x0_top3, gold)
        x15_e = is_evidence_hit(x15_top3, gold)

        summary["x0_anchor_hit"] += int(x0_a)
        summary["x15_anchor_hit"] += int(x15_a)
        summary["x0_evidence_hit"] += int(x0_e)
        summary["x15_evidence_hit"] += int(x15_e)

        if x0_a and not x15_a: summary["x0_only_anchor_hit"].append(item["id"])
        if x15_a and not x0_a: summary["x15_only_anchor_hit"].append(item["id"])
        if x0_a and x15_a: summary["both_anchor_hit"].append(item["id"])
        if not x0_a and not x15_a: summary["both_anchor_miss"].append(item["id"])

        per_query.append({
            "id": item["id"],
            "domain": item["domain"],
            "query": item["question"],
            "gold_doc": gold["doc_path"],
            "gold_anchor": gold["anchor"],
            "x0_anchor_hit": x0_a, "x15_anchor_hit": x15_a,
            "x0_evidence_hit": x0_e, "x15_evidence_hit": x15_e,
            "x0_top3_anchors": [
                f"{r['metadata']['file_path']}{r['metadata']['markdown_anchor']}"
                for r in x0_top3
            ],
            "x15_top3_anchors": [
                f"{r['metadata']['file_path']}{r['metadata']['markdown_anchor']}"
                for r in x15_top3
            ],
        })

    summary["improvement_anchor"] = summary["x15_anchor_hit"] - summary["x0_anchor_hit"]
    summary["improvement_evidence"] = summary["x15_evidence_hit"] - summary["x0_evidence_hit"]
    summary["total"] = len(test_items)
    summary["elapsed_seconds"] = time.time() - t0

    Path(args.output).write_text(json.dumps(
        {"summary": summary, "per_query": per_query},
        ensure_ascii=False, indent=2
    ))

    print()
    print("=" * 60)
    print(f"X0  anchor_hit:   {summary['x0_anchor_hit']}/{len(test_items)}")
    print(f"X15 anchor_hit:   {summary['x15_anchor_hit']}/{len(test_items)}")
    print(f"提升:             {summary['improvement_anchor']:+d} 题")
    print(f"X0  evidence_hit: {summary['x0_evidence_hit']}/{len(test_items)}")
    print(f"X15 evidence_hit: {summary['x15_evidence_hit']}/{len(test_items)}")
    print(f"耗时:             {summary['elapsed_seconds']:.1f}s")
    print(f"详细 JSON:        {args.output}")
    print()

    # release gate
    if summary["x15_anchor_hit"] >= summary["x0_anchor_hit"]:
        print("✅ release gate: x15 anchor_hit >= x0 anchor_hit")
    else:
        print("❌ release gate FAIL: x15 召回率低于 x0!")
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本**

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python3 backend/ingestion/scripts/eval_x15_baseline.py \
    --test-set docs/Public_Test_Set.jsonl \
    --output /tmp/x15_baseline_result.json
```

Expected：
- 跑 ~5-10 分钟（200 题 × 2 路径）
- 屏幕输出 X0/X1.5 anchor_hit + improvement
- **release gate**：`x15_anchor_hit >= x0_anchor_hit` 通过

- [ ] **Step 3: 把结果摘要追加到 progress 文件**

```bash
cat >> docs/superpowers/progress/2026-04-30-x15-baseline.md <<'EOF'
# X1.5 baseline 对比

**时间**: 2026-04-30
**测试集**: docs/Public_Test_Set.jsonl (200 题)
**完整结果**: /tmp/x15_baseline_result.json

## 关键指标

[把脚本输出的 X0/X15 anchor_hit + improvement 复制贴这里]

## 验收

- [x/?] release gate (x15 ≥ x0): __
- [x/?] 期望提升 (≥ +5): __

EOF

mkdir -p docs/superpowers/progress
git add docs/superpowers/progress/2026-04-30-x15-baseline.md backend/ingestion/scripts/eval_x15_baseline.py
git commit -m "feat(ingestion/scripts): X1.5 baseline 对比脚本 + 200 题首次结果

- eval_x15_baseline.py 跑全测试集，对比 X0 vs X1.5 anchor_hit/evidence_hit
- 输出 JSON 含 per_query 详情
- release gate: x15 anchor_hit ≥ x0 anchor_hit (硬性)
- 期望: ≥ +5 题提升

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: 数据校验脚本 verify_section_grouping.py
📖 业内叫：grouping invariant guard

- **目标：** 校验 (file_path, title_path) 分组下 chunk_index 100% 连续的假设。未来 reindex / 新文档可能引入边角 case 让分组静默误并，这个脚本提前抓出
- **输入：** DB
- **输出：** `backend/ingestion/scripts/verify_section_grouping.py` + 当前数据 0 违规
- **验收标准：** 脚本跑通且 violations 列表为空（当前数据 0 违规已数据验证过）
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Create: `backend/ingestion/scripts/verify_section_grouping.py`

- [ ] **Step 1: 写脚本**

```python
"""校验 (file_path, title_path) 分组的 chunk_index 连续性。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.1 显式假设

未来若 chunker 升级 / 文档新增 / reindex 引入边角 case（同文件下两个不同物理 section 共享相同 title_path 文本），
分组逻辑会静默误并这两段。本脚本提前抓出。

退出码：
  0 = 全部通过
  1 = 发现违规
"""
import sys
import sqlite3
from pathlib import Path

DB_PATH = Path("backend/storage/index/knowledge.db")


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
            violations.append(f"{r['file_path']} | tp={r['tp']!r}: {indices}")
    return violations


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    violations = verify_section_grouping(conn)
    conn.close()

    if violations:
        print(f"❌ 发现 {len(violations)} 个分组假设违规：")
        for v in violations[:20]:
            print(f"  {v}")
        if len(violations) > 20:
            print(f"  ... 共 {len(violations)} 项，仅展示前 20")
        print()
        print("X1.5 (file_path, title_path) 分组假设失效，需排查 chunker 输出或语料是否有重复 title_path。")
        sys.exit(1)
    else:
        print(f"✅ 所有分组的 chunk_index 100% 连续，X1.5 分组假设成立")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本**

```bash
python3 backend/ingestion/scripts/verify_section_grouping.py
```

Expected：`✅ 所有分组的 chunk_index 100% 连续`

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/scripts/verify_section_grouping.py
git commit -m "feat(ingestion/scripts): verify_section_grouping 数据校验

防 X1.5 分组假设静默失效（未来 reindex 或新文档引入重复 title_path）。
当前数据 0 违规验证通过。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: 可维护性

---

### Task 17: 更新 INTERFACE.md
📖 业内叫：API contract documentation

- **目标：** 把 X1.5 引入的字段变化和契约调整写进 INTERFACE.md
- **输入：** spec
- **输出：** 更新后的 `backend/ingestion/INTERFACE.md`
- **验收标准：** INTERFACE.md 含 markdown_anchor / is_x15_truncated 字段说明 + char_offset 跟随 content 的语义注释 + Layer 2 映射建议
- **是否当前必须：** 是
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/INTERFACE.md`

- [ ] **Step 1: 在 INTERFACE.md 加 X1.5 字段说明**

打开 `backend/ingestion/INTERFACE.md`，找到 metadata 字段表（grep "metadata.anchor_id"），在表的合适位置追加：

```markdown
| `metadata.markdown_anchor` | string | markdown section anchor，如 `#top` 或 `#section-id`；**赛题 citation 输出用**。Layer 2 海军应映射到 `RetrievedChunk.anchor` |
| `metadata.is_x15_truncated` | bool | X1.5 max_chars 截断标记。**仅 X1.5 路径**实际发生截断时为 true，其它情况（X0 路径、SINGLE 退化、by-id 接口、未截断的 X1.5）一律 false |
```

在 "字段定义" 段后追加新一节：

```markdown
## X1.5 search 接口字段语义（重要）

自 commit `<X1.5 实施 commit hash>` 起，`vector-search` / `text-search` 接口的字段语义有以下变化：

### 不变（保契约）

- `chunk_id`：DB sha256 真主键，组内分最高 chunk 的代表，可用 by-id 反查
- `metadata.title_path` / `metadata.is_truncated` / 其它从代表 chunk 继承
- `total` 字段 = `len(results)`，分组合并后的返回条数

### 跟随 content 走（X1.5 路径）

- `content` = `title_path + "\n\n" + raw_slice (max_chars=2000 居中截)`
- `metadata.char_offset_start` = window 起点（不是代表 chunk 的）
- `metadata.char_offset_end` = window 终点
- `metadata.anchor_id` = `f"{file_path}#{char_offset_start}"`，跟着 window 起点

### 新增（赛题输出用）

- `metadata.markdown_anchor`：section 标识（如 `#api-发起驱逐` / `#top`），**赛题判分按这字段**
- `metadata.is_x15_truncated`：X1.5 截断标记

### 收缩（合并影响）

- 同 `(file_path, title_path)` 内多个命中合并为 1 个 result
- 30 个候选可能收缩到 ~15-20 个 result（取决于命中分布）

### by-id 接口不变

- `GET /chunks/{chunk_id}` 仍返回单 chunk 原 content
- metadata 也含 `markdown_anchor` / `is_x15_truncated=false`（复用 _row_to_metadata）

### Layer 2 映射建议（**海军 team 改动**）

```python
# backend/LLM/retrieval.py
def to_retrieved_chunk(api_result: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=api_result["chunk_id"],
        content=api_result["content"],
        doc_path=api_result["metadata"]["file_path"],
        anchor=api_result["metadata"]["markdown_anchor"],  # ← 改这一行
        score=api_result["score"],
        is_truncated=api_result["metadata"]["is_truncated"],
        title_path=api_result["metadata"].get("title_path"),
    )
```
```

- [ ] **Step 2: 验证文档可读性（grep 关键字段）**

```bash
grep -n "markdown_anchor\|is_x15_truncated" backend/ingestion/INTERFACE.md
```

Expected：至少 4 行命中

- [ ] **Step 3: Commit**

```bash
git add backend/ingestion/INTERFACE.md
git commit -m "docs(ingestion/INTERFACE): X1.5 字段变化和契约调整

- markdown_anchor / is_x15_truncated 字段说明
- char_offset / anchor_id 跟随 content（X1.5 时是 window）
- result 数量收缩说明
- 海军侧映射建议

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 18: Codex review baseline 结果（可选交叉验证）
📖 业内叫：cross-engine baseline review

- **目标：** 让 ChatGPT 独立审一遍 baseline 结果，找盲点
- **输入：** Task 15 跑出的 baseline_result.json + 脚本
- **输出：** Codex 审查报告（贴回对话）
- **验收标准：** Codex 输出 "Approved" 或列出 Issues 供讨论；如有 issue 用户拍板修不修
- **是否当前必须：** 否（advisory，不影响上线）
- **关键节点：** 是（Codex 输出后必停等用户审）

**Files:**
- 无新文件，纯 cross-review.sh 调用 + 报告记录

- [ ] **Step 1: 跑 cross-review**

```bash
bash .claude/skills/brainstorming/scripts/cross-review.sh \
    backend/ingestion/scripts/eval_x15_baseline.py \
    /tmp/x15_baseline_result.json
```

- [ ] **Step 2: 把 Codex 输出贴到 progress 文件**

```bash
# 把上面命令的 review 报告（codex 输出段）复制到这里
cat >> docs/superpowers/progress/2026-04-30-x15-baseline.md <<'EOF'

## Codex 交叉审查

[贴 Codex 审查报告，包含 Status / Issues / Recommendations 段]

EOF

git add docs/superpowers/progress/2026-04-30-x15-baseline.md
git commit -m "docs(progress): X1.5 baseline Codex 交叉审查记录

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: 必停等用户拍板（关键节点）**

**stop here** —— 把 Codex 报告贴回对话，让用户决定：
- Approved → 进 Task 19 收尾
- Issues Found → 跟用户讨论是否修，修完再进 Task 19

---

### Task 19: 推送 + 通知海军 team
📖 业内叫：merge + cross-team handoff

- **目标：** push 全部 X1.5 commits 到 origin/main，让海军 team 知道字段已暴露可对接
- **输入：** Phase 1-3 全部 commits
- **输出：** main 分支推送 + 给海军 team 的对接说明
- **验收标准：** `git status` clean，`git log origin/main..HEAD` 为空（已 push 同步），INTERFACE.md 在 origin/main 可访问
- **是否当前必须：** 是
- **关键节点：** 是（push 是跨 team 可见的不可逆动作）

**Files:**
- 无文件改动，纯 git push + 通信

- [ ] **Step 1: 看 commits 确认状态**

```bash
git log --oneline origin/main..HEAD
git status
```

Expected：commits 列表对应 Task 1-17（约 15-17 个 commit），working tree clean

- [ ] **Step 2: push（关键节点，必停等用户审 push）**

**stop here** — 把 `git log` 输出给用户看，问是否 push origin main。

用户批准后：

```bash
git push origin main
```

Expected：push 成功

- [ ] **Step 3: 写一条给海军 team 的对接说明（贴回对话）**

写一段简短文字：

```
@海军 team:

X1.5 已合并到 main（commit <hash>）。ingestion API 现在多两个字段：
- metadata.markdown_anchor (赛题 citation 用)
- metadata.is_x15_truncated (X1.5 截断标记)

需要海军侧改 backend/LLM/retrieval.py 的 to_retrieved_chunk 函数，把
RetrievedChunk.anchor 从原来的 anchor_id 改成映射 metadata.markdown_anchor。
具体见 backend/ingestion/INTERFACE.md "Layer 2 映射建议" 段。

应急回滚：INGESTION_X15_ENABLED=false 重启 ingestion 即可（30 秒回 X0）。

baseline 数据：/tmp/x15_baseline_result.json (X1.5 anchor_hit XX/200 vs X0 XX/200，提升 +XX 题)
```

- [ ] **Step 4: 不 commit（已无文件改动），任务结束**

---

## Self-Review

按白话 writing-plans skill 要求的 9 项 self-review。

**1. Spec 覆盖**：

| Spec 章节 | 对应 Task |
|---|---|
| §1 改造范围（routes_search.py + x15.py + INTERFACE.md）| Task 1, 2-7, 17 |
| §2.1 分组 | Task 5, 10 |
| §2.2 居中截 | Task 4, 9 |
| §2.3 section 真边界 | Task 3 |
| §2.4 LRU 缓存 | Task 2, 11 |
| §2.5 _format_result_x15 | Task 6, 12 |
| §2.6 入口 + flag | Task 7 |
| §3 metadata 字段规范 | Task 1, 17 |
| §4 失败 fallback 矩阵 | Task 6, 12 |
| §5 feature flag | Task 7 |
| §6 跨 team 上线依赖 | Task 17, 19 |
| §7.1 单元测试 4 文件 | Task 9-12 |
| §7.2 集成测试 | Task 13, 14 |
| §7.3 baseline + hit 规则 | Task 15 |
| §7.4 Codex 交叉验证 | Task 18 |
| §2.1 显式假设 + 数据校验 | Task 16 |

**所有 spec 章节都有对应 task 覆盖**。

**2. Placeholder scan**：搜过 "TBD" / "TODO" / "implement later"，0 命中。

**3. Type consistency**：
- `_format_result_x15(conn, group_chunks, title_path, metadata_x0)` 在 Task 6 / 7 / 12 / 15 一致
- `assign_group_key` / `group_results` / `make_window` / `_read_raw_file` / `get_section_full_range` 函数名跨 task 一致
- `metadata.markdown_anchor` / `metadata.is_x15_truncated` 字段名跨 Task 1 / 12 / 13 / 17 一致

**4. 外行版摘要**：顶部存在，4 必答问题都答了，约 350 字。

**5. 三阶段完整**：
- Phase 1 (Task 1-8)：最小可跑 + 烟雾测试
- Phase 2 (Task 9-16)：单元 + 集成 + baseline + 数据校验
- Phase 3 (Task 17-19)：文档 + Codex review + push

**6. 任务 4 字段**：每个 Task 都有 目标 / 输入 / 输出 / 验收 / 当前必须 / 关键节点。

**7. 任务名白话**：每个 Task 标题都是大白话主标题 + 📖 业内叫副行。

**8. 测试场景清单**：Task 9, 10, 11, 12, 13, 14 6 个测试 task 都有 6 维度矩阵；❌ 都配了理由。

**9. 测试代码白话说明**：每个测试函数上方都有 4 字段（测什么/输入/期望/为什么必须测）。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-x15-rigorous-implementation.md`**.

**两种执行方式：**

**1. Subagent-Driven**（默认推荐，但用户偏好 inline）—— 每个 task 派 fresh subagent，task 间 review，快速迭代

**2. Inline Execution**（用户偏好）—— 当前 session 直接跑，按 Phase 边界 checkpoint review

**根据 memory 偏好"长 plan 执行 inline 优先"，默认走 inline executing-plans。**

是否同意 inline 执行？或者改用其它方式？
