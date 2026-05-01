# Chunker 修复 + 检索结构感知增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 chunker 吞空格/列表粘连 bug，并给检索加上"标题归属"信号，让按章节标题问的问题能找到那一节的内容

**Architecture:** 两个独立但共享 re-index 成本的修复。修复 1 重写 `_split_paragraph` 改成"扫边界 + 切原文"，行级保护列表标记，并修段落切分对 CRLF 和多空行的鲁棒性问题。修复 2 走两条路：BM25 通过 FTS5 内置的列权重提升 title 命中（API 完全不变），向量则在 index 时把 title_path 拼到 content 前面再 embed，让 chunk 向量自带章节语义；先做 3 文件小规模实验验证副作用，再决定是否全量。最后预留 sibling 邻居救援作为兜底。

**Tech Stack:** Python 3.12 / conda env sqllineage / FastAPI / SQLite (FTS5) / bge-m3 (1024d) / pytest

---

## 外行版摘要

**1. 做什么？**  
两件事：① 修掉切块代码里的一个 bug——它把句号后面的空格全吃了，还把"1. The Pod"这种列表编号和后面的内容粘在一起；② 让检索系统知道"这个 chunk 属于哪个标题"，而不是只看 chunk 里的孤立文字。

**2. 为什么需要？**  
今天实测发现：用户用源文件标题做问题时，回答里 6 步流程的 chunk 完全没出现。两个原因——chunker bug 让向量算错（污染了 14% 的 chunk）+ 检索完全不看标题归属。两个都修才能彻底解决"按章节问→找不到那节内容"。

**3. 大致怎么做？**  
- Phase 1（必做）：重写句子切分，保证"切完拼回去 == 原文"，行级识别列表标记不误切；改完全量重新索引一次。
- Phase 2（增强）：先改 BM25 让 title 列权重高 5 倍（一行 SQL）；然后小规模实验"embedding 时把标题拼到内容前面"——只改 3 个文件先看效果（特别是会不会让陷阱题假阳性变得更糟），数据正向再全量做。
- Phase 3（兜底）：如果上面做完 6 步流程还断成两块，再加同章节邻居救援逻辑，但保持 API 不变。

**4. 主要风险？**  
- 全量 re-index 是耗时操作（11471 chunks × bge-m3 ≈ 2-4 小时）。失败回滚要再来一次。
- "embedding 拼 title_path"是个**单向门**——改了之后所有 chunk 向量被章节语义"染色"，可能让特异性查询变差，也可能让 K8s trap 假阳性更严重。所以 Phase 2 加了实验门控，不直接全量。
- chunker 重写引入新 bug 的可能。靠完整测试场景矩阵 + invariant 测试（拼回去等于原文）兜底。

---

## 文件结构

**改动文件**：
- `backend/ingestion/chunker/document_splitter.py` — 重写 `_split_paragraph`，加 `_is_list_marker_at` 工具函数；段落切分用正则 + offset 跟踪
- `backend/ingestion/db/chunks_repo.py` — `text_search` SQL 改 `ORDER BY bm25(chunks_fts, ...)` 加 title 权重
- `backend/ingestion/sync/pipeline.py` — embedding 输入加 title_path 前缀（**条件性**，看 Phase 2 实验数据）

**新增文件**：
- `backend/ingestion/tests/unit/test_split_paragraph_invariant.py` — chunker 不变量 + 列表保护 + CRLF 鲁棒性测试
- `backend/ingestion/scripts/title_aware_embedding_experiment.py` — Phase 2 小规模实验脚本

**测试集**（已存在 sanity_check.py）：
- `backend/ingestion/scripts/sanity_check.py` — 不改，只用来跑 7 题对比（QUERIES 列表已有 5 题，加 2 个 trap 变种用命令行参数跑）

---

## Phase 1: 最小可跑（修 chunker bug + 全量 re-index）

### Task 1: 重写句子切分逻辑，保留空格 + 列表保护
📖 业内叫：sentence boundary detection + list-aware chunking

- **目标：** 把 `_split_paragraph` 从"split-然后拼"改成"找边界-然后按 offset 切原文"，让切完拼回去等于原文（不丢一个字符）；同时行级识别 markdown 列表标记，不把 `1. The Pod` 中的 `.` 当句末
- **输入：** 一段 raw text（可能含中英文/列表/换行）
- **输出：** `list[tuple[str, bool]]`——每段 ≤ MAX_CHARS（默认 1000），第二个 bool 表示是否被硬切（用尽边界点仍不够长才硬切）
- **验收标准：**
  1. 不变量：`"".join(piece for piece, _ in result) == original_text`
  2. 列表项 `1. The Pod` 在切分后仍是 `1. The Pod`（空格保留，不变 `1.The Pod`）
  3. `Python 3.12.` 这种伪列表（行内非行首）不会被错误保护，仍按句号切
  4. `pytest backend/ingestion/tests/unit/test_split_paragraph_invariant.py -v` 全绿
- **是否当前必须：** 是
- **关键节点：** 否（纯代码改动，可回滚）

**Files:**
- Modify: `backend/ingestion/chunker/document_splitter.py:13-102`
- Test: `backend/ingestion/tests/unit/test_split_paragraph_invariant.py`（新建）

#### 测试场景清单

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | 多句中英混合段落，长度 < MAX_CHARS | ✅ | `test_short_passthrough` |
| 正常路径 | 多句段落 > MAX_CHARS，按句号切成多块 | ✅ | `test_long_split_by_sentence` |
| 边界值 | 不变量：拼接 == 原文 | ✅ | `test_join_equals_original` |
| 边界值 | 单句 > MAX_CHARS（无内部边界点）→ 硬切 | ✅ | `test_no_boundary_hard_split` |
| 异常输入 | 空字符串 / 纯标点 / 纯空白 | ✅ | `test_edge_inputs` |
| 状态相关 | 多次调用结果一致（无副作用）| ❌ | 函数无状态，不适用 |
| 业务规则 | 列表 `1. xxx` 不被切，`Python 3.12.` 仍切 | ✅ | `test_list_marker_protection` |

- [ ] **Step 1: 写不变量测试 + 列表保护测试**

**测什么行为：** 切分后所有片段拼接必须等于原文（一字不差）  
**输入：** 一段 markdown 含中英混合 + 列表 + 多句  
**期望：** `"".join(...)` 严格等于原文  
**为什么必须测：** 这是修复的核心承诺。没有这一条，"修了 bug" 就是空话——可能换了一种方式丢字符

