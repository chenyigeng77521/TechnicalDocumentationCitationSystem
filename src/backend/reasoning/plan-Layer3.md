下面是**完全补全的 Layer 3（推理与引用层）设计方案**，严格按`requirment.md` 硬性约束，重点保证：

- **引用100%真实**

- **拒答准确**

- **零幻觉**

- **评测高分**

---

# 3. 推理与引用层（Layer 3）

> 👉 负责：**“答案是否正确 + 引用是否真实 + 是否拒答正确”**

---

## 3.1 系统架构（文字图）

```
Layer 2 输出（TopK chunks + score）
            │
            ▼
┌──────────────────────────────────────┐
│   Step 1: 可回答性判定（硬规则）       │
│   - rerank_score threshold           │
│   - chunk数量 / 覆盖度检查            │
└──────────────┬───────────────────────┘
               │ YES
               ▼
┌──────────────────────────────────────┐
│   Step 2: 上下文构建（Context Builder）│
│   - 拼接 chunk.content               │
│   - 保留 doc_path + anchor           │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│   Step 3: LLM 推理（严格约束 Prompt）  │
│   - 仅允许引用 context                │
│   - 强制结构化输出                   │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│   Step 4: 引用校验（强一致验证）       │
│   - answer ↔ chunk 语义匹配           │
│   - anchor 必须存在                   │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│   Step 5: 后处理                     │
│   - 去幻觉过滤                        │
│   - 统一格式输出                      │
└──────────────────────────────────────┘
```

---

## 3.2 数据处理流程（Query → Answer）

### Step 0：输入

```json
{
  "query": "...",
  "retrieved_chunks": [
    {
      "content": "...",
      "doc_path": "...",
      "anchor": "...",
      "score": 0.82
    }
  ]
}
```

---

### Step 1：可回答性判定（第一道 Gate）

```python
def is_answerable(chunks):
    if len(chunks) == 0:
        return False

    max_score = max(c.score for c in chunks)

    # 双阈值（关键）
    if max_score < 0.4:
        return False

    # 覆盖度（防误召）
    if len([c for c in chunks if c.score > 0.5]) == 0:
        return False

    return True
```

👉 不进入 LLM，直接拒答（避免幻觉）

---

### Step 2：Context 构建（严格可控）

```text
[Chunk 1]
doc: docs/react/xxx.md
anchor: #xxx
content: ...

[Chunk 2]
doc: ...
```

**关键规则：**

- ❌ 不做摘要

- ❌ 不拼接外部知识

- ✅ 原文注入

- ✅ 保留来源信息

---

### Step 3：LLM 推理（强约束 Prompt）

**Prompt（核心约束）**

```
你必须严格基于提供的 context 回答问题：

规则：
1. 只能使用 context 中的信息
2. 不允许使用外部知识
3. 如果无法从 context 得到答案，输出：REFUSE
4. 每一个结论必须能在 context 中找到依据
5. 不允许编造

输出格式：
{
  "answer": "...",
  "citations": [
    {"doc_path": "...", "anchor": "..."}
  ]
}
```

---

### Step 4：引用生成机制（100%正确）

#### 机制：**引用来源绑定 chunk**

LLM 不允许自由生成引用：

```python
allowed_citations = {
    (chunk.doc_path, chunk.anchor)
}
```

#### 校验逻辑：

```python
def validate_citations(output, chunks):
    valid_set = {(c.doc_path, c.anchor) for c in chunks}

    for cite in output["citations"]:
        if (cite["doc_path"], cite["anchor"]) not in valid_set:
            return False

    return True
```

👉 不合法 → 强制拒答

---

### Step 5：语义一致性校验（防“假引用”）

```python
def verify_answer_support(answer, cited_chunks):
    for chunk in cited_chunks:
        if semantic_similarity(answer, chunk.content) > 0.75:
            return True
    return False
```

👉 不满足 → 判定幻觉 → 拒答

---

### Step 6：最终输出

```json
{
  "answer": "...",
  "citations": [...],
  "is_refusal": false,
  "confidence": 0.87
}
```

---

## 3.3 拒答策略（核心得分点）

### 拒答触发条件（必须同时设计）

#### 条件 1：检索不足

```
max_score < 0.4
```

#### 条件 2：LLM 判定

```
输出 == REFUSE
```

#### 条件 3：引用校验失败

