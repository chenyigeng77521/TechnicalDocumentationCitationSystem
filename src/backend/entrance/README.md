# Entrance Service - 入口服务模块

> 项目：TechnicalDocumentationCitationSystem  
> 路径：`src/backend/entrance`  
> 端口：**3002**  
> 职责：接收前端请求，统一编排下游服务，是系统的**唯一入口层**

---

## 📁 目录结构

```
entrance/
├── src/
│   ├── config.ts                  # 配置中心（运行时读取环境变量）
│   ├── types.ts                   # 全局类型定义
│   ├── server.ts                  # Express 服务启动入口
│   ├── routes/
│   │   ├── qa.ts                 # 问答路由（/api/qa）
│   │   ├── upload.ts             # 文件上传路由（/api/upload）
│   │   ├── context.ts            # 上下文记忆代理路由（/api/context）
│   │   ├── session.ts            # Session 管理路由（/api/session）
│   │   ├── batch-test.ts        # 批量测试路由（/api/batch-test）
│   │   └── logs.ts              # 日志流式推送路由（/api/logs）
│   └── services/
│       ├── firstlayer-client.ts   # FirstLayer 分类服务客户端
│       └── question-filter-client.ts  # Question Filter 过滤服务客户端
├── dist/                         # tsc 编译输出
├── storage/
│   ├── batchtest/                # 批量测试上传临时文件
│   └── result/                  # 批量测试结果文件
├── logs/                         # 日志输出目录
├── .env                          # 环境变量配置
├── package.json
└── tsconfig.json
```

---

## 🛠 技术栈

| 技术 | 说明 |
|------|------|
| Express 4.18 | HTTP 服务框架 |
| TypeScript 5.3 | 类型安全 |
| Multer | 文件上传中间件 |
| Axios / node-fetch | HTTP 客户端 |
| dotenv | 环境变量加载 |
| uuid | 唯一 ID 生成 |

---

## 🌐 API 路由总览

### `/api/qa` - 智能问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ask` | 同步问答（已废弃，保留兼容） |
| POST | `/ask-stream` | **流式问答（SSE）**，生产使用 |
| GET | `/types` | 获取问题分类类型列表 |
| GET | `/files` | 获取已上传文件列表 |
| GET | `/stats` | 获取系统统计信息 |
| DELETE | `/files/:filename` | 删除指定文件 |
| POST | `/batch-classify` | 批量分类问题 |

**问答调用链**：
```
前端 → POST /api/qa/ask-stream
  → Question Filter（过滤无效问题）
  → NLU Pipeline（指代消解、查询重写，可选）
  → Category Classifier（问题分类）
  → Reasoning Service（端口 8001，检索+回答）
  → 返回 SSE 流
```

---

### `/api/upload` - 文件管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/` | 上传文件（支持多文件，最大 100 个） |
| GET | `/raw-files` | 获取 data/ 目录下所有文件（分页） |
| GET | `/download/:filename` | 下载文件 |
| DELETE | `/delete` | 删除文件（先通知索引服务） |
| GET | `/read` | 读取文件内容 |
| POST | `/save` | 保存/更新文件内容 |
| POST | `/modify-index` | 通知索引服务重新索引 |

**删除事务保证**：先调用索引服务（端口 3003）删除索引，返回 `status=deleted` 后才删除本地文件，否则不删除。

---

### `/api/context` - 上下文记忆（代理转发到端口 3006）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/create-session` | 创建新会话 |
| GET | `/get-all-messages/:session_id` | 获取完整对话历史 |
| GET | `/get-latest-conversations/:session_id` | 获取最近 N 组问答 |
| POST | `/add-user-message` | 添加用户消息 |
| POST | `/add-assistant-message` | 添加助手消息 |

---

### `/api/session` - Session 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/create` | 创建新 session |
| GET | `/validate/:session_id` | 验证 session 是否有效 |
| GET | `/info/:session_id` | 获取 session 详细信息 |