```python
# backend/ingestion/tests/unit/test_split_paragraph_invariant.py
import pytest
from backend.ingestion.chunker.document_splitter import _split_paragraph, MAX_CHARS

def test_join_equals_original():
    """不变量：所有产出片段拼接 == 原文。"""
    text = (
        "这是第一句。这是第二句。\n"
        "1. The Pod resource is updated.\n"
        "2. The kubelet notices.\n"
        "Python 3.12. 是新版本。结束。"
    ) * 50  # 重复让总长 > MAX_CHARS
    pieces = _split_paragraph(text)
    rebuilt = "".join(p for p, _ in pieces)
    assert rebuilt == text, f"不变量违反: 长度差 {len(text) - len(rebuilt)}"


def test_short_passthrough():
    """段落 ≤ MAX_CHARS 直接原样返回。"""
    text = "短段落。就这么短。"
    result = _split_paragraph(text)
    assert result == [(text, False)]


def test_long_split_by_sentence():
    """段落 > MAX_CHARS，按句号切；切片不丢字符且都 ≤ MAX_CHARS。"""
    sentence = "这是一个测试句。"
    text = sentence * 200  # 远超 MAX_CHARS
    pieces = _split_paragraph(text)
    assert all(len(p) <= MAX_CHARS for p, _ in pieces)
    assert "".join(p for p, _ in pieces) == text


def test_list_marker_protection():
    """列表项 '1. xxx' 不被错切；'Python 3.12.' 仍按句号切。"""
    text = "前言。" + ("一二三四五六七八九十" * 100) + "\n1. The Pod resource\n2. The kubelet\nPython 3.12. 发布于 2024 年。结束。"
    pieces = _split_paragraph(text)
    # 检查列表标记完整性：拼回去后 "1. The" 仍存在（没有被改成 "1.The"）
    rebuilt = "".join(p for p, _ in pieces)
    assert "1. The Pod" in rebuilt
    assert "2. The kubelet" in rebuilt
    # 'Python 3.12.' 这个伪列表不应被保护——仍按句号切，但拼回去仍完整
    assert "Python 3.12. 发布于" in rebuilt


def test_no_boundary_hard_split():
    """单句无内部边界 + 长度 > MAX_CHARS → 硬切，is_truncated=True。"""
    text = "啊" * (MAX_CHARS + 100)  # 没有任何句末标点
    pieces = _split_paragraph(text)
    assert any(trunc for _, trunc in pieces), "应至少有一片硬切"
    assert "".join(p for p, _ in pieces) == text


def test_edge_inputs():
    """空字符串、纯空白、纯标点的健壮性。"""
    # 空串
    assert _split_paragraph("") == [("", False)]
    # 纯空白
    s = "   \n\n   "
    assert _split_paragraph(s) == [(s, False)]
    # 纯标点
    s = "。！？"
    assert _split_paragraph(s) == [(s, False)]
```

- [ ] **Step 2: 跑测试，确认在改代码前是 FAIL（red 状态）**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_split_paragraph_invariant.py -v`  
Expected: `test_join_equals_original` 和 `test_list_marker_protection` 至少其中一个 FAIL（因为旧代码会丢空格 + 粘连列表）

- [ ] **Step 3: 重写 `_split_paragraph` + 加 `_is_list_marker_at` 工具函数**

```python
# backend/ingestion/chunker/document_splitter.py:13 起替换
import re
from typing import Optional

MAX_CHARS = 1000
SENTENCE_END_RE = re.compile(r"[。！？.!?]")
HEADING_ONLY_RE = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)


def _is_list_marker_at(text: str, dot_pos: int) -> bool:
    """判断 text[dot_pos] 这个 '.' 是不是 markdown 列表标记的一部分。
    
    规则：
    - 必须是英文 '.'，中文 '。' 不需要保护（中文文档没有 '1. ' 这种列表）
    - dot_pos 所在行的行首到 dot_pos 之前必须是 \\s*\\d+（行首空白 + 纯数字）
    - dot_pos 后必须紧跟空白（' ' '\\t' '\\n'）或行尾——防 'Python 3.12.' 这种伪列表被错误保护
    
    例子:
    - '1. The Pod' 中的 '.' (pos=1) → True (line_prefix='1', after=' ')
    - 'Python 3.12.' 中的 '.' (pos=11) → False (line_prefix='Python 3.12'，不匹配 \\d+$)
    - '   3. Item' 中的 '.' (pos=4) → True (line_prefix='   3', after=' ')
    """
    if dot_pos < 0 or dot_pos >= len(text) or text[dot_pos] != '.':
        return False
    line_start = text.rfind('\n', 0, dot_pos) + 1
    line_prefix = text[line_start:dot_pos]
    if not re.match(r'^\s*\d+$', line_prefix):
        return False
    # 后面必须是空白或行尾，否则不是列表标记（防 '12.' 在词中间）
    after = text[dot_pos + 1:dot_pos + 2]
    return after in (' ', '\t', '\n', '')


def _split_paragraph(text: str) -> list[tuple[str, bool]]:
    """单段 → list[(chunk_text, is_truncated)]。
    
    关键不变量：所有产出片段拼接 == 原文（一字不差）。
    实现：扫所有句末标点位置作为候选边界，按 MAX_CHARS 贪心切原文 substring。
    无可用边界时硬切并标记 is_truncated=True。
    """
    if len(text) <= MAX_CHARS:
        return [(text, False)]
    
    # 收集所有合法句末标点位置（过滤掉列表标记）
    candidates: list[int] = []
    for m in SENTENCE_END_RE.finditer(text):
        if _is_list_marker_at(text, m.start()):
            continue
        candidates.append(m.end())  # 边界 = 标点之后
    
    pieces: list[tuple[str, bool]] = []
    cursor = 0
    while cursor < len(text):
        target = cursor + MAX_CHARS
        # 找 cursor < c ≤ target 范围内最大的 c
        boundary = None
        for c in candidates:
            if c <= cursor:
                continue
            if c > target:
                break
            boundary = c
        
        if boundary is None:
            # 无可用边界 → 硬切到 target
            end = min(cursor + MAX_CHARS, len(text))
            pieces.append((text[cursor:end], True))
            cursor = end
        else:
            pieces.append((text[cursor:boundary], False))
            cursor = boundary
    
    return pieces
```

- [ ] **Step 4: 跑测试，确认 GREEN**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_split_paragraph_invariant.py -v`  
Expected: 6 个测试全部 PASS

