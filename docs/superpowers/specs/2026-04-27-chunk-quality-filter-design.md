# chunker 垃圾内容过滤 设计文档

- **日期**：2026-04-27
- **来源**：海军联调测试报告 P0 问题 #2 — reranker 把全是点的 chunk `'..............................'` 评成 0.49 高分塞进 top-3
- **目标**：在 chunker 入库前加内容质量过滤，把"没意义"的 chunk 从源头清掉

---

## 外行版摘要

**1. 做什么？**
在我们 chunker 切完 chunks 之后、入库之前加一个"质量检查员"，扔掉 3 类没意义的 chunk：太短的 / 全是符号空白没语义的 / 同一文档里完全重复的。

**2. 为什么需要？**
联调测试时海军调 pipeline，bge-reranker 把 Oracle SQL Hints 里 `'..............................'`（一行 36 个点）评成 0.49 高分塞进 top-3 给张满柱。这是个真实可复现的 bug——chunker 没过滤无意义内容、reranker 又救不了。从源头扔掉这种 chunk 是治本。

**3. 大致怎么做？**
- 新建独立模块 `backend/ingestion/chunker/quality_filter.py`，单一职责
- 暴露 1 个函数 `filter_quality(chunks: list[Chunk]) -> list[Chunk]`
- 内部按顺序应用 3 条规则：①太短 ②有效字符占比低 ③同文档去重
- chunker 在 `split_document()` 末尾调一次 filter_quality，替换现有的简单长度过滤

**4. 主要风险？**
- min_chars 从 30 提到 50 可能误伤短中文 chunk → 用 is_truncated 标记的硬切 chunk 跳过此检查保护内容完整性
- 字母数字占比 < 30% 可能误伤含大量符号的代码 chunk → Unicode L+N 分类把中文/英文/数字都算"有效"，实测代码 chunk 字母占 60% 以上不会误伤
- 同文档去重可能误删合理重复（比如同份 docx 里同一段话被引用两次）→ 业界 95% RAG 默认做，跨文档不去重是边界

**spec 序章**：本 spec 对应 [`docs/superpowers/reports/2026-04-27-海军联调报告.md`](../reports/2026-04-27-海军联调报告.md) 第 6 段问题 #2 的最优解。

---

## 1. 设计决策（已与用户对齐）

| # | 决策点 | 选定方案 |
|---|---|---|
| 1 | 4 条业界标配规则 | min_chars=50 / Unicode L+N 字符占比 / 同文档去重 / 空 chunk strip 自动覆盖 |
| 2 | 模块组织 | **方案 B：独立 quality_filter.py 模块**（职责单一、易测、可复用 OCR/xlsx parser）|
| 3 | min_chars 阈值 | **50**（业界下限，从 30 提保守提升）|
| 4 | "有效字符"定义 | **Unicode L + N 分类**（中文/英文/数字/各国文字全算有效，标点空白不算）|
| 5 | 占比阈值 | **< 30%** 视为垃圾（极低误伤风险）|
| 6 | 去重范围 | **同 file_path 内**留第一条（不跨文档）|
| 7 | is_truncated 特殊处理 | **方案 B**：仅跳过"太短"检查；占比检查 + 去重照常 |
| 8 | `document_splitter.MIN_CHARS` 旧常量 | **删除**，由 `quality_filter.MIN_CHARS_QUALITY=50` 完全替代——单一来源避免阈值漂移 |

---

## 2. 架构

### 2.1 文件结构

```
新建：
  backend/ingestion/chunker/quality_filter.py        独立模块，单一职责

修改：
  backend/ingestion/chunker/document_splitter.py
    - 第 145 行简单过滤替换成调 filter_quality
    - 第 11 行 MIN_CHARS = 30 常量【删除】，由 quality_filter 替代

新增测试：
  backend/ingestion/tests/unit/test_quality_filter.py  8 个 unit test

修改测试（受 MIN_CHARS 删除 + 阈值 30 → 50 影响）：
  backend/ingestion/tests/unit/test_chunker.py
    - 第 6 行 import MIN_CHARS 删除（或改 import MIN_CHARS_QUALITY from quality_filter）
    - 第 84-85 行 fixture：47/46 chars 段落 → 提到 ≥ 50 字符（如改成 60 字符）
    - 第 106-110 行 test_min_chars_filter：改名为 test_quality_filter_drops_short，断言改用 MIN_CHARS_QUALITY
    - 加 1 个集成 test test_chunker_uses_quality_filter（mock 验证调用）
    - 加 1 个集成 test test_chunker_drops_low_quality_chunks（直接验 split_document 真行为，不 mock）
```