```
invalid citation
```

#### 条件 4：语义不一致

```
answer unsupported
```

---

### 统一拒答格式（必须严格一致）

```text
抱歉，我无法从提供的文档中找到答案。
```

---

## 3.4 防幻觉机制（关键）

### 1️⃣ 输入约束

- 仅传入检索 chunk

- 不允许 system 注入额外知识

---

### 2️⃣ Prompt 约束（强制 REFUSE）

---

### 3️⃣ 输出校验（三层）

| 层级  | 校验                |
| --- | ----------------- |
| 1   | citation 是否存在     |
| 2   | answer 是否来源 chunk |
| 3   | chunk 是否支持 answer |

---

### 4️⃣ Fail Fast 机制

```python
if any_check_failed:
    return REFUSAL
```

---

## 3.5 接口设计（Web 层调用）

---

### 3.5.1 单次请求接口

```
POST /api/qa
```

#### 入参

```json
{
  "id": "eval_qa_xxx",
  "query": "..."
}
```

#### 出参

```json
{
  "id": "eval_qa_xxx",
  "answer": "...",
  "citations": [
    {
      "doc_path": "...",
      "anchor": "..."
    }
  ],
  "is_refusal": false,
  "confidence": 0.91
}
```

---

### 3.5.2 批量请求接口（Public_Test_Set.jsonl）

```
POST /api/qa/batch
```

#### 核心流程

```
2. 核心流程（严格对齐你的要求）

接收 items（id + query）
 │
 ▼
多线程调用【单次请求接口 /api/qa】
 │
 ▼
复用单次接口的 query 处理逻辑
 │
 ▼
保持原始 id（不能改！）
 │
 ▼
写入 result_[id].jsonl
 │
 ▼
返回文件路径
```

#### 入参

```json
{
  "items": [
    {
      "id": "123",
      "query": "..."
    }
  ]
}
```

#### 出参

```json
{

  "status": "success",
  "file_path": "./eval/result_123.jsonl"
}
```

#### 文件格式result_[id].jsonl

> 文件格式每行有答和无答组成，如果对应对象的参数则值设置空，但是文件格式必须遵循

**有答响应**

```
{"id": "spring_trap_024", "domain": "Spring Framework", "question": "`@Scheduled` 注解的 `timeUnit` 参数应该如何使用？我想用 `TimeUnit.MINUTES` 来指定 `fixedDelay` 的单位。", "is_answerable": false, "answer": "根据当前文档无法回答该问题，`@Scheduled` 注解没有 `timeUnit` 参数。`fixedDelay` 等时间相关属性的单位固定为毫秒，时间单位无法通过参数更改。。", "gold_sources": [], "trap_type": "parameter_mismatch", "unanswerable_reason": "`@Scheduled` 注解没有 `timeUnit` 参数。`fixedDelay` 等时间相关属性的单位固定为毫秒，时间单位无法通过参数更改。", "difficulty": "medium"}
```

**无答响应**

```
{"id": "spring_trap_024", "domain": "Spring Framework", "question": "`@Scheduled` 注解的 `timeUnit` 参数应该如何使用？我想用 `TimeUnit.MINUTES` 来指定 `fixedDelay` 的单位。", "is_answerable": false, "answer": "根据当前文档无法回答该问题，`@Scheduled` 注解没有 `timeUnit` 参数。`fixedDelay` 等时间相关属性的单位固定为毫秒，时间单位无法通过参数更改。。", "gold_sources": [], "trap_type": "parameter_mismatch", "unanswerable_reason": "`@Scheduled` 注解没有 `timeUnit` 参数。`fixedDelay` 等时间相关属性的单位固定为毫秒，时间单位无法通过参数更改。", "difficulty": "medium"}
```

---

## 3.6 错误处理机制

| 错误类型         | 处理              |
| ------------ | --------------- |
| LLM 超时       | 重试 1 次 → 失败返回拒答 |
| citation 不合法 | 拒答              |
| 无 chunk      | 拒答              |
| JSON 解析失败    | fallback → 拒答   |
| rerank 失败    | fallback BM25   |

---

## 3.7 性能与延迟优化

### 并行化

```python
retrieve + rerank 并行
```

---

### Token 控制

- context ≤ 6k tokens

- 动态截断

---

### 批量优化

```python
batch size = 8
```