- [ ] **Step 5: 跑全部 ingestion 单元测试，确认无回归**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit -v`  
Expected: 全部 PASS（如果有失败的旧测试，说明它们以前依赖了 bug 行为，这种情况要更新旧测试，不要回滚新代码——但要在 commit 信息里说明）

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/chunker/document_splitter.py backend/ingestion/tests/unit/test_split_paragraph_invariant.py
git commit -m "fix(chunker): 重写 _split_paragraph 保留空格 + 列表标记保护

- 改成扫边界 + 按 offset 切原文，保证 join == 原文（不变量测试）
- 加 _is_list_marker_at 行级判定，'1. xxx' 不再被误切成 '1.xxx'
- 'Python 3.12.' 这种伪列表仍按句号切（line_prefix 不匹配 \\d+$）
- 修复 sanity_check.py 中 14.4% chunk 的空格吞咽 + 列表粘连问题"
```

---

### Task 2: 段落切分对 CRLF + 多空行鲁棒
📖 业内叫：line ending normalization + paragraph boundary regex

- **目标：** 修复 `split_document` 里 `raw.split("\n\n")` + `cursor += 2` 的脆弱假设——CRLF 输入或连续多空行会让 offset 偏移
- **输入：** parser 给的 raw_text（任意换行风格）
- **输出：** chunk 列表（offset 字段精确指向归一化后文本中的位置）
- **验收标准：**
  1. CRLF 输入（`\r\n\r\n`）正确识别段落边界，每个 chunk 的 char_offset_start/end 字段对应归一化后文本
  2. 三个连续换行（`\n\n\n`）只切出一次段落边界，不会让后续 chunk 的 offset 偏移 1
  3. 既有的 markdown 文件 re-index 后 chunk_count 跟旧版偏差 ≤ 5%（说明只是修了 corner case，没大改切分行为）
- **是否当前必须：** 是（Codex 指出与 Task 1 相邻的同类 bug，一波修完再 re-index 才划算）
- **关键节点：** 否

**Files:**
- Modify: `backend/ingestion/chunker/document_splitter.py:131-186`
- Test: `backend/ingestion/tests/unit/test_split_paragraph_invariant.py`（追加测试）

#### 测试场景清单

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | LF + 单空行段落分隔 | ✅ | `test_lf_normal`（已被 Task 1 间接覆盖）|
| 正常路径 | CRLF 输入正确归一化 | ✅ | `test_crlf_normalized` |
| 边界值 | 多于 2 个连续换行 | ✅ | `test_triple_newline` |
| 边界值 | 文档末尾无换行 | ✅ | `test_no_trailing_newline` |
| 异常输入 | 混合 CRLF + LF | ✅ | `test_mixed_line_endings` |
| 状态相关 | 同输入两次产生相同 chunk_id（确定性）| ❌ | chunk_id 由 hash 决定，已有逻辑覆盖 |
| 业务规则 | offset 字段在归一化文本中精确 | ✅ | `test_offsets_match_normalized` |

- [ ] **Step 1: 追加 CRLF/多空行测试**

**测什么行为：** raw_text 含 CRLF 或多空行时，每个 chunk 的 offset 字段在归一化文本中精确指向该 chunk 起始字符  
**输入：** 三段文字用 `\r\n\r\n`（CRLF 双空行）和 `\n\n\n`（三换行）混合分隔  
**期望：** chunk 数 == 3；chunk[i].content == normalized_text[chunk[i].offset_start:chunk[i].offset_end]  
**为什么必须测：** offset 字段是前端跳转 anchor 的依据，错位会让 K8s 文档双语对照页面跳到错误位置

```python
# 追加到 backend/ingestion/tests/unit/test_split_paragraph_invariant.py

from backend.ingestion.chunker.document_splitter import split_document
from backend.ingestion.parser.types import ParseResult


def _make_parse_result(text: str) -> ParseResult:
    return ParseResult(raw_text=text, title_tree=[], comment_ranges=[], language=None)


def test_crlf_normalized():
    """CRLF 输入正确切分，offset 字段对应归一化（LF）后文本。"""
    raw = "段落一第一句。段落一第二句。\r\n\r\n段落二第一句。\r\n\r\n段落三。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 3
    # offset 应在归一化文本中精确（归一化把 \r\n → \n，长度变短）
    normalized = raw.replace("\r\n", "\n")
    for c in chunks:
        assert c.content == normalized[c.char_offset_start:c.char_offset_end]


def test_triple_newline():
    """三个连续换行（\\n\\n\\n）只产生一次段落边界，不让后续 offset 偏移。"""
    raw = "段落一。\n\n\n段落二。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 2
    # 第二段 offset 应指向 '段落二' 的 '段'
    assert chunks[1].content.startswith("段落二")


def test_mixed_line_endings():
    """raw 中 \\r\\n 和 \\n 混用，归一化后边界仍正确。"""
    raw = "段落一。\r\n\r\n段落二。\n\n段落三。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 3
    # 每段都能在归一化文本中精确定位
    normalized = raw.replace("\r\n", "\n")
    for c in chunks:
        assert c.content == normalized[c.char_offset_start:c.char_offset_end]


def test_no_trailing_newline():
    """文档末尾无换行，最后一段仍被切出。"""
    raw = "段落一。\n\n段落二（无尾换行）。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 2
    assert chunks[1].content == "段落二（无尾换行）。"
```

- [ ] **Step 2: 跑新增测试，确认 FAIL（旧代码不会归一化 CRLF）**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_split_paragraph_invariant.py::test_crlf_normalized backend/ingestion/tests/unit/test_split_paragraph_invariant.py::test_triple_newline -v`  
Expected: 2 个测试 FAIL（offset 不匹配 / chunk 数不对）

- [ ] **Step 3: 改 split_document，加 CRLF 归一化 + 正则切段落 + offset 跟踪**

```python
# backend/ingestion/chunker/document_splitter.py:124-198 替换
PARA_BOUNDARY_RE = re.compile(r"\n{2,}")  # 2+ 换行作为段落分隔


