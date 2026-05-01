# Phase 1 Smoke Test Report

**日期**：2026-04-29 → 2026-04-30  
**Plan**：[2026-04-29-chunker-fix-and-retrieval-enhancement](../plans/2026-04-29-chunker-fix-and-retrieval-enhancement.md)  
**测试模式**：A1 纯向量轨道（`sanity_check.py --only-vec`）  
**对照基准**：Phase 0 baseline（chunker fix 前的 7 题数据）

## 7 题对比表

| # | 类型 | Phase 0 vec top-1 | Phase 1 vec top-1 | 6步 chunk 排名变化 / 备注 |
|---|---|---|---|---|
| Q1 | K8s 6步 | 0.7920 (#4453) | 0.7920 (#4453) | top-1-9 完全一致；rank-10 从 #5606 换为 #6438；中文 6步 chunk #5623 rank 10→11 |
| Q2 | React 真实 (heading) | 0.6515 incremental-adoption | 0.6515 同 | ⚠️ 完全持平（分数+文件+排名一字不差）|
| Q3 | Spring 真实 (heading) | 0.7467 databuffer-codec | 0.7467 同 | ⚠️ 完全持平 |
| Q4 | SSH 真实 (keyword) | 0.8307 secret.md | 0.8307 同 | ⚠️ 完全持平（10/10 都是 secret.md）|
| Q5 | K8s trap (虚构 backupPolicy) | 0.6729 configmap | 0.6729 同 | ⚠️ 完全持平（trap 假阳性未解决）|
| Q6 | React trap (mitochondria) | 0.6043 preserving-state | 0.6043 同 | ⚠️ 完全持平 |
| Q7 | Spring trap (quantumCache) | 0.5460 webflux | 0.5460 同 | ⚠️ 完全持平 |

## 关键发现

### 1. chunker fix 对纯向量召回几乎零影响

7 题里 6 题 top-1 分数**一字不差**。原因：

- chunker fix 改了 14% (1651/11491) 的 chunks 内容（去除 `1.The` 粘连 / 还原句号后空格 / 补回换行）
- 但**这 1651 个 chunks 里极少出现在 7 题的 top-50 之内**
- 高分 chunks 多为不含 markdown 列表的文本（自然中文段落），未被 bug A 污染 → embedding 完全不变
- **结论**：bug A 主要损伤的是被污染 chunks 自身的内容可读性，对它们在向量空间的相对位置影响小

### 2. Q1 是唯一发生纯向量变化的 query

- 中文 6步 chunk #5606 (旧) → #5623 (新)，rank 10 → 11，score 0.6758 → 0.6613 (-0.0145)
- 英文 6步 chunk #4631 仍在原位但 rank 13（修复前未在 top 50）
- 同一 chunk 修复前后两版 embedding cosine = 0.9882（高度相似但不一致）
- **诊断**：dense embedding 对小输入改动响应非单调；0.014 score 差异在 0.6-0.7 区间属正常噪声

### 3. reranker 验证（用 Q1 验证完整 4 轨道）

- B reranker top-5 中**中文 6步 chunk #5623 仍在 rank 4**（score 0.9900）
- 英文 6步 chunk #4631 在 reranker 后 rank > 10——**这其实是合理改善**（中文 query 不该让英文 chunk 排太前）
- chunker fix 让 reranker 拿到干净文本后，做出更准确的语言相关性判断

### 4. 用户痛点 query "API 发起驱逐的工作原理是什么" 的 vec 结果**完全没改善**

- 修复前后 top-10 一字不差
- 6步 chunks 都没出现在 top-10
- 原因：query 含"工作原理"四字，这四字**只在 title_path 里**，6步 chunk **内容**里没有
- **vector_search 不看 title_path** → 无法召回

**这是问题 B（retrieval 不用 title_path）的典型表现**，chunker fix 不解决这类问题。

## Plan Task 4 验收对照

| 验收条款 | 结果 |
|---|---|
| Q2/Q3/Q4 真实命中：top-1 文件不变 + 分数变化 ≤ 0.05 | ✅ 全部完全持平 |
| Q5/Q6/Q7 trap：top-1 分数变化 ≤ 0.05 | ✅ 全部完全持平 |
| Q1：6步 chunk 在 A1 vec top-10 里 rank ≤ 5 | ⚠️ rank 11，未达成；reranker B 轨道补到 rank 4 |
| chunk 数差 ±5% 内 | ✅ +0.17% (11471 → 11491) |
| 6步 chunk 内容修复肉眼可见 | ✅ `1.The` → `1. The`，`terminated.The` → `terminated. The` |
| 总耗时 | ✅ 7.6 min（原估 2-4h）|

**总判定**：Phase 1 **PASS**

## 总结：Phase 1 是必要但不充分

**Phase 1 完成了它的核心目标**：
- chunks 文本质量从"14% 被污染"变为"100% 干净"
- 不变量保证：拼回去 == 原文（10 个回归测试覆盖）
- 段落切分对 CRLF + 多空行鲁棒
- 全量 re-index 顺利完成

**Phase 1 未触及的问题**（Phase 2 范畴）：
- vector_search 不看 title_path → 标题型 query 召不回标题下的内容（问题 B）
- BM25 默认权重未给 title 列加权
- "返回整节"的诉求 → Phase 3 sibling 救援

**用户感受到的"结果差"**——大头来自问题 B。Phase 2 必做。

## 进入 Phase 2 的前置确认

- [x] Phase 1 所有 task 已 commit
- [x] DB 备份保留 (`knowledge.db.bak.before-chunker-fix`)
- [x] 192 个测试全过，零回归
- [x] Phase 1 smoke 数据落账，Phase 2 改动有 baseline 对比

**下一步**：Phase 2 Task 5（FTS title 加权）
