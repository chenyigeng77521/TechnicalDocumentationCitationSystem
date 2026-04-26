# Question Filter 升级说明

## 升级日期
2026-04-26

## 主要变更

### 1. 模型升级
- **原模型**: `uer/structbert-base-chinese` (已废弃)
- **新模型**: `hfl/chinese-roberta-wwm-ext` (中文 RoBERTa)
- **状态**: 模型加载失败时自动降级为规则匹配

### 2. 多级过滤策略

```
问题输入
    ↓
┌─────────────────────────────────┐
│ 第一级：规则检查                │
│ - 空问题检测                    │
│ - 无中文字符检测                │
│ - 纯标点检测                    │
└─────────────────────────────────┘
    ↓ (未匹配)
┌─────────────────────────────────┐
│ 第二级：关键词匹配              │
│ - 闲聊类 (CHAT)                 │
│ - 自我介绍 (SELF_INRO)          │
│ - 实时类 (REALTIME)             │
└─────────────────────────────────┘
    ↓ (未匹配)
┌─────────────────────────────────┐
│ 第三级：ML 模型分类              │
│ - RoBERTa 6 分类模型              │
│ - 置信度 < 0.6 标记需二次过滤    │
└─────────────────────────────────┘
    ↓ (置信度低 or 无模型)
┌─────────────────────────────────┐
│ 第四级：上下文记忆层 (预留)     │
│ - 分析对话历史                  │
│ - 二次判断问题有效性            │
└─────────────────────────────────┘
    ↓
最终分类结果
```

### 3. 分类标签（6 分类）

| 标签 | 说明 | 示例 |
|------|------|------|
| **VALID** | 有效问题 | "如何申请年假？" |
| **INVALID** | 无效问题 | "" (空), "asdfgh" (乱码) |
| **REALTIME** | 实时类问题 | "今天天气怎么样？" |
| **CHAT** | 友好闲聊 | "你好", "吃了吗" |
| **OFFTOPIC** | 偏离主题 | "帮我买股票" |
| **SELF_INRO** | 自我介绍 | "你是谁？" |

### 4. API 接口变更

#### `/api/filter` (POST)
**新增字段**:
```json
{
    "question": "字符串",
    "conversation_history": [  // 新增：可选
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "您好！"}
    ]
}
```

**新增响应字段**:
```json
{
    "need_context_check": true,   // 新增：是否需要上下文记忆层
    "final_category": "VALID"     // 新增：上下文记忆层最终分类
}
```

#### `/api/filter/with-context` (POST) - 新增
**用途**: 上下文记忆层二次过滤接口

**状态**: 预留接口，需配置 `CONTEXT_MEMORY_ENABLED=true` 启用

### 5. 上下文记忆层配置

在 `.env` 文件中添加:
```env
# 上下文记忆层服务地址
CONTEXT_MEMORY_URL=http://localhost:3006

# 是否启用上下文记忆层
CONTEXT_MEMORY_ENABLED=false

# 调用超时时间 (毫秒)
CONTEXT_MEMORY_TIMEOUT=5000
```

### 6. 代码结构

```
backend/firstlayer/question_filter/
├── app.py                 # FastAPI 应用入口
├── config.py              # 配置文件 (新增 CONTEXT_MEMORY_* 配置)
├── classifier.py          # 问题分类器 (重写，支持多级过滤)
└── routes/
    └── classify.py        # API 路由 (新增 /with-context 接口)
```

## 使用示例

### 基本过滤
```bash
curl -X POST http://localhost:3005/api/filter \
  -H "Content-Type: application/json" \
  -d '{"question": "如何申请年假？"}'
```

### 带上下文的过滤
```bash
curl -X POST http://localhost:3005/api/filter \
  -H "Content-Type: application/json" \
  -d '{
    "question": "它多少钱？",
    "conversation_history": [
      {"role": "user", "text": "我想了解 iPhone 15"},
      {"role": "assistant", "text": "iPhone 15 是我们的最新款手机..."}
    ]
  }'
```

### 上下文记忆层过滤（预留）
```bash
curl -X POST http://localhost:3005/api/filter/with-context \
  -H "Content-Type: application/json" \
  -d '{
    "question": "它多少钱？",
    "conversation_history": [...]
  }'
```

## 上下文记忆层开发指南（待实现）

### 服务要求
- **端口**: 3006 (建议)
- **框架**: FastAPI
- **接口**: `POST /api/filter-with-context`

### 请求格式
```json
{
    "question": "它多少钱？",
    "conversation_history": [
        {"role": "user", "text": "我想了解 iPhone 15"},
        {"role": "assistant", "text": "iPhone 15 是我们的最新款手机..."}
    ]
}
```

### 响应格式
```json
{
    "category": "VALID",
    "confidence": 0.85,
    "reason": "结合上下文，'它'指代'iPhone 15'，是有效问题"
}
```

### 实现思路
1. 分析对话历史，识别指代关系
2. 将问题与上下文合并，重新分类
3. 返回最终分类结果

## 测试命令

```bash
# 测试基本过滤
curl http://localhost:3005/api/filter/types

# 测试闲聊识别
curl -X POST http://localhost:3005/api/filter \
  -H "Content-Type: application/json" \
  -d '{"question": "你好"}'

# 测试实时类问题
curl -X POST http://localhost:3005/api/filter \
  -H "Content-Type: application/json" \
  -d '{"question": "今天天气怎么样？"}'

# 测试有效问题
curl -X POST http://localhost:3005/api/filter \
  -H "Content-Type: application/json" \
  -d '{"question": "如何申请年假？"}'
```

## 注意事项

1. **PyTorch 版本**: 当前 PyTorch 2.2.2 无法安全加载 ML 模型，自动降级为规则匹配
2. **上下文记忆层**: 目前为预留接口，需后续开发
3. **置信度阈值**: ML 模型置信度 < 0.6 时会标记需要上下文记忆层检查
4. **规则优先**: 规则和关键词匹配优先级高于 ML 模型，确保快速过滤

## 后续计划

- [ ] 开发上下文记忆层服务
- [ ] 升级 PyTorch 至 2.6+ 以启用 ML 模型
- [ ] 优化闲聊识别准确率
- [ ] 添加更多实时类关键词
- [ ] 支持多轮对话上下文理解