### 2.2 模块对外接口

```python
def filter_quality(chunks: list[Chunk]) -> list[Chunk]:
    """对 chunks 应用 3 条质量规则，返回保留的 chunks（顺序保持）。

    规则按顺序：
      ① 太短的丢（< MIN_CHARS_QUALITY），但 is_truncated=True 的留
      ② 字母数字占比 < ALPHANUM_RATIO_THRESHOLD 的丢
      ③ 同 file_path 内 content 完全相同的，留第一条
    """
```

### 2.3 内部 helpers（私有，单测拆开覆盖）

```python
_drop_too_short(chunks)              # 规则 ①
_drop_low_alphanumeric(chunks)       # 规则 ②
_dedup_within_document(chunks)       # 规则 ③
_alphanumeric_ratio(text: str) -> float   # 工具函数
```

---

## 3. 数据流

```
现状：document 进 chunker 5 步流水线

  原文 → ①按段落切 → ②跳标题段 → ③长段按句号/硬切 → ④过滤太短 → ⑤入库
                                                      ↑
                                                现状只有简单长度判断（MIN_CHARS=30）

改造：第 ④ 步换成 filter_quality

  原文 → ①按段落切 → ②跳标题段 → ③长段按句号/硬切 → ④filter_quality(chunks) → ⑤入库
                                                      ↑
                              ① 太短的丢（≥ 50）但 is_truncated 留
                              ② 有效字符占比 < 30% 的丢（is_truncated 也查）
                              ③ 同文档 content 重复的留第一条（is_truncated 也查）
```

### 3.1 在 document_splitter.py 的具体集成点

```python
# 当前第 145 行：
chunks = [c for c in chunks if c.char_count >= MIN_CHARS or c.is_truncated]

# 改成：
from backend.ingestion.chunker.quality_filter import filter_quality
chunks = filter_quality(chunks)
```

第 146-149 行的"重新编号 chunk_index + 重算 chunk_id"逻辑保留——必须在过滤之后做（chunks 删了编号要连续，chunk_id 含 index 也要重算）。

---

## 4. 规则细节

### 4.1 规则 ①：太短的丢（min_chars=50）

```python
MIN_CHARS_QUALITY = 50  # 业界下限，从原 MIN_CHARS=30 提升

def _drop_too_short(chunks: list[Chunk]) -> list[Chunk]:
    return [
        c for c in chunks
        if len(c.content) >= MIN_CHARS_QUALITY or c.is_truncated  # 统一用 len(c.content) 不用 c.char_count
    ]
```

📖 is_truncated=True 跳过此检查（is_truncated 是大段被硬切的产物，少了一片破坏完整性）。

### 4.2 规则 ②：有效字符占比 < 30%

"有效字符" = Unicode L 类（字母，含中文/英文/各国文字）+ N 类（数字）

```python
import unicodedata

ALPHANUM_RATIO_THRESHOLD = 0.30


def _alphanumeric_ratio(text: str) -> float:
    """有效字符（字母 + 数字 + 中文等）占总字符数的比例。"""
    if not text:
        return 0.0
    valid = sum(
        1 for ch in text
        if unicodedata.category(ch)[0] in ('L', 'N')
    )
    return valid / len(text)


def _drop_low_alphanumeric(chunks: list[Chunk]) -> list[Chunk]:
    return [
        c for c in chunks
        if _alphanumeric_ratio(c.content) >= ALPHANUM_RATIO_THRESHOLD
    ]
```

| 例子 | 有效字符占比 | 行为 |
|---|---|---|
| `"............................"` | 0% | ❌ 丢 |
| `"\t\t   \n\n  ,,,"` | 0% | ❌ 丢 |
| `"++++++ |||||| ----- ====="` | 0% | ❌ 丢 |
| `"啊"` | 100% | ✅ 留（但规则 ① 会丢，长度不够）|
| `"controller-manager 配置启动参数"` | ~75% | ✅ 留 |
| `"cat > /etc/kubernetes/conf <<EOF"` | ~62% | ✅ 留 |
| `"数据治理是企业核心实践"` | ~85% | ✅ 留 |

### 4.3 规则 ③：同文档同位置去重