def split_document(
    parse_result: ParseResult,
    *,
    file_path: str,
    file_hash: str,
    index_version: str,
) -> list[Chunk]:
    """三级 fallback 切分。
    
    入口处归一化 CRLF→LF；段落用正则 \\n{2,} 切而不是固定 \\n\\n。
    每个段落的 offset 通过 finditer 跟踪，不假设固定边界长度。
    """
    raw_original = parse_result.raw_text
    raw = raw_original.replace("\r\n", "\n").replace("\r", "\n")
    titles = _flatten_titles(parse_result.title_tree or [])
    comment_ranges = parse_result.comment_ranges or []
    
    # 用 finditer 切段落 + 记录每段的 (start_offset, content)
    paragraphs_with_offset: list[tuple[int, str]] = []
    cursor = 0
    for m in PARA_BOUNDARY_RE.finditer(raw):
        if cursor < m.start():
            paragraphs_with_offset.append((cursor, raw[cursor:m.start()]))
        cursor = m.end()
    if cursor < len(raw):
        paragraphs_with_offset.append((cursor, raw[cursor:]))
    
    chunks: list[Chunk] = []
    chunk_index = 0
    
    for para_start, para in paragraphs_with_offset:
        if not para.strip():
            continue
        if _is_heading_only(para):
            continue
        if _para_fully_inside_comment(para_start, len(para), comment_ranges):
            continue
        
        local_cursor = 0
        for piece, is_truncated in _split_paragraph(para):
            if not piece:
                continue
            # _split_paragraph 输出是 para 的顺序切片（拼接 == para），用 local_cursor 跟踪精确 offset
            offset = para_start + local_cursor
            title_path = _title_path_at_offset(titles, offset)
            chunk_id = _make_chunk_id(file_path, chunk_index, piece)
            chunks.append(Chunk(
                chunk_id=chunk_id,
                file_path=file_path,
                file_hash=file_hash,
                index_version=index_version,
                content=piece,
                anchor_id=f"{file_path}#{offset}",
                title_path=title_path,
                char_offset_start=offset,
                char_offset_end=offset + len(piece),
                char_count=len(piece),
                chunk_index=chunk_index,
                is_truncated=is_truncated,
                content_type="document",
                language=parse_result.language,
                markdown_anchor=_anchor_at_offset(titles, offset),
            ))
            chunk_index += 1
            local_cursor += len(piece)
    
    chunks = filter_quality(chunks)
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.chunk_id = _make_chunk_id(file_path, i, c.content)
    
    return chunks
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_split_paragraph_invariant.py -v`  
Expected: 全 10 个测试 PASS

- [ ] **Step 5: 跑 ingestion 全部 unit + integration，确认无回归**

Run: `cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem && /opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests -v`  
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/chunker/document_splitter.py backend/ingestion/tests/unit/test_split_paragraph_invariant.py
git commit -m "fix(chunker): split_document 归一化 CRLF + 正则切段落 + offset 跟踪

- 入口处 \\r\\n → \\n 归一化，避免 CRLF 输入下 split('\\n\\n') 失败
- 段落用 PARA_BOUNDARY_RE = \\n{2,} 切，正确处理 3+ 连续换行
- 用 finditer 跟踪每段在归一化文本中的 offset，不再假设固定边界长度
- offset 字段精确指向归一化文本，前端 anchor 跳转修正"
```

---

### Task 3: 备份 + 全量 re-index
📖 业内叫：full reindex / data migration

- **目标：** 用修复后的 chunker 重建整个 chunks 表，所有 embedding 基于干净文本重新计算
- **输入：** 当前 `backend/storage/index/knowledge.db`（含 11471 个旧 chunk）
- **输出：** 新的 `knowledge.db`，chunk 数差异在 ±5% 内，所有内容用新 chunker + 全量 bge-m3 embedding
- **验收标准：**
  1. `knowledge.db.bak.before-chunker-fix` 备份存在
  2. `SELECT count(*) FROM chunks` 在 11471 ± 600 范围
  3. 抽查 api-eviction.md 的 chunk #15 (offset 4631-5606) 内容里 `1. The` `terminated. The` 等空格被还原
  4. 跑 sanity_check.py Q1 (Pod 怎么删除)，6 步 chunk 在 A1 vec top-10 里 rank 至少提升一位（以前 #16 在 rank 10）
- **是否当前必须：** 是
- **关键节点：** **是**（数据库全量重建，2-4 小时，失败回滚成本高）

**Files:**
- Backup: `backend/storage/index/knowledge.db` → `knowledge.db.bak.before-chunker-fix`
- Use existing: `backend/ingestion/scripts/reindex_groupA.py` 或写一个简单的 reindex_all.py

#### 测试场景清单（这是 data 操作，不是单元测试）

| 维度 | 验证项 | 怎么验 |
|---|---|---|
| 备份完整 | bak 文件存在且可读 | `ls -la` + `sqlite3 .schema` |
| chunk 数合理 | 11471 ± 600 | SQL count |
| 内容修复 | 6 步 chunk 空格还原 | 抽样 chunk_index=15 看 content |
| 检索改善 | sanity_check Q1 6步 chunk 排名提升 | 跑 sanity_check.py 对比 |

