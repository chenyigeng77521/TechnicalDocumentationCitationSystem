# 推理与引用层 (Reasoning Layer)

> Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline

## 概述

推理与引用层是技术文档智能问答系统的核心层，负责：
- 将检索到的文档块精准注入到 LLM 上下文
- 执行 LLM 推理生成回答
- 验证回答中的引用是否真实有效
- 严格限制推理范围，杜绝模型幻觉

## 五大核心要求

### 1. 精准注入（转化）
- 将检索到的"最小充分信息集合"封装并注入模型
- 去重、截断、格式化为统一的上下文块
- 支持 `is_truncated` 标注

### 2. 双重溯源（验证）
- **同步验证**：检查引用 ID 是否真实存在（< 10ms）
- **异步验证**：Token 级匹配关键信息（名词、数字、版本号）
- 可信度标记：`✓`（验证通过）/ `?`（不确定）

### 3. 动态治理（清理）
- 实时剔除冗余或冲突信息
- 跨文档语义去重（余弦相似度 > 0.95）
- 冲突解决策略：保留高分/保留两者/合并

### 4. 边界严控（拒答）
- 硬性门控：`max_score < 0.4` 直接拒答
- 空查询、无结果等边界情况处理
- 拒答时返回调试信息供评委验证

### 5. 效能平衡（分级）
- 异步校对与分级验证
- 不阻塞响应的异步质量检查
- 流式输出 + 实时引用展示

## 模块结构

```
Reasoning/
├── types.ts              # 类型定义
├── context_injector.ts    # 上下文注入器
├── prompt_builder.ts      # 提示词构建器
├── citation_verifier.ts   # 引用验证器（同步+异步）
├── rejection_guard.ts     # 拒答守卫
├── context_governance.ts  # 动态治理器
├── reasoning_pipeline.ts   # 推理管道编排
├── webui.ts               # WebUI 接口
└── index.ts               # 导出入口
```

## API 接口

### REST API

#### POST `/api/reasoning/ask`
问答接口

```json
// Request
{
  "question": "如何配置 OAuth2 认证？",
  "topK": 5,
  "strictMode": true,
  "enableAsyncVerification": true
}

// Response
{
  "success": true,
  "answer": "OAuth2 配置需要...",
  "citations": [
    {
      "id": 1,
      "anchorId": "docs/auth.md#1000",
      "titlePath": "Authentication > OAuth2",
      "score": 0.87,
      "verificationStatus": "verified",
      "filePath": "docs/auth.md",
      "snippet": "OAuth2 配置需要..."
    }
  ],
  "noEvidence": false,
  "maxScore": 0.87,
  "confidence": 0.85,
  "contextTruncated": false
}
```

#### POST `/api/reasoning/ask-stream`
流式问答接口（SSE）

```json
// 事件流
data: {"answer": "OAuth2 "}
data: {"answer": "配置"}
data: {"citation": {"id": 1, "anchorId": "docs/auth.md#1000"}}
data: {"verification": {"citationId": 1, "status": "verified"}}
data: {"sources": [...]}
data: [DONE]
```

### WebSocket

#### WS `/ws/reasoning`

```json
// 连接
{"type": "connected", "clientId": "client_1"}

// 发送请求
{"type": "ask", "question": "...", "requestId": "123"}

// 接收响应
{"type": "response", "requestId": "123", "answer": "...", "citations": [...]}
```

## 配置项

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_API_KEY` | - | LLM API 密钥 |
| `LLM_BASE_URL` | - | LLM API 基础 URL |
| `LLM_MODEL` | `gpt-4-turbo` | LLM 模型 |
| `SCORE_THRESHOLD` | `0.4` | 拒答阈值 |
| `MAX_CONTEXT_TOKENS` | `6000` | 最大上下文 token |
| `ENABLE_ASYNC_VERIFICATION` | `true` | 启用异步验证 |
| `ENABLE_GOVERNANCE` | `true` | 启用动态治理 |

## 使用示例

### 1. 基础使用

```typescript
import { createReasoningPipeline } from './Reasoning';

const pipeline = createReasoningPipeline({
  llm: {
    apiKey: process.env.LLM_API_KEY,
    baseUrl: process.env.LLM_BASE_URL,
  },
  scoreThreshold: 0.4,
});

const response = await pipeline.reason({
  query: "如何配置 OAuth2 认证？",
  chunks: retrievedChunks,
  strictMode: true,
});

console.log(response.answer);
console.log(response.citations);
```

### 2. 流式使用

```typescript
for await (const event of pipeline.streamReason(request)) {
  switch (event.type) {
    case 'token':
      console.log(event.content);
      break;
    case 'citation':
      console.log('New citation:', event.citation);
      break;
    case 'done':
      console.log('Final response:', event.response);
      break;
  }
}
```

## 验证流程

### 同步验证（< 10ms）
1. 从 LLM 回答中提取所有 `[n]` 引用
2. 检查 ID 是否存在于 chunks 列表
3. 剔除无效引用，标记为 `[n❓]`

### 异步验证（不阻塞）
1. 提取引用附近的关键词（名词、数字、版本号）
2. 在原始 chunk 中查找匹配
3. 计算匹配率：`matched / total`
4. 更新可信度标记：`✓` / `?`

## 拒答条件

| 条件 | 原因 | 消息 |
|------|------|------|
| 无检索结果 | `NO_CHUNKS` | 未检索到相关文档 |
| 得分 < 0.4 | `LOW_SCORE` | 检索得分低于阈值 |
| 空查询 | `EMPTY_QUERY` | 查询内容为空 |

拒答响应示例：
```
根据现有文档无法回答此问题。

提示：当前检索得分（0.31）低于系统阈值（0.4），无法确保回答准确性。

--- 调试信息（供评委验证）---
最高检索得分: 0.31
系统阈值: 0.4
检索到的文档块数: 3
Top 5 得分: [0.31, 0.28, 0.15, 0.12, 0.08]
--------------------------------
```

## 上下文格式

注入 LLM 的上下文格式：
```
[ID: 1, Source: docs/api/auth.md#4821 | Authentication > OAuth2 > Token Refresh]
Token 刷新接口需在请求头中携带 Authorization: Bearer {refresh_token}...

---

[ID: 2, Source: docs/api/auth.md#5100 | Authentication > OAuth2 > Token Expiry]
Token 默认有效期为 7 天...

[此段内容已截断，建议查阅原文]
```

## 集成到现有系统

1. 安装依赖：
```bash
npm install ws @types/ws
```

2. 在 `server.ts` 中引入：
```typescript
import { createReasoningRouter } from './routes/reasoning';
import { DatabaseManager } from './database/index.js';

const db = new DatabaseManager(process.env.DB_PATH);
const { router, webUI } = createReasoningRouter(db);
app.use('/api/reasoning', router);

// 设置 WebSocket
webUI.setWebSocketServer(server);
```

## License

MIT
