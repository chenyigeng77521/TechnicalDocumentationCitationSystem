# Title-aware Embedding Experiment Report

**日期**：2026-04-30  
**Plan**：[2026-04-29 chunker-fix-and-retrieval-enhancement](../plans/2026-04-29-chunker-fix-and-retrieval-enhancement.md) Task 6  
**实验脚本**：[backend/ingestion/scripts/title_aware_embedding_experiment.py](../../backend/ingestion/scripts/title_aware_embedding_experiment.py)  
**完整输出**：`/tmp/title_emb_exp.log`

## 实验设计

**对照**：
- A 原版：embedding 输入 = chunk content（现状）
- B 实验：embedding 输入 = `{title_path}\n\n{content}`（拼标题）

**测试样本**：3 个文件 88 chunks
- api-eviction.md (K8s)
- incremental-adoption.md (React)
- databuffer-codec.adoc (Spring)

**测试 query**：7 题（4 真实 + 3 trap）

**关键约束**：临时 DB（`/tmp/exp_variant_a.db`、`/tmp/exp_variant_b.db`），不动主 DB

## 7 题数据

| Q | 类型 | A top-1 score | B top-1 score | Δ | top-1 chunk 同 | 备注 |
|---|---|---|---|---|---|---|
| Q1 | K8s 6步 | 0.7920 | 0.7813 | **-0.0108** | ✅ | 同 chunk #4453 |
| Q2 | React 真 | 0.6515 | 0.6856 | **+0.0341** | ✅ | 同 chunk，分数提升 |
| Q3 | Spring 真 | 0.7467 | 0.6991 | **-0.0476** | ✅ | 同 chunk，分数下降 |
| Q4 | SSH Secret | 0.4318 | 0.4296 | -0.0023 | ❌ | **secret.md 不在 corpus，无效样本** |
| Q5 | K8s trap | 0.5787 | 0.5787 | **0.0000** | ✅ | trap 完全持平 ✅ |
| Q6 | React trap | 0.4993 | 0.4950 | -0.0042 | ❌ | trap 微降 |
| Q7 | Spring trap | 0.4950 | 0.4947 | -0.0003 | ❌ | trap 持平 |

## 关键观察

### ① trap 没变糟 ✅

之前担心"拼 title 让 K8s 区域语义更密 → trap 假阳性升高"——**实验数据反驳了这个担忧**：

- Q5 K8s trap：完全 0.0000 持平
- Q6 React trap：-0.0042（轻微改善）
- Q7 Spring trap：-0.0003 持平

**结论**：title-aware embedding 不会恶化 trap 假阳性。

### ② 真实命中**改善不一致**

3 个真实 query（去掉 corpus 外的 Q4）：

- Q1: **-0.0108**（轻微下降）
- Q2: **+0.0341**（明显改善）
- Q3: **-0.0476**（明显下降）

**净效果**：+0.0341 - 0.0108 - 0.0476 = **-0.0243**（净负面）

3 题里 1 升 2 降——**没有一致性的改善信号**。

### ③ 为什么 Q3 大幅下降？

Q3 query "DataBufferFactory 是用来做什么的"，最相关 chunk 的 title_path = `"Data Buffers and Codecs > \`DataBufferFactory\`..."`。

拼到 content 前：
```
Data Buffers and Codecs > `DataBufferFactory` ...

`DataBufferFactory` is used to create data buffers in one of...
```

英文 query "DataBufferFactory" 匹配的是 `DataBufferFactory` 一个具体词。原版 content 里这个词高频出现 → 高分。拼 title 后 content 占比变小（被 title 稀释）→ 总体语义偏向"标题概念" → 跟具体词的余弦距离反而增大。

**这印证了我们之前讨论的风险**：title 长 + content 短时，title 主导 → 精准查询变差。

## 决策

按 plan Task 7 的决策树：
- ✅ trap 不变糟（先决条件满足）
- ❌ 真实命中**没有一致改善**（净负面 -0.024）

**结论：不建议全量做 title-aware embedding**

**理由**：
1. **数据中立偏负**——3 题 1 升 2 降，净 -0.024，没有明确收益
2. **风险点已验证**：Q3 那种"具体词 query"会被 title 稀释，问题真实存在
3. **第二次全量 re-index 成本高**（7-30 min + DB 备份切换 + 又一次单向门）
4. **替代方案已生效**：Task 5 的 BM25 title 5x 加权**已经把"标题型 query"那一路打通了**——同样的功能不冒 embedding 全量改动的风险
5. **将来可以再试**：试不同的连接符（如 "Section: {title}\n\n{content}"）、不同权重的 mix（如 0.7 * content_emb + 0.3 * title_emb），但这些变体都需要更多样本验证，超出本次 plan 范围

## 给 Phase 2 收尾的建议

Phase 2 完成情况：
- ✅ Task 5（BM25 title 加权）—— **完成 + 实测改善**
- ❌ Task 6/7（title-aware embedding）—— **决定不全量做，跳过 Task 7**

**Phase 2 实际产出**：BM25 这一路加了结构感知；vector 这一路保持原样（避免引入不一致）。

**Phase 2 核心问题**——"按标题问 query 召不回标题下内容"——的解决方案：

> 标题命中型 query：BM25 path 直接召回（Task 5）→ RRF 融合让向量+BM25 共同决定 → 海军 reranker 二次排序

不依赖 vector path 单独解决问题 B，而是靠**两路融合**互补，避免 embedding 大改动的不确定性。