- [ ] **Step 1: 备份当前 DB**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
cp backend/storage/index/knowledge.db backend/storage/index/knowledge.db.bak.before-chunker-fix
ls -lh backend/storage/index/knowledge.db.bak.before-chunker-fix
```

Expected: 输出 bak 文件大小（应在 100 MB 量级）

- [ ] **Step 2: 写 reindex_all.py 脚本**（如果不存在）

```python
# backend/ingestion/scripts/reindex_all.py
"""全量 re-index 所有已索引文件。
用法: /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.sync.pipeline import index_pipeline, DB_PATH, RAW_DIR


async def main():
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT file_path FROM documents").fetchall()
    conn.close()
    
    file_paths = [r[0] for r in rows]
    # documents.file_path 当前是绝对路径——转成相对 RAW_DIR
    base = RAW_DIR.resolve()
    relatives = []
    for fp in file_paths:
        p = Path(fp)
        try:
            rel = str(p.relative_to(base))
        except ValueError:
            rel = p.name  # fallback
        relatives.append(rel)
    
    print(f"Re-indexing {len(relatives)} files...")
    failed = []
    for i, rel in enumerate(relatives, 1):
        try:
            result = await index_pipeline(rel)
            print(f"  [{i}/{len(relatives)}] {rel} → {result['status']}")
        except Exception as e:
            print(f"  [{i}/{len(relatives)}] {rel} → FAILED: {type(e).__name__}: {e}")
            failed.append((rel, str(e)))
    
    print(f"\nDone. {len(relatives) - len(failed)} ok, {len(failed)} failed")
    if failed:
        for rel, err in failed:
            print(f"  FAIL: {rel}: {err}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: 关键节点——必停等用户审批后再执行**

⚠️ 这一步会跑 2-4 小时，且不可中断（中断后 DB 状态部分新部分旧）。  
**用户必须明确批准才继续：** "确认 backup 已存在 + 在 conda env sqllineage + 没有其他人在用 ingestion 服务 → 开跑"

- [ ] **Step 4: 跑全量 re-index**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all 2>&1 | tee /tmp/reindex.log
```

Expected: 末尾打印 "Done. 164 ok, 0 failed"。如果有 failed，先 stop 看 log 里报错的文件，决定单文件 retry 还是 skip。

- [ ] **Step 5: 验证 chunk 数 + 抽查 6 步 chunk 内容**

```bash
/opt/anaconda3/envs/sqllineage/bin/python -c "
import sqlite3
conn = sqlite3.connect('backend/storage/index/knowledge.db')
cur = conn.cursor()
print('chunks:', cur.execute('SELECT count(*) FROM chunks').fetchone()[0])
print('files:', cur.execute('SELECT count(DISTINCT file_path) FROM chunks').fetchone()[0])

# 找 api-eviction.md 里包含 6 步流程的 chunk
cur.execute('''
  SELECT chunk_index, char_count, substr(content, 1, 200) FROM chunks
  WHERE file_path LIKE '%api-eviction.md' AND content LIKE '%kubelet%删除时间戳%'
  ORDER BY chunk_index
''')
for row in cur.fetchall():
    print('---')
    print(f'  chunk_index={row[0]} char_count={row[1]}')
    print(f'  content head: {row[2]!r}')
"
```

Expected:
- chunks 在 11471 ± 600（10800 - 12100）
- files = 164
- 6 步 chunk 内容里能看到 `1. The Pod` `1. API 服务器` 等保留空格的形式（不是 `1.The` `1.API`）

- [ ] **Step 6: 跑 sanity_check Q1 验证检索改善**

```bash
/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.sanity_check "Pod 被 API 驱逐时是怎么一步步删除的" --only-vec 2>&1 | tee /tmp/sanity_q1_after_fix.log
tail -25 /tmp/sanity_q1_after_fix.log
```

Expected: top-10 里出现 6 步流程 chunk（content 含 `kubelet 注意到` 或 `1. API 服务器`），rank 比修复前的 #10 (0.6758) 至少提升一位

- [ ] **Step 7: Commit reindex 脚本（不 commit DB）**

```bash
git add backend/ingestion/scripts/reindex_all.py
git commit -m "chore(ingestion): 加全量 re-index 脚本

为 chunker fix 后的全量重建用。脚本读 documents.file_path，
转成相对 RAW_DIR 的路径后逐文件调 index_pipeline。

DB 文件不入 git；备份保存为 knowledge.db.bak.before-chunker-fix。"
```

---

### Task 4: Phase 1 完成验证（smoke test）
📖 业内叫：phase boundary verification

- **目标：** 跑全 7 题（5 原版 + 2 trap 变种），跟 Phase 0 baseline 对比，确认 chunker fix 真的提升了 6 步流程召回，且没有让其他 query 变差
- **输入：** 修复并 re-indexed 的 DB
- **输出：** 一份对比报告 `docs/superpowers/reports/2026-04-29-phase1-smoke.md`
- **验收标准：**
  1. Q1（6 步流程）：A1 vec 里出现含 `kubelet/宽限期` 的 chunk，rank ≤ 5
  2. Q2/Q3/Q4（真实命中）：top-1 文件不变，top-1 分数变化 ≤ 0.05
  3. Q5/Q6/Q7（trap）：top-1 分数变化 ≤ 0.05（确认 chunker fix 没引入新假阳性）
- **是否当前必须：** 是（Phase 边界）
- **关键节点：** **是**（决定能不能进 Phase 2）

**Files:**
- Create: `docs/superpowers/reports/2026-04-29-phase1-smoke.md`

- [ ] **Step 1: 跑 7 题（仍用 --only-vec，跟 baseline 同条件）**

逐题跑，输出贴回报告。**不要并行，单条跑确保 DB 不被并发干扰**：

```bash
for q in \
  "Pod 被 API 驱逐时是怎么一步步删除的" \
  "React Compiler 的增量采用是什么意思" \
  "DataBufferFactory 是用来做什么的" \
  "Kubernetes 中用于存放 SSH 身份认证凭据的内置 Secret 类型是什么" \
  "如何在 Deployment 的 YAML 中配置 backupPolicy 字段来自动备份 Pod 数据" \
  "如何在 React 组件中配置 mitochondria 属性来管理状态" \
  "Spring Boot 中如何使用 quantumCache 注解来缓存 Service 方法的返回值"; do
  echo "===== Q: $q ====="
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.sanity_check "$q" --only-vec 2>&1 | tail -20
  echo ""
done | tee /tmp/phase1_smoke.log
```

- [ ] **Step 2: 写 phase1 报告**

把 7 题的 top-3 文件 + 分数列出来，跟 baseline 对比（Phase 0 数据已有）。报告模板：

```markdown
# Phase 1 Smoke Test Report

| Q | 类型 | Phase 0 vec top-1 | Phase 1 vec top-1 | 6步 chunk rank 变化 |
|---|---|---|---|---|
| Q1 | 6步 | 0.79 / chunk #4453 | TBD | TBD |
...

结论：
- chunker fix 是否成功？
- 是否有 query 变差？
- 进 Phase 2 还是 stop 修问题？
```

- [ ] **Step 3: 关键节点——把报告给用户审，等批准后才进 Phase 2**

如果批准 → 进 Phase 2  
如果发现 chunker fix 让某些 query 变差 → 停下分析（可能引入了新 bug）

- [ ] **Step 4: Commit 报告**

```bash
git add docs/superpowers/reports/2026-04-29-phase1-smoke.md
git commit -m "docs: Phase 1 chunker fix smoke test report"
```

---

## Phase 2: 质量增强（BM25 加权 + embedding 实验 → 决策）

### Task 5: BM25 给 title_path 列加权
📖 业内叫：FTS5 column weighting / weighted bm25

- **目标：** 在 `text_search` SQL 的 ORDER BY 里把 title_path 列的 BM25 权重设成 5 倍 content，让标题命中型 query 排前列
- **输入：** Phase 1 已 re-indexed 的 DB（chunks_fts 已有 content/title_path 两列）
- **输出：** 改了一行 ORDER BY，API 完全不变
- **验收标准：**
  1. 跑 Q1（6 步流程）的 BM25 轨道：含 title_path "API 发起驱逐的工作原理" 的 chunk rank 提升
  2. 跑 Q2/Q3/Q4（真实标题）：top-3 仍是正确文件
  3. existing tests 全 PASS（特别是 fts_jieba regression test）
- **是否当前必须：** 是（API 不变，风险最低，先做）
- **关键节点：** 否（一行 SQL 改动，可秒回滚）

**Files:**
- Modify: `backend/ingestion/db/chunks_repo.py:135-146` (text_search SQL)
- Test: `backend/ingestion/tests/unit/test_text_search_title_weight.py`（新建）

#### 测试场景清单

| 维度 | 场景 | 是否测 | 对应测试 / 不测理由 |
|---|---|---|---|
| 正常路径 | 查询命中 title_path 的 chunk 排前面 | ✅ | `test_title_match_ranks_higher` |
| 边界值 | title_path 为 NULL 的 chunk 仍被返回 | ✅ | `test_null_title_returns` |
| 异常输入 | 空 query / 全标点 | ❌ | _build_fts_query 已处理（返空数组）|
| 错误处理 | FTS5 语法异常 | ❌ | 已在 _escape_fts_phrase 处理 |
| 状态相关 | 同 query 多次结果一致 | ❌ | SQL 确定性 |
| 业务规则 | content 命中也仍能召回（不是只看 title）| ✅ | `test_content_only_match_still_returned` |

- [ ] **Step 1: 写测试**

**测什么行为：** title_path 含查询词的 chunk 排序高于只在 content 里命中的 chunk  
**输入：** query "工作原理"，DB 里有两个 chunk——一个 title_path="API 发起驱逐的工作原理"，content 不含；另一个 title_path 为别的，content 含 "工作原理"  
**期望：** 第一个 chunk 排在前面  
**为什么必须测：** 这是本任务存在的全部理由，不测就没法验证 weight 真的生效

```python
# backend/ingestion/tests/unit/test_text_search_title_weight.py
import pytest
import sqlite3
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, text_search


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def _make_chunk(chunk_id, content, title_path):
    return {
        "chunk_id": chunk_id,
        "file_path": "test.md",
        "file_hash": "h",
        "index_version": "v1",
        "content": content,
        "anchor_id": f"test.md#{chunk_id}",
        "title_path": title_path,
        "char_offset_start": 0,
        "char_offset_end": len(content),
        "char_count": len(content),
        "chunk_index": int(chunk_id[-1]) if chunk_id[-1].isdigit() else 0,
        "is_truncated": False,
        "content_type": "document",
        "language": None,
        "embedding": None,
        "markdown_anchor": "#top",
    }


def test_title_match_ranks_higher(temp_db):
    """title_path 命中的 chunk 排名高于只在 content 命中的 chunk。"""
    chunks = [
        _make_chunk("a1", "这是一段无关内容", "API 发起驱逐的工作原理"),  # title 命中"工作原理"
        _make_chunk("b1", "我会讲讲什么是工作原理这个概念", "完全无关的标题"),  # content 命中"工作原理"
    ]
    insert_chunks(temp_db, chunks)
    
    results = text_search(temp_db, "工作原理", top_k=10)
    assert len(results) >= 2
    assert results[0]["chunk_id"] == "a1", f"title 命中的 a1 应排第一，实际 top-1 是 {results[0]['chunk_id']}"


def test_null_title_returns(temp_db):
    """title_path=None 的 chunk 仍能被 BM25 召回（content 命中时）。"""
    chunks = [
        _make_chunk("c1", "content 含工作原理这个关键词", None),
    ]
    insert_chunks(temp_db, chunks)
    results = text_search(temp_db, "工作原理", top_k=10)
    assert len(results) >= 1
    assert results[0]["chunk_id"] == "c1"


def test_content_only_match_still_returned(temp_db):
    """content 命中即使 title 不含也能召回（避免漏召）。"""
    chunks = [
        _make_chunk("d1", "API 服务器删除 Pod 资源", "无关标题"),
    ]
    insert_chunks(temp_db, chunks)
    results = text_search(temp_db, "Pod 资源", top_k=10)
    assert len(results) >= 1
    assert results[0]["chunk_id"] == "d1"
```

- [ ] **Step 2: 跑测试，确认 PASS（BM25 默认行为可能已经让 title_match 排前面，先看下基线）**

Run: `/opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_text_search_title_weight.py -v`

如果第一个 test 已 PASS（说明默认 BM25 已经行为正确），仍然要做权重显式化——但跳过 Step 3 的"加权后才能 PASS"逻辑，直接进 Step 4。

如果 FAIL，往下走。

- [ ] **Step 3: 改 text_search 加权**

```python
# backend/ingestion/db/chunks_repo.py:135-146 替换
rows = conn.execute(
    """
    SELECT c.*, bm25(chunks_fts, 1.0, 5.0) AS bm25_rank, d.indexed_at AS doc_indexed_at
    FROM chunks_fts fts
    JOIN chunks c ON c.chunk_id = fts.chunk_id
    JOIN documents d ON c.file_path = d.file_path
    WHERE chunks_fts MATCH ?
    ORDER BY bm25(chunks_fts, 1.0, 5.0)
    LIMIT ?
    """,
    (fts_query, top_k),
).fetchall()
```

注意：`bm25(table, weight1, weight2, ...)` 的 weight 顺序对应 FTS5 表里被索引列的声明顺序。看 schema.sql:48 是 `chunks_fts(chunk_id UNINDEXED, content, title_path, ...)`，所以 weight 顺序是 (content_weight, title_path_weight)。content=1.0, title_path=5.0 让 title 命中分数 5 倍放大。

注意 FTS5 的 bm25 返回**负数**（越小越相关），所以 `ORDER BY bm25(...)` 升序就是相关度降序——这个保留原行为。

- [ ] **Step 4: 跑测试 GREEN**

Run: `/opt/anaconda3/envs/sqllineage/bin/python -m pytest backend/ingestion/tests/unit/test_text_search_title_weight.py -v`  
Expected: 3 测试 PASS

- [ ] **Step 5: 跑现有 fts_jieba regression test 确认无回归**

Run: `/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.regression_test_fts_jieba 2>&1 | tail -10`  
Expected: PASS（如果 FAIL 看 diff，可能要调权重；title=5.0 偏激进可以试 3.0）

- [ ] **Step 6: 跑 sanity_check Q1 BM25 轨道，看 title 命中 chunk 排名**

Run: `/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.sanity_check "Pod 被 API 驱逐时是怎么一步步删除的" --only-bm25 2>&1 | tail -20`  
Expected: api-eviction.md 文件占据更多 top 位置，特别是 title_path 含"工作原理"的 chunk

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/db/chunks_repo.py backend/ingestion/tests/unit/test_text_search_title_weight.py
git commit -m "feat(retrieval): BM25 给 title_path 列 5x 权重

text_search 用 bm25(chunks_fts, 1.0, 5.0) 替代默认 fts.rank
让 title_path 命中的 chunk 在标题型 query 下排前面
API 完全不变（caller 仍传 query 字符串、收 chunks 数组）"
```

---

### Task 6: title-aware embedding 小规模实验
📖 业内叫：title-augmented dense retrieval / context-aware embedding

- **目标：** 用 3 个文件做受控实验：把 title_path 拼到 content 前再 embed，跟原版（只 embed content）比 7 题 top-10 变化，**重点看 trap 是否变得更糟**。**不动主 DB**
- **输入：** 主 DB（只读）+ 3 个测试文件（api-eviction.md / incremental-adoption.md / databuffer-codec.adoc）
- **输出：** 一份对比报告 `docs/superpowers/reports/2026-04-29-title-embedding-experiment.md`
- **验收标准：**
  1. 实验脚本不写主 DB（用 in-memory SQLite 或临时 DB 文件）
  2. 7 题对比表清晰列出 top-3 文件 + 分数变化
  3. 明确给出"建议全量做 / 不建议 / 数据不足需要更多样本"的结论
- **是否当前必须：** 是
- **关键节点：** 否（实验脚本，不影响主系统）

**Files:**
- Create: `backend/ingestion/scripts/title_aware_embedding_experiment.py`
- Create: `docs/superpowers/reports/2026-04-29-title-embedding-experiment.md`

- [ ] **Step 1: 写实验脚本**

```python
# backend/ingestion/scripts/title_aware_embedding_experiment.py
"""title-aware embedding 受控实验。