```python
def _dedup_within_document(chunks: list[Chunk]) -> list[Chunk]:
    """同 file_path 内 content + char_offset_start 完全相同的留第一条；不跨文档。

    去重 key：(file_path, content, char_offset_start)
    - file_path 区分跨文档（合理引用不去重）
    - content   raw byte-for-byte 比较（不 strip / 不 normalize）
    - char_offset_start  保护硬切产物（同 content 不同 offset = 文档不同位置 = 可引用源不同）
    """
    seen: set[tuple[str, str, int]] = set()
    out = []
    for c in chunks:
        key = (c.file_path, c.content, c.char_offset_start)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
```

📖 **规范陈述（normative，必须遵守）**：
- **跨文档不去重**——多个文档可能合理引用同一段标准/法规
- 比较 **raw 字节** 不是 normalized——`"foo"` 和 `"foo "`（带尾空格）算不同 chunk
- **同 file_path + 同 content + 不同 char_offset_start 的 chunks must be preserved by design**——因为 chunk identity 是 citeable-span based（anchor_id = `file_path#offset`），同 content 不同 offset = 文档不同位置 = 不同的可引用源。任何 dedup 实现 must 包含 char_offset_start 在 key 里。

| 场景 | 旧 key (file_path, content) | 新 key (file_path, content, offset) | 行为 |
|---|---|---|---|
| 同文档真重复（chunker bug） | 同 → 去重 | 同（offset 也相同）→ 去重 | 一致 ✅ |
| 同文档硬切产物 | 同 → **误去重** ❌ | 不同（offset 不同）→ 留 | 修复 ✅ |
| 跨文档同内容 | 不同 → 留 | 不同 → 留 | 一致 ✅ |

### 4.4 主入口顺序

```python
def filter_quality(chunks: list[Chunk]) -> list[Chunk]:
    chunks = _drop_too_short(chunks)
    chunks = _drop_low_alphanumeric(chunks)
    chunks = _dedup_within_document(chunks)
    return chunks
```

📖 顺序固定：先短 → 再占比 → 再去重。这样 dedup 时数据池已经干净，计算量最小。

---

## 5. 错误处理

```python
filter_quality([])           # → [] （空列表返空，不报错）
filter_quality(None)         # → 抛 TypeError（按 Python 惯例不静默处理 None）
```

所有 helper 都是纯函数（无状态、无 IO、无异常），实现简单。

---

## 6. 测试矩阵（6 维度）

| 维度 | 该测的场景 | 是否测 | 对应测试 |
|---|---|---|---|
| 正常路径 | 全部合规的 chunks 全保留 | ✅ | test_keeps_normal_chunks |
| 边界值 | 50 字符 OK / 49 字符丢 / is_truncated 短 chunk 留 | ✅ | test_drops_chunk_below_min_chars + test_keeps_truncated_short_chunk |
| 异常输入 | 纯标点 / 纯空白 / 各种符号 / 中文短 | ✅ | test_drops_pure_punctuation / test_drops_whitespace_heavy / test_keeps_chinese_content |
| 错误处理 | 空 list 返空 | ✅ | test_empty_input_returns_empty |
| 错误处理 | None 输入抛 TypeError | ✅ | test_none_input_raises_typeerror |
| 状态相关 | 同 file_path 重复 / 跨 file_path 重复 | ✅ | test_dedups_within_document / test_keeps_cross_document_duplicates |
| 业务规则 | 含符号代码 chunk 不误伤 | ✅ | test_keeps_code_with_symbols |

**总计 9 个 unit 测试**，所有测试用真实 Chunk 对象，不 mock。

集成测试 2 个（在 test_chunker.py 加）：
- `test_chunker_uses_quality_filter` —— mock filter_quality，验证被调用（结构验证）
- `test_chunker_drops_low_quality_chunks` —— **不 mock**，直接给 split_document 一个含纯标点段落的 ParseResult 输入，断言 output 不含该 chunk（行为验证）

现有测试受 MIN_CHARS 删除影响要修复：
- `test_chunker.py:6` 删除 `MIN_CHARS` import（或改成 `from quality_filter import MIN_CHARS_QUALITY`）
- `test_chunker.py:84-85` fixture 字符数从 47/46 提到 ≥ 50（如统一改成 60）
- `test_chunker.py:106-110` test_min_chars_filter 改名 + 断言改用新常量

---

## 7. 验收标准（acceptance criteria）

📖 这一段对应 codex review 提的"明确 pass/fail + 默认值 + 可验证 guardrail"要求。

### 7.1 功能验收

