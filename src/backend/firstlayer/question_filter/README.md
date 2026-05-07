# Question Filter - 问题过滤服务

> 项目：TechnicalDocumentationCitationSystem  
> 路径：`src/backend/firstlayer/question_filter`  
> 端口：**3005**  
> 职责：过滤无效问题和实时类问题，是问答系统的**前置过滤层**

---

## 📁 目录结构

```
question_filter/
├── app.py               # FastAPI 服务入口
├── config.py            # 配置文件
├── classifier.py        # 过滤分类器核心实现
├── routes/
│   ├── classify.py      # 过滤 API
│   └── __init__.py
└── __init__.py
```

---

## 🛠 技术栈

| 技术 | 说明 |
|------|------|
| FastAPI | Web 服务框架 |
| PyTorch | 深度学习框架 |
| Transformers | Hugging Face 模型库 |
| StructBERT | 问题过滤模型 |

---

## 🔬 过滤分类

### 支持的分类类型

| 分类 | 说明 | 处理方式 |
|------|------|----------|
| **VALID** | 有效问题 | 正常处理，继续后续流程 |
| **INVALID** | 无效问题 | 无法回答的问题，返回过滤提示 |
| **REALTIME** | 实时类问题 | 需要实时数据的问题，返回提示 |
| **OFFTOPIC** | 偏离主题 | 恶意/敏感/广告等问题，拒绝回答 |
| **CHAT** | 友好闲聊 | 日常问候，可适度回应 |
| **SELF_INTRO** | 自我介绍 | 询问 AI 身份的问题 |

---

## 🌐 API 路由总览

### `/api/filter` - 问题过滤

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/` | 单条问题过滤 |
| GET | `/types` | 获取所有过滤类型 |
| POST | `/batch` | 批量过滤 |
| POST | `/with-context` | 上下文记忆层二次过滤 |
| GET | `/keywords` | 获取实时类关键词列表 |

---

### 过滤请求示例

```json
{
    "question": "今天的天气怎么样？",
    "conversation_history": [
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "您好！有什么可以帮助您的吗？"}
    ]
}
```

### 过滤响应示例

```json
{
    "success": true,
    "question": "今天的天气怎么样？",
    "category": "REALTIME",
    "confidence": 0.95,
    "description": "实时类问题",
    "reason": "问题需要实时天气数据",
    "filter_message": "抱歉，这个问题需要实时数据支持..."
}
```

---

## 🔄 多级过滤策略

```
1. 规则检查（快速过滤）
   ↓
2. 关键词匹配（闲聊、实时类等）
   ↓
3. ML 模型分类（StructBERT）
   ↓
4. 上下文记忆层二次过滤（边界情况）
```

---

## 🚀 启动方式

```bash
# 进入目录
cd question_filter

# 启动服务
python app.py

# 或使用 uvicorn
uvicorn app:app --host 0.0.0.0 --port 3005
```

---

## ⚙️ 环境变量配置

| 变量名 | 说明 |
|--------|------|
| `HOST` | 监听地址（默认 0.0.0.0） |
| `PORT` | 监听端口（默认 3005） |
| `MODEL_PATH` | 模型文件路径 |
| `CONTEXT_MEMORY_URL` | 上下文记忆服务地址（可选） |
| `CONTEXT_MEMORY_ENABLED` | 是否启用上下文记忆层 |

---

## 📝 过滤消息模板

当问题被过滤时，返回对应的友好提示消息：

- **INVALID**：抱歉，您的问题不在知识库覆盖范围内
- **REALTIME**：抱歉，这个问题需要实时数据支持
- **OFFTOPIC**：抱歉，我无法回答这类问题
- **CHAT**：您好！有什么可以帮助您的吗？
- **SELF_INTRO**：我是您的智能助手...

---

## 📊 下游服务依赖

| 服务名 | 端口 | 说明 |
|--------|------|------|
| Context Memory | 3006 | 上下文记忆服务（可选） |