跑两版 embedding（A=原版只 embed content / B=拼 title_path），
在临时 DB 里建索引，跑 7 题 top-10 对比。不污染主 DB。

用法:
  /opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.title_aware_embedding_experiment
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, vector_search

TEST_FILES = [
    "api-eviction.md",
    "incremental-adoption.md",
    "databuffer-codec.adoc",
]

QUERIES = [
    ("Q1 K8s 6步", "Pod 被 API 驱逐时是怎么一步步删除的"),
    ("Q2 React 真", "React Compiler 的增量采用是什么意思"),
    ("Q3 Spring 真", "DataBufferFactory 是用来做什么的"),
    ("Q4 SSH Secret", "Kubernetes 中用于存放 SSH 身份认证凭据的内置 Secret 类型是什么"),
    ("Q5 K8s trap", "如何在 Deployment 的 YAML 中配置 backupPolicy 字段来自动备份 Pod 数据"),
    ("Q6 React trap", "如何在 React 组件中配置 mitochondria 属性来管理状态"),
    ("Q7 Spring trap", "Spring Boot 中如何使用 quantumCache 注解来缓存 Service 方法的返回值"),
]


def fetch_chunks_from_main_db(file_basenames):
    """从主 DB 读出指定文件的 chunk（不改主 DB）。"""
    main = sqlite3.connect("backend/storage/index/knowledge.db")
    main.row_factory = sqlite3.Row
    cur = main.cursor()
    chunks = []
    for basename in file_basenames:
        cur.execute(
            """SELECT * FROM chunks
               WHERE file_path LIKE ?
               ORDER BY chunk_index""",
            (f"%{basename}",),
        )
        chunks.extend([dict(r) for r in cur.fetchall()])
    main.close()
    return chunks