---

### `/api/batch-test` - 批量测试

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/upload` | 上传批量测试文件（JSON/JSONL/CSV/TXT） |
| GET | `/results` | 获取结果文件列表（分页） |
| GET | `/download/:filename` | 下载结果文件 |
| POST | `/submit` | 接收前端解析好的批量数据，转发到推理层 |

**支持的批量文件格式**：`.json`、`.jsonl`、`.txt`、`.csv`、`.md`、`.adoc`

批量文件保存路径：`项目根目录/data/batchtest/`

---

### `/api/logs` - 日志流式推送

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stream` | SSE 流式推送日志（tail -f 风格） |
| GET | `/read` | 读取日志内容（普通 JSON，兼容 Cloudflare Tunnel） |
| POST | `/write` | 前端主动写入日志 |

---

## ⚙️ 环境变量配置（`.env`）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `3002` | 服务监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `UPLOAD_DIR` | `../../../data/documents` | 文件上传目录 |
| `DATA_ROOT` | `../../../data` | 数据根目录 |
| `BATCH_TEST_UPLOAD_DIR` | `../storage/batchtest` | 批量测试上传目录 |
| `RESULT_DIR` | `../../../eval` | 结果文件目录 |
| `FIRSTLAYER_URL` | `http://localhost:3004` | 分类服务地址 |
| `ENABLE_QUESTION_CLASSIFICATION` | `false` | 是否启用问题分类 |
| `QUESTION_FILTER_URL` | `http://localhost:3005` | 问题过滤服务地址 |
| `ENABLE_QUESTION_FILTER` | `true` | 是否启用问题过滤 |
| `CONTEXT_MEMORY_URL` | `http://localhost:3006` | 上下文记忆服务地址 |
| `ENABLE_CONTEXT_MEMORY` | `true` | 是否启用上下文记忆 |
| `BATCH_QUERY_URL` | `http://localhost:8001/api/qa/batch` | 批量查询地址 |
| `ENABLE_NLU` | `false` | 是否启用 NLU 管道 |
| `NLU_PIPELINE_URL` | `http://localhost:3004/api/nlu/process` | NLU 管道地址 |

---

## 🚀 启动方式

```bash
# 安装依赖
npm install

# 开发模式（tsx 热重载）
npm run dev

# 生产构建
npm run build

# 生产启动
npm start
```

---

## 📝 关键设计说明

### 1. NLU 预处理（可选）

问答流程中支持 NLU 管道：
- **指代消解**：处理"它"、"这个"等指代词
- **查询重写**：优化问题表达
- **完整性检查**：判断问题是否完整
- 若 NLU 服务不可用，自动降级到本地规则处理

### 2. 事务一致性（删除/编辑）

- **删除**：先调索引服务 → `status=deleted` → 才删本地文件
- **编辑保存**：先调索引服务 → `status=indexed` → 才保存文件
- 保证索引服务与本地文件系统状态一致

### 3. 请求超时配置

- 全局请求超时：**20 分钟**
- 索引服务调用超时：60 秒
- 推理层调用超时：120 秒
- 批量测试调用超时：30 分钟

### 4. 文件名安全

- 自动修复 Latin-1 编码导致的中文乱码
- 过滤非法字符（`< > : " / \ | ? *`）
- 防止路径穿越攻击（所有路径均做 `startsWith` 校验）

---

## 📊 下游服务依赖

| 服务名 | 端口 | 说明 |
|--------|------|------|
| Index Service | 3003 | 文件索引服务 |
| Reasoning Service | 8001 | 推理问答服务 |
| FirstLayer Classifier | 3004 | 问题分类服务（可选） |
| Question Filter | 3005 | 问题过滤服务 |
| Context Memory | 3006 | 上下文记忆服务 |
| NLU Pipeline | 3004 | NLU 处理管道（可选） |