| # | 验收项 | 通过条件 |
|---|---|---|
| 1 | 9 个 quality_filter unit 测试全 PASS | `pytest backend/ingestion/tests/unit/test_quality_filter.py -v` → 全 PASS |
| 2 | 集成测试 mock 验证 | `pytest backend/ingestion/tests/unit/test_chunker.py::test_chunker_uses_quality_filter -v` → PASS |
| 3 | 集成测试**行为**验证（关键）| `pytest backend/ingestion/tests/unit/test_chunker.py::test_chunker_drops_low_quality_chunks -v` → PASS |
| 4 | 现有测试不破坏 | `pytest backend/ingestion/tests/ -v` → 全 PASS（含 §2.1 列出的 test_chunker.py 3 处修复）|

📖 验收 #3（行为验证）是关键——光验"被调用"不够，必须验"调用后真扔掉了垃圾"。

### 7.2 数值 guardrail（执行后实测校准）

| 阈值 | 默认值 | 实测结果（联调库 1055 → 704 chunks）|
|---|---|---|
| MIN_CHARS_QUALITY | 50 | 联调库 chunks 减少 ~33%（不是早期估计的 5%——Kubernetes docx 真实重复多 + DataGovernance 短 Q&A 句被过滤都是预期）|
| ALPHANUM_RATIO_THRESHOLD | 0.30 | 真实代码 chunks 全保留（占比都 > 60%）|
| 同文档同位置去重 | 不可关 | Kubernetes docx 重复 chunks 大量被去重（-52%）；保留 23 条同 content 不同 offset 的合理引用片段 |

📖 早期 spec 写的"减少 < 5%" 是低估——执行时发现 Kubernetes 部署手册里有大量真实重复（不同章节多次引用同一配置命令），dedup 起作用合理减少 52%。这不是误伤，是 dedup 设计初衷。

### 7.3 集成验收（**手动**，可选，重建 DB 验证）

📖 这一步**不是 planning gate**——它要求 7 份联调测试文档 + 本地重建 DB 环境，不是所有开发者都稳定具备。建议在用户/陈一赓那边手动跑一次确认效果，不强制每次 CI 跑。

```bash
# Step 1: 删旧 DB（备份先）
mv backend/storage/index/knowledge.db backend/storage/index/knowledge.db.before-quality-filter

# Step 2: 启 ingestion，重新跑 7 文档索引
INGESTION_UPLOAD_ENABLED=true ./backend/ingestion/start.sh --bg
sleep 4
for f in "Oracle SQL Hints.pdf" "Kubernetes-v1.23.17部署指导手册.docx" \
         "DataGovernance_培训演讲稿与演示指南.docx" "System Alarm understanding.pptx" \
         "CMPAK F5 DNS requirement-V3.6.xlsx" "Copy Cmpak Data Governance Architecture.en.pptx" \
         "副本Cmpak Data Governance Architecture.pptx"; do
    curl -s -X POST http://localhost:3003/index -H "Content-Type: application/json" \
         -d "{\"file_path\": \"$f\"}"
    echo
done

# Step 3: 用 Python 直接调 _alphanumeric_ratio 精确校验（不用 SQL 启发式）
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate sqllineage
python <<'PY'
import sqlite3
from backend.ingestion.chunker.quality_filter import (
    _alphanumeric_ratio, MIN_CHARS_QUALITY, ALPHANUM_RATIO_THRESHOLD,
)

conn = sqlite3.connect("backend/storage/index/knowledge.db")
rows = conn.execute(
    "SELECT chunk_id, file_path, content, is_truncated FROM chunks"
).fetchall()
print(f"total chunks: {len(rows)}")

# 验 1：太短 chunk（is_truncated=False 时）= 0
short_bad = [
    r for r in rows
    if len(r[2]) < MIN_CHARS_QUALITY and not r[3]
]
print(f"violations 太短: {len(short_bad)} (expected 0)")

# 验 2：低字母数字占比 chunk = 0
low_alpha = [
    r for r in rows
    if _alphanumeric_ratio(r[2]) < ALPHANUM_RATIO_THRESHOLD
]
print(f"violations 低占比: {len(low_alpha)} (expected 0)")

# 验 3：同 file_path 内 content 重复 = 0
seen = set()
dup = []
for cid, fp, content, _ in rows:
    if (fp, content) in seen:
        dup.append((cid, fp))
    seen.add((fp, content))
print(f"violations 同文档重复: {len(dup)} (expected 0)")
PY
```