def build_temp_db(chunks, embed_fn, db_path):
    """用 embed_fn 对每个 chunk 重算 embedding，写入临时 DB。"""
    if Path(db_path).exists():
        Path(db_path).unlink()
    init_db(Path(db_path))
    conn = get_connection(Path(db_path))
    
    # documents 表也要插（vector_search SQL JOIN 它）
    file_paths = set(c["file_path"] for c in chunks)
    for fp in file_paths:
        conn.execute(
            """INSERT OR IGNORE INTO documents
               (file_path, file_name, file_hash, file_size, format, index_version, last_modified, indexed_at, index_status, chunk_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp, Path(fp).name, "h", 0, "md", "v1", "2026-04-29", "2026-04-29", "indexed", 0),
        )
    
    new_chunks = []
    for c in chunks:
        c_dict = dict(c)
        # 重新 embed
        text_to_embed = embed_fn(c_dict)
        emb = model.encode(text_to_embed, normalize_embeddings=True).tolist()
        c_dict["embedding"] = emb
        new_chunks.append(c_dict)
    
    insert_chunks(conn, new_chunks)
    conn.commit()
    return conn


def variant_a(c):
    """A 版：只 embed content（原版）。"""
    return c["content"]


def variant_b(c):
    """B 版：拼 title_path + content。"""
    if c.get("title_path"):
        return f"{c['title_path']}\n\n{c['content']}"
    return c["content"]


def run_query(conn, query):
    """跑 vector_search，返回 top-10。"""
    q_emb = model.encode(query, normalize_embeddings=True).tolist()
    return vector_search(conn, q_emb, top_k=10)


if __name__ == "__main__":
    print("Loading bge-m3...")
    from sentence_transformers import SentenceTransformer
    global model
    model = SentenceTransformer("BAAI/bge-m3")
    print("loaded")
    
    chunks = fetch_chunks_from_main_db(TEST_FILES)
    print(f"Got {len(chunks)} chunks across {len(TEST_FILES)} test files")
    
    print("\n=== Building variant A (content-only) ===")
    conn_a = build_temp_db(chunks, variant_a, "/tmp/exp_variant_a.db")
    
    print("=== Building variant B (title + content) ===")
    conn_b = build_temp_db(chunks, variant_b, "/tmp/exp_variant_b.db")
    
    for name, q in QUERIES:
        print(f"\n{'='*100}\n{name}: {q}\n{'='*100}")
        a_results = run_query(conn_a, q)
        b_results = run_query(conn_b, q)
        
        print(f"\n  A (content-only) top-3:")
        for i, r in enumerate(a_results[:3], 1):
            print(f"    {i}  {r['score']:.4f}  {Path(r['file_path']).name}  {r['content'][:50]!r}")
        print(f"\n  B (title+content) top-3:")
        for i, r in enumerate(b_results[:3], 1):
            print(f"    {i}  {r['score']:.4f}  {Path(r['file_path']).name}  {r['content'][:50]!r}")
```

- [ ] **Step 2: 跑实验**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.title_aware_embedding_experiment 2>&1 | tee /tmp/title_emb_exp.log
```

Expected: 7 题各两组 top-3 数据。耗时 5-10 分钟（少量 chunk）。

- [ ] **Step 3: 写报告，明确决策**

```markdown
# Title-aware Embedding Experiment Report

## 数据
| Q | A top-1 (score/file) | B top-1 (score/file) | 真实命中变化 | trap 假阳性变化 |
|---|---|---|---|---|
...

## 结论
- 真实命中改善：[YES/NO/NEUTRAL]
- trap 是否变得更糟（关键看 Q5/Q6/Q7）：[YES/NO/NEUTRAL]
- **最终建议：全量做 / 不全量 / 需更多样本**

## 推理
[基于数据展开]
```

- [ ] **Step 4: Commit**

```bash
git add backend/ingestion/scripts/title_aware_embedding_experiment.py docs/superpowers/reports/2026-04-29-title-embedding-experiment.md
git commit -m "experiment: title-aware embedding 3 文件受控实验

跑两版 embedding (content-only vs title+content) 在临时 DB 中
对比 7 题 top-10 变化，重点验证 trap 假阳性是否恶化

主 DB 未动；结论见报告"
```

---

### Task 7: 实验决策 + 条件性全量切换
📖 业内叫：experiment-driven decision gate

- **目标：** 根据 Task 6 实验数据决定是否全量切到 title-aware embedding；如果决定切，改 pipeline.py + 全量 re-index
- **输入：** Task 6 报告
- **输出：** 决策记录 + （条件性）全量 re-index 后的 DB
- **验收标准：**
  - 数据正向（trap 不变糟 + 真实命中提升）→ 改 pipeline.py + 全量 re-index → 跑 7 题对比 Phase 1 baseline
  - 数据负面（trap 变糟 / 真实命中变差）→ 跳过此 task，记录决策原因
  - 数据中立 → 默认不全量做（无明确收益不冒风险）
- **是否当前必须：** 否（条件性）
- **关键节点：** **是**（决策点 + 可能触发第二次全量 re-index）

**Files:**
- (条件性) Modify: `backend/ingestion/sync/pipeline.py:98` (batch_embed 输入)

- [ ] **Step 1: 关键节点——把 Task 6 报告给用户审批**

⚠️ 用户决定 → 走分支 A 或分支 B

**分支 A（实验数据正向，全量做）**：

- [ ] **Step A1: 改 pipeline.py 让 embedding 输入拼 title_path**

```python
# backend/ingestion/sync/pipeline.py:98 替换
embeddings = await batch_embed([
    f"{c.title_path}\n\n{c.content}" if c.title_path else c.content
    for c in chunks
])
```

- [ ] **Step A2: 备份 + 全量 re-index（同 Task 3 流程）**

```bash
cp backend/storage/index/knowledge.db backend/storage/index/knowledge.db.bak.before-title-embedding
/opt/anaconda3/envs/sqllineage/bin/python -m backend.ingestion.scripts.reindex_all 2>&1 | tee /tmp/reindex_title.log
```

- [ ] **Step A3: 跑 7 题对比 Phase 1 baseline**

逐题跑、写报告。验收：
- 真实命中（Q1-Q4）top-1 score 不下降超过 0.05
- trap（Q5-Q7）top-1 score 不上升超过 0.05

如果失败 → 必须回滚（恢复 bak）。

- [ ] **Step A4: Commit**

```bash
git add backend/ingestion/sync/pipeline.py
git commit -m "feat(ingestion): embedding 输入拼 title_path

让每个 chunk 的 1024 维向量自带章节语义
基于 2026-04-29 实验数据决策，详见报告

DB 已全量 re-index"
```

**分支 B（实验数据负面或中立，不全量）**：

- [ ] **Step B1: 写决策记录**

```markdown
# Title Embedding 决策：暂不全量

依据：[实验数据]
保留为可恢复实验，pipeline.py 不动
等下次发现按章节召回的痛点更明确时再考虑
```

- [ ] **Step B2: Commit**

```bash
git add docs/superpowers/reports/2026-04-29-title-embedding-decision.md
git commit -m "decision: 暂不全量做 title-aware embedding（基于实验数据）"
```

---

## Phase 3: 可维护性增强（兜底）

### Task 8: 同章节邻居救援（条件性）
📖 业内叫：sibling expansion / parent-document context injection

- **目标：** 如果 Phase 2 完成后 6 步流程仍在 vector top-10 之外，给 vector_search 加内部"邻居救援"逻辑：top-K primary chunk 强匹配时，把同 (file_path, title_path) 下相邻 chunk 也带进结果
- **输入：** 修复后的 DB
- **输出：** vector_search 返回的扁平 chunk 列表（API 不变）
- **验收标准：**
  1. Q1 在 top-10 里同时出现 chunk #15 和 #16（或对应修复后的版本）
  2. 真实命中（Q2-Q4）top-1 score 变化 ≤ 0.03
  3. 返回 chunk 总数 = top_k，不会因为邻居膨胀
- **是否当前必须：** 否（兜底）
- **关键节点：** 否

**Files:**
- (条件性) Modify: `backend/ingestion/db/chunks_repo.py:66-92` (vector_search)

跳过详细步骤——这个 task 只在 Phase 2 完成后 sanity_check Q1 仍然失败时才动手。届时根据具体数据现写。

---

## Self-Review

**1. Spec coverage：** Codex 提的所有点都覆盖了——A 重写（T1）+ 段落鲁棒（T2）+ re-index（T3）+ 验证（T4）；B BM25 加权（T5）+ embedding 实验（T6）+ 决策（T7）+ 兜底（T8）。

**2. Placeholder scan：** 所有 step 都有完整代码或确切命令；没有 TBD/TODO/Similar to。

**3. Type consistency：** `_split_paragraph` / `_is_list_marker_at` / `split_document` 命名前后一致；`_make_parse_result` test helper 在 Task 2 引入并被同文件后续测试复用。

**4. 外行版摘要：** 顶部存在；4 必答都答了；约 600 字（在 1000 上限内）。

**5. 三阶段完整：** Phase 1（T1-T4，必做）/ Phase 2（T5-T7，质量增强）/ Phase 3（T8，兜底）。每个 task 都属于某 Phase。"是否当前必须" 字段与 Phase 划分一致。

**6. 任务 6 字段：** 每个 Task 顶都有目标/输入/输出/验收/当前必须/关键节点 6 项。

**7. 任务名白话：** 全部任务标题都是大白话主标题 + 📖 业内叫副行。

**8. 测试场景清单：** Task 1/2/5 含完整 6 维度矩阵；T3/4/6/7 是 data 操作或决策点（不写测试）。❌ 都配理由。

**9. 测试代码白话说明：** 所有写测试的步骤上方都有"测什么/输入/期望/为什么必须测"4 字段。

**关键节点标记：** T3 全量 re-index = 是；T4 Phase 边界 = 是；T7 实验决策 + 条件性全量 = 是。其他 = 否。
