# Chunker Fix + Retrieval Enhancement 进度

## 进度总览（自动更新）
- 当前阶段：Phase 1（最小可跑）
- 进度：2/8 (25%)
- 卡点：无
- 最近更新：2026-04-29 Task 2 完成

---

## Task 1: 重写 _split_paragraph 保留空格 + 列表保护（完成）
- 时间：~10 分钟
- 做了什么：
  - 删除 `SENTENCE_SPLIT_RE = r"(?<=[。！？.!?])\s*"`（消耗空白的旧正则）和 `_hard_split` 辅助
  - 加 `SENTENCE_END_RE = r"[。！？.!?]"`（不消耗）+ `_is_list_marker_at` 行级判定
  - 重写 `_split_paragraph` 用 finditer 扫边界 + 贪心 substring 切原文
- 测试结果：
  - 新增 6 测试全过（test_join_equals_original / test_short_passthrough / test_long_split_by_sentence / test_list_marker_protection / test_no_boundary_hard_split / test_edge_inputs）
  - ingestion unit 测试 179 个全过，无回归
- 文件改动：
  - `backend/ingestion/chunker/document_splitter.py`（修改）
  - `backend/ingestion/tests/unit/test_split_paragraph_invariant.py`（新建）
- 验收对照：✅ 全部符合
  - join 拼回去 == 原文 ✅
  - `1. The Pod` 列表标记不被切成 `1.The Pod` ✅
  - `Python 3.12.` 伪列表仍按句号切 ✅
  - pytest 全绿 ✅
- 偏离 plan：无
- 提交：a6b5880
- 下一步：Task 2

## Task 2: split_document 归一化 CRLF + 段落正则切分 + offset 跟踪（完成）
- 时间：~10 分钟
- 做了什么：
  - 加 `PARA_BOUNDARY_RE = re.compile(r"\n{2,}")` 段落边界正则
  - split_document 入口加 `raw.replace("\r\n", "\n").replace("\r", "\n")` CRLF 归一化
  - 用 finditer 切段落 + 记录 (para_start, para)，不再 split('\n\n') + 固定 cursor+=2
  - 子片段 offset 用 local_cursor 累加（修复 plan 里发现的 raw.find 重复 piece bug）
- 测试结果：
  - 新增 4 测试全过（test_crlf_normalized / test_triple_newline / test_mixed_line_endings / test_no_trailing_newline）
  - ingestion 全套 192 测试全过（unit + integration），零回归
- 文件改动：
  - `backend/ingestion/chunker/document_splitter.py`（修改 split_document + 加 PARA_BOUNDARY_RE）
- 验收对照：✅ 全部符合
  - CRLF 输入正确切 ✅
  - 3+ 连续换行不让 offset 偏移 ✅
  - offset 在归一化文本中精确 ✅
- 偏离 plan：无
- 提交：b343ca8
- 下一步：Task 3（关键节点，必停等用户审）

## Task 3: 备份 + 全量 re-index（关键节点，待用户审批）