📖 用 Python 直接调真实的 `_alphanumeric_ratio` + `MIN_CHARS_QUALITY` 常量做校验，跟规则定义 100% 一致（不像 SQL 启发式查询有近似误差）。

---

## 8. Out of Scope（明确不做）

- ❌ 重复 token 占比检测（"abc abc abc abc" 刷屏）—— 大规模训练数据集才做
- ❌ 跨文档近似去重（MinHash + LSH）—— 我们 1k chunks 不需要
- ❌ 语言检测过滤 —— 多语言友好，不限制
- ❌ 阈值运行时可配置 —— 直接硬编码常量，未来需要再说
- ❌ 删除已入库的旧垃圾 chunks —— 由集成验收时重建 DB 实现，不写迁移脚本

如果未来需要，单开新 spec。

---

## 9. 集成顺序（实现时）

1. 写 `quality_filter.py` 框架（常量 + 4 个函数签名）
2. 写 `test_quality_filter.py` 第一条 test_keeps_normal_chunks + TDD 走通
3. 逐条实现 + 测试（_drop_too_short → _drop_low_alphanumeric → _dedup_within_document）
4. 实现 main `filter_quality()` 串起来
5. 改 `document_splitter.py`：
   - 第 145 行替换成 `chunks = filter_quality(chunks)`
   - **删除**第 11 行 `MIN_CHARS = 30` 常量
6. 修现有 `test_chunker.py`（受 MIN_CHARS 删除影响 3 处）：
   - 第 6 行 import MIN_CHARS 删除
   - 第 84-85 行 fixture 47/46 → 60 字符
   - 第 106-110 行 test_min_chars_filter 改名 + 断言用 MIN_CHARS_QUALITY
7. 加 2 个集成测试到 `test_chunker.py`：
   - `test_chunker_uses_quality_filter`（mock 验证）
   - `test_chunker_drops_low_quality_chunks`（行为验证）
8. 跑 `pytest backend/ingestion/tests/ -v` 全绿——**关键命令**：
   - `pytest backend/ingestion/tests/unit/test_quality_filter.py -v`（8 个新 PASS）
   - `pytest backend/ingestion/tests/unit/test_chunker.py -v`（含 2 个新集成测试 + 修复后的现有测试 PASS）
   - 不再核对总测试数，只核对上面两个命令全绿
9. 重建 DB 集成验收（按 §7.3 用 Python 精确校验）
10. 提交 commits

---

## 10. 自检 checklist (spec self-review)

- ✅ Placeholder scan：无 TBD / TODO
- ✅ 内部一致性：决策 1-7 / §3 / §4 / §6 / §7 互相对得上
- ✅ 范围检查：单一 plan 可实现，没跨多模块
- ✅ 模糊性检查：每条规则都给具体阈值 + 真实例子
- ✅ 默认值 + guardrail：§7.2 列了每个数值的默认值 + 怎么验它没误伤
- ✅ 错误处理：§5 简单清晰
- ✅ 与 codex review 历次反馈一致：明确 pass/fail / 数值 heuristic 有验证边界 / acceptance criteria 具体可测
- ✅ codex review 第 1 轮已修：
  - §1 决策 8 明确 `document_splitter.MIN_CHARS` 删除契约
  - §2.1 列出现有 test_chunker.py 受影响的 3 处具体行号 + 修改方法
  - §6 加第 2 个集成测试 `test_chunker_drops_low_quality_chunks`（不 mock，直接验 split_document 行为）
  - §7.3 SQL 启发式校验改成 Python 直接调 `_alphanumeric_ratio`（跟规则 100% 一致）
- ✅ codex review 第 2 轮已修：
  - §7.1 验收清单显式列两个集成测试（`test_chunker_uses_quality_filter` + `test_chunker_drops_low_quality_chunks`）
  - §7.3 标成"手动可选验收"，不是 planning gate
  - §9 集成顺序去掉错算的"应 90 PASS"，改成 "关键命令全绿" 不数总数
- ✅ codex cross-debug 架构修复（执行阶段发现）：
  - §4.3 dedup key 从 `(file_path, content)` 改为 `(file_path, content, char_offset_start)`
  - 起因：执行 T2.2 时现有测试 `test_single_giant_sentence_triggers_hard_truncate` 失败——硬切产物 content byte-for-byte 相同被误去重
  - codex 指出："content-only dedup" 跟 "chunk as citeable source span" 设计理念冲突，加 offset 是治本
