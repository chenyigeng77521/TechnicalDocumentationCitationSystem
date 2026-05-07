# Context Memory - 上下文记忆服务

> 项目：TechnicalDocumentationCitationSystem  
> 路径：`src/backend/firstlayer/context_memory`  
> 端口：**3006**  
> 职责：管理 session 级别的对话历史，为多轮对话提供上下文支持

---

## 📁 目录结构

```
context_memory/
├── src/
│   ├── app.py             # FastAPI 服务入口
│   ├── config.py          # 配置文件
│   └── memory_service.py  # 记忆服务核心实现
├── data/
│   └── sessions.json      # Session 数据存储（可选持久化）
└── __init__.py
```

---

## 🛠 技术栈

| 技术 | 说明 |
|------|------|
| FastAPI | Web 服务框架 |
| Pydantic | 数据验证 |

---

## 📝 数据模型

### Session 数据结构

```python
{
    "session_id": "session_abc123",
    "created_at": "2026-01-15T10:30:00Z",
    "history": [
        {
            "records": 1,
            "timestamp": "2026-01-15T10:30:15Z",
            "user": "华为 Mate60 Pro 充电速度怎么样？",
            "assistant": "支持 88W 有线快充，30 分钟可充至 80%。"
        },
        {
            "records": 2,
            "timestamp": "2026-01-15T10:32:08Z",
            "user": "它的续航表现呢？",
            "assistant": "内置 5000mAh 电池，重度使用续航约 8 小时。"
        }
    ]
}
```

### 存储限制
- 每个 session 最多保存 **30 组问答**
- 超出限制时自动删除最旧的对话记录
- **纯内存存储**，服务重启后数据清空

---

## 🌐 API 路由总览

### 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/context/create-session` | 创建新 session |
| DELETE | `/api/context/delete-session/:session_id` | 删除整个 session |
| POST | `/api/context/clear-session` | 清空 session 对话历史 |

### 消息管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/context/add-user-message` | 添加用户消息（一问的开始） |
| POST | `/api/context/add-assistant-message` | 添加助手消息（一问的结束） |

### 历史查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/context/get-history/:session_id` | 获取完整对话历史 |
| GET | `/api/context/get-all-messages/:session_id` | 获取所有消息列表 |
| GET | `/api/context/get-latest-question/:session_id` | 获取最新用户提问 |
| GET | `/api/context/get-latest-conversations/:session_id` | 获取最近 N 组问答 |

### 全局查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/context/get-all-sessions` | 获取所有 session |
| GET | `/api/context/get-all-conversations` | 获取所有会话记录 |

---

## 🔄 消息记录流程

```
1. 用户提问 → add-user-message
   ↓
2. 系统处理 → 记录到 history
   ↓
3. 助手回答 → add-assistant-message
   ↓
4. 更新记录 → 完成一问一答
```

### 添加用户消息
```json
POST /api/context/add-user-message
{
    "session_id": "session_abc123",
    "content": "华为 Mate60 Pro 充电速度怎么样？"
}
```

### 添加助手消息
```json
POST /api/context/add-assistant-message
{
    "session_id": "session_abc123",
    "content": "支持 88W 有线快充，30 分钟可充至 80%。"
}
```

---

## 📊 典型使用场景

### 场景 1：指代消解
```
用户：iPhone 15 多少钱？     → VALID
助手：iPhone 15 售价 5999 元起。

用户：它支持快充吗？         → "它" → "iPhone 15"
助手：支持 20W 快充。
```

### 场景 2：上下文补全
```
用户：我想了解一下 iPhone 15
助手：iPhone 15 是苹果最新款手机...

用户：128G 的价格呢？        → 结合上下文理解
助手：128G 版本售价 5999 元。
```

---

## 🚀 启动方式

```bash
# 进入目录
cd context_memory/src

# 启动服务
python app.py

# 或使用 uvicorn
uvicorn app:app --host 0.0.0.0 --port 3006
```

---

## ⚙️ 配置参数（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 3006 | 服务监听端口 |
| `HOST` | 0.0.0.0 | 监听地址 |
| `MAX_CONVERSATIONS` | 30 | 每个 session 最大问答组数 |

---

## 🔒 安全说明

- 纯内存存储，服务重启后数据丢失
- 无认证机制，仅限内网使用
- 无持久化层，可按需扩展 SQLite/Redis

---

## 📊 上游服务依赖

Context Memory 作为**被调用方**，为以下服务提供上下文支持：

| 服务名 | 端口 | 调用方式 |
|--------|------|----------|
| Entrance | 3002 | HTTP API 代理 |
| Category Classifier | 3004 | HTTP API |
| Question Filter | 3005 | HTTP API（可选） |
