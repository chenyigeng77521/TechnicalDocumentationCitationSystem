# NLU 处理流程说明

## 📋 完整处理流程

```
用户提问
   ↓
1. 指代判断 (RexUniNLU) → 检测是否包含指代词
   ↓
2. 上下文加载 → 如果有指代词，从上下文记忆服务加载历史会话 (2 轮)
   ↓
3. 指代替换 (RexUniNLU) → 用历史上下文替换指代词
   ↓
4. 查询改写 (SlimPLM-Query-Rewriting) → 优化查询表达
   ↓
5. 完整性检查 → 两层判断
   ├─ 5.1 规则快速过滤 → 拦截格式错误、空问题等
   └─ 5.2 TurnSense 模型 → 语义完整性判断
   ↓
6. 检索层调用 → http://172.25.178.29:18020/query
   ↓
7. 记录上下文 → 将问答记录到上下文记忆服务
   ↓
返回答案给前端
```

---

## 🚀 API 接口

### 1. 完整 NLU 处理

```bash
POST /api/nlu/process
Content-Type: application/json

{
  "question": "如何申请年假？",
  "session_id": "session_abc123"  // 可选
}
```

**响应**:
```json
{
  "success": true,
  "question": "如何申请年假？",
  "answer": "根据知识库内容...\n\n**具体答案：**...",
  "sources": ["文件：第三方系统.md", "..."],
  "error": null,
  "processing_steps": {
    "has_pronoun": false,
    "query_rewritten": "如何申请年假",
    "completeness_check": {
      "is_complete": true,
      "message": "通过规则检查"
    },
    "retrieval": {
      "success": true,
      "execution_time": 3.627
    },
    "context_recorded": true
  },
  "category": "PROC",
  "confidence": 0.85
}
```

---

### 2. 仅分类（不检索）

```bash
POST /api/nlu/classify-only
Content-Type: application/json

{
  "question": "如何申请年假？",
  "session_id": "session_abc123"
}
```

**响应**:
```json
{
  "success": true,
  "question": "如何申请年假？",
  "category": "PROC",
  "confidence": 0.85,
  "description": "过程型问题 - 询问步骤、流程、操作方法"
}
```

---

### 3. 检查问题完整性

```bash
GET /api/nlu/check-completeness?question=如何申请年假
```

**响应**:
```json
{
  "success": true,
  "is_complete": true,
  "message": "通过规则检查"
}
```

---

### 4. 查询改写

```bash
POST /api/nlu/rewrite-query
Content-Type: application/json

{
  "question": "请问年假怎么申请呢？"
}
```

**响应**:
```json
{
  "success": true,
  "original": "请问年假怎么申请呢？",
  "rewritten": "如何申请年假"
}
```

---

### 5. 指代消解

```bash
POST /api/nlu/resolve-pronoun
Content-Type: application/json

{
  "question": "它怎么申请？",
  "session_id": "session_abc123"
}
```

**响应**:
```json
{
  "success": true,
  "has_pronoun": true,
  "original": "它怎么申请？",
  "resolved": "年假怎么申请？",
  "replaced": true,
  "history_count": 2
}
```

---

### 6. 测试检索层连接

```bash
GET /api/nlu/test-retrieval?question=测试
```

**响应**:
```json
{
  "success": true,
  "retrieval_success": true,
  "answer": "根据知识库内容...",
  "error": null
}
```

---

## ⚙️ 配置说明

### .env 文件配置

```bash
# 上下文记忆服务地址
CONTEXT_MEMORY_URL=http://localhost:3006

# 检索层地址
RETRIEVAL_URL=http://172.25.178.29:18020/query

# HTTP 超时时间（秒）
HTTP_TIMEOUT=60

# NLU 模型路径（实际使用时需要配置真实路径或 API）
REXUNINLU_MODEL_PATH=rex_uninlu
SLIMPLM_MODEL_PATH=slimplm_query_rewriting
TURNSENSE_MODEL_PATH=turnsense
```

---

## 🔧 完整性检查两层逻辑

### 第一层：规则快速过滤

