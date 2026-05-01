# X1.5 严谨版实施进度

## 进度总览（自动更新）

- **当前阶段**：Phase 2 完成 → Phase 3 Task 18 (Codex review baseline)
- **进度**：17/19 (89%) — 单测 30/30 通过，集成测试 8/8 通过，baseline release gate PASS（X1.5 救活 +10 题）
- **卡点**：无
- **最近更新**：2026-05-01 Task 15 baseline 完成（X0=35/150 → X1.5=45/150，+10 题，0 搞砸）

## Plan 文件
[docs/superpowers/plans/2026-04-30-x15-rigorous-implementation.md](../plans/2026-04-30-x15-rigorous-implementation.md)

## Spec 文件
[docs/superpowers/specs/2026-04-30-x15-rigorous-design.md](../specs/2026-04-30-x15-rigorous-design.md)

## 执行模式
- 蜂群（subagent-driven-development）
- 每 task 派 fresh subagent + 两轮 review（spec + code quality）
- 白话双轨进度报告（对话 + 本文件）
- 5 种必停：出错 / 关键节点 / Phase 边界 / 验收存疑 / 依赖升级
- Phase 边界走 smoke test 三步

---

## Phase 1: 最小可跑

### Task 1: metadata 加 markdown_anchor + is_x15_truncated (完成)

- **时间**：~16:21（Subagent 估约 5 分钟）
- **做了什么**：在 `_row_to_metadata` 加 2 行：`is_x15_truncated`（默认 False）和 `markdown_anchor`（fallback `#top`）
- **测试结果**：curl `/chunks/{chunk_id}` 实测两字段都暴露，markdown_anchor 命中真实值 `#extract-a-component`（说明 fallback 逻辑也对）
- **文件改动**：
  - Modify: `backend/ingestion/api/routes_search.py` (+2)
- **验收对照**：✅ 全部符合
- **偏离 plan**：无
- **commit**：331f94b
- **下一步**：Task 2「写 raw 文件读取 + LRU 缓存」

### Task 2: 创建 x15.py + _read_raw_file LRU (完成)

- **做了什么**：新建 `backend/ingestion/api/x15.py` 模块，第一个函数 `_read_raw_file(file_path)` 读源 markdown + CRLF 归一化 + `@lru_cache(maxsize=200)` 装饰
- **测试结果**：手工跑 `_read_raw_file('add-react-to-an-existing-project.md')` 输出 8476 chars，CR 个数 0
- **文件改动**：
  - Create: `backend/ingestion/api/x15.py` (+24)
- **验收对照**：✅ 全部符合
- **偏离 plan**：plan 验证步骤用了 `kubernetes/api-eviction.md`，实际 DB file_path 平铺无子目录前缀（`api-eviction.md` 即可），subagent 用真实存在的文件验证
- **commit**：9375c7b
- **下一步**：Task 3-5 合并（追加 get_section_full_range / make_window / assign_group_key + group_results 三个独立 helper）

### Task 3-5 合并: get_section_full_range + make_window + grouping (完成)

- **做了什么**：往 x15.py 追加 3 个独立 helper（共 106 行）：
  - `get_section_full_range`：查同 section 全部 chunks 的 offset union（含未命中）+ 进程级缓存
  - `make_window`：居中截 3 档策略 + 边界回弹
  - `assign_group_key` + `group_results`：SECTION/SINGLE 分组 + 组内 score 降序
- **测试结果**：实测真实 section span=2361 字符 + 缓存命中；make_window 3 档 case 全 OK；分组逻辑 OK
- **文件改动**：
  - Modify: `backend/ingestion/api/x15.py` (+106)
- **验收对照**：✅ 全部符合
- **偏离 plan**：无（合并 3 个 task 1 个 commit，subagent 自驱完成）
- **commit**：837624f
- **下一步**：Task 6「_format_result_x15 主函数」（核心，单独跑）

### Task 6: _format_result_x15 主函数 (完成)

- **做了什么**：往 x15.py 追加 `_format_result_x15` 主函数（66 行）—— SECTION 合并 + SINGLE 退化 + 失败 fallback 三条路径
- **测试结果**：
  - Case A SECTION：原 chunk 199 字符 → X1.5 化 **1350 字符**（section 全量 + title_path 前缀工作正常）
  - Case B SINGLE：原 chunk content 不变 ✅
  - Case C fallback：file 不存在 → WARNING + 退回原 content ✅
- **文件改动**：
  - Modify: `backend/ingestion/api/x15.py` (+66)
- **验收对照**：✅ 全部符合
- **偏离 plan**：无
- **commit**：0288510
- **下一步**：Task 7「routes_search.py 入口改造 + feature flag」

### Task 7: routes_search 入口改造 + feature flag (完成)

- **做了什么**：改造 vector-search / text-search 入口走 X1.5 路径，加 INGESTION_X15_ENABLED env var flag，原 _format_result 改名为 _format_result_legacy（X0 备用）；by-id 接口保持原样
- **测试结果**：
  - **X1.5 端到端跑通**：30 个 chunk 收缩为 6 个 section group，top-3 全部含 title_path 前缀（如 "How to remove unnecessary Effects > Passing data to the parent"）
  - is_x15_truncated 既有 False（短 section）也有 True（长 section）—— 居中截算法触发正常
  - feature flag 切换：X0 路径 result=30（未收缩，X0 行为正常）
- **文件改动**：
  - Modify: `backend/ingestion/api/routes_search.py` (+57 -11)
- **验收对照**：✅ 全部符合
- **偏离 plan**：subagent 多 import 了 defaultdict（routes_search 实际不用，留到 Task 17 清理）
- **commit**：fa4f07f
- **下一步**：Task 8 痛点 query 烟雾测试（**Phase 1 边界必停**）