```python
# 空检查
if not question:
    return False, "问题不能为空"

# 长度检查
if len(question) < 2:
    return False, "问题太短，请提供更详细的描述"

# 格式错误检查
if question.count('?') > 3:
    return False, "问题格式异常"

# 乱码检查
if 特殊字符比例 > 50%:
    return False, "问题包含过多特殊字符，请重新输入"
```

### 第二层：TurnSense 模型检查

```python
# TODO: 实际使用时调用 TurnSense 模型
# 这里使用简单规则作为占位符
return True, "通过语义检查"
```

---

## 📊 检索层接口说明

### 请求格式

```bash
POST http://172.25.178.29:18020/query
Content-Type: application/json

{
  "query": "AUTH CRBT USER 说明",
  "timeout": 60,
  "return_raw": false
}
```

### 响应格式

```json
{
  "success": true,
  "query": "AUTH CRBT USER 说明",
  "answer": "根据知识库内容，在文件 **第三方系统.md** 中找到了相关信息。\n\n**具体答案：**...",
  "raw_output": null,
  "error": null,
  "execution_time": 3.627309799194336,
  "timestamp": "2026-04-27T15:35:11.722971",
  "sources": [
    "**第三方系统.md",
    "文件：第三方系统.md",
    "第三方系统.md"
  ],
  "metadata": {
    "files_in_wiki": 12,
    "wiki_path": "/Users/lenghaijun/sdd/kdDemo/wiki",
    "cached": true
  }
}
```

### 响应 Headers

```
access-control-allow-credentials: true
access-control-allow-origin: *
content-type: application/json
```

---

## 🔄 上下文记忆集成

### 记录用户提问

```bash
POST http://localhost:3006/api/context/add-user-message
Content-Type: application/json

{
  "session_id": "session_abc123",
  "content": "如何申请年假？"
}
```

### 记录助手回答

```bash
POST http://localhost:3006/api/context/add-assistant-message
Content-Type: application/json

{
  "session_id": "session_abc123",
  "content": "根据知识库内容，年假申请流程如下..."
}
```

### 获取历史对话

```bash
GET http://localhost:3006/api/context/get-latest-conversations/session_abc123
```

**响应**:
```json
{
  "success": true,
  "session_id": "session_abc123",
  "conversations": [
    {
      "user_message": "如何申请年假？",
      "assistant_message": "年假申请流程如下...",
      "timestamp": "2026-04-27T15:35:11"
    },
    {
      "user_message": "年假有多少天？",
      "assistant_message": "根据员工手册，年假为 15 天...",
      "timestamp": "2026-04-27T15:36:22"
    }
  ]
}
```

---

## 🚀 启动服务

```bash
cd /Users/chenyigeng/Library/Application Support/winclaw/.openclaw/workspace/TechnicalDocumentationCitationSystem/backend/firstlayer/category_classifier

# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置真实的服务地址

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python app.py

# 或使用启动脚本
./start.sh
```

---

## 📝 注意事项

1. **NLU 模型配置**: 当前代码使用占位符，实际使用时需要配置真实的 RexUniNLU、SlimPLM、TurnSense 模型路径或 API
2. **检索层地址**: 确保检索服务 `http://172.25.178.29:18020/query` 可访问
3. **上下文记忆服务**: 确保 `http://localhost:3006` 服务已启动
4. **CORS 配置**: 已配置允许所有来源访问，生产环境建议限制

---

## 🐛 故障排查

### 问题：检索层连接失败

**检查**:
```bash
curl http://172.25.178.29:18020/health
```

**解决**:
- 确认检索服务已启动
- 检查网络连通性
- 检查防火墙设置

### 问题：上下文记忆服务不可用

**检查**:
```bash
curl http://localhost:3006/health
```

**解决**:
- 启动 Context Memory 服务
- 检查端口 3006 是否被占用

### 问题：NLU 模型加载失败

**检查**:
```bash
# 查看日志
tail -f logs/category_classifier.log
```

**解决**:
- 确认模型文件存在
- 检查模型路径配置
- 确认有足够的内存加载模型

---

**版本**: 1.0.0  
**更新日期**: 2026-04-27
