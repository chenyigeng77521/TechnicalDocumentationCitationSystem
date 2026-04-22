# Knowledge QA System - 智能文档问答系统

基于知识库驱动的智能问答系统，支持多格式文档上传、自动转换、语义检索和精确引用。

---

## ✨ 核心特性

- 📄 **多格式支持**：PDF、Word、Excel、Markdown、纯文本
- 🔍 **双模式检索**：语义检索（向量）+ 关键词检索（兜底）
- 📚 **严格引用**：每个回答附带文档出处，支持溯源
- 🎯 **智能分块**：自动文档分块，保留位置映射
- 🔒 **严格模式**：只能根据文档回答，禁止编造
- 🎨 **专业 UI**：简洁的文档管理系统风格，去 AI 化设计
- 🐳 **Docker 部署**：完整容器化方案，一键启动

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层 (Frontend)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   问答首页   │  │   文件上传   │  │   文件管理   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      API 网关层 (Express)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 上传 API  │  │ 问答 API  │  │ 检索 API  │  │ 管理 API  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      核心服务层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 文档转换器   │  │ 检索引擎     │  │ 问答服务     │       │
│  │ (Word/Excel/ │  │ (语义 + 关键词)│  │ (严格引用)   │       │
│  │  PDF→MD)     │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据存储层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  SQLite      │  │ 向量索引     │  │ 文件存储     │       │
│  │ (元数据)     │  │ (Embedding)  │  │ (原始文件)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 方式 1：Docker 部署（推荐）

```bash
# 1. 克隆项目
git clone <repository-url>
cd knowledge-qa-system

# 2. 一键启动
chmod +x *.sh
./start.sh

# 3. 访问系统
# 前端：http://localhost:3000
# 后端：http://localhost:3002
```

**详细部署文档**: 查看 [DEPLOYMENT.md](./DEPLOYMENT.md)

---

### 方式 2：本地开发

#### 后端启动

```bash
cd knowledge-qa-system

# 安装依赖
npm install

# 配置环境变量
cp .env.example .env
# 编辑 .env（可选，不配置 LLM API 使用关键词检索）

# 启动服务
npm start
# 或
npx tsx src/server.ts
```

#### 前端启动

```bash
cd knowledge-qa-system/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问：http://localhost:3000

---

## 📖 使用指南

### 1. 上传文档

1. 点击顶部导航栏 "上传文件"
2. 拖拽文件或点击选择
3. 可选：设置分类和标签
4. 点击 "上传"

**支持格式**：
- `.pdf` - PDF 文档
- `.doc`, `.docx` - Word 文档
- `.xls`, `.xlsx` - Excel 表格
- `.txt` - 纯文本
- `.md` - Markdown

**限制**：
- 最多 10 个文件/次
- 单个文件最大 50MB

---

### 2. 文件管理

- 查看文档列表
- 查看统计信息（文档数、块数、索引状态）
- 重新触发向量化索引
- 删除文档

---

### 3. 智能问答

1. 在首页输入问题
2. 系统自动检索相关文档
3. 查看回答和引用来源

**回答示例**：
```
根据产品文档，我们的服务支持以下功能：
1. 文档智能检索
2. 多格式支持
3. 精确引用溯源

（文档路径：/uploads/product-guide.pdf，段落：功能介绍）
```

---

## 🔧 配置说明

### 环境变量

```bash
# .env（后端）

# LLM API（可选）
LLM_API_KEY=your_openai_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo

# 嵌入模型
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=1536

# 严格模式（默认 true）
STRICT_MODE=true

# 服务器
PORT=3002
HOST=0.0.0.0

# 数据库
DB_PATH=/app/storage/knowledge.db
INDEX_PATH=/app/storage/index
```

```bash
# .env.local（前端）

NEXT_PUBLIC_API_URL=http://localhost:3002
```

---

## 📊 API 文档

### 文件上传

```http
POST /api/upload
Content-Type: multipart/form-data

files: File[]
category?: string
tags?: string
```

**响应**：
```json
{
  "message": "上传成功",
  "files": [
    {
      "id": "uuid",
      "originalName": "doc.pdf",
      "status": "completed"
    }
  ]
}
```

---

### 智能问答

```http
POST /api/qa/ask
Content-Type: application/json

{
  "question": "如何配置系统？",
  "topK": 5,
  "strictMode": true
}
```

**响应**：
```json
{
  "answer": "系统配置需要在 .env 文件中设置...",
  "citations": [
    {
      "documentPath": "/uploads/config-guide.pdf",
      "paragraph": "配置说明章节",
      "score": 0.92
    }
  ]
}
```

---

### 语义检索

```http
POST /api/qa/search
Content-Type: application/json

{
  "query": "产品功能",
  "topK": 5
}
```

---

### 获取文件列表

```http
GET /api/qa/files
```

**响应**：
```json
{
  "files": [
    {
      "id": "uuid",
      "name": "doc.pdf",
      "format": "pdf",
      "size": 102400,
      "uploadTime": "2026-04-21T12:00:00Z",
      "category": "产品文档"
    }
  ]
}
```

---

### 获取统计信息

```http
GET /api/qa/stats
```

**响应**：
```json
{
  "stats": {
    "fileCount": 10,
    "chunkCount": 150,
    "indexedCount": 150
  }
}
```

---

### 触发向量化

```http
POST /api/qa/index
```

---

### 健康检查

```http
GET /health
```

**响应**：
```json
{
  "status": "ok",
  "timestamp": "2026-04-21T12:00:00Z",
  "version": "1.0.0"
}
```

---

## 🗂️ 项目结构

```
knowledge-qa-system/
├── src/                    # 后端源代码
│   ├── converter/          # 文档转换器
│   │   ├── index.ts        # 转换入口
│   │   ├── word.ts         # Word 转 MD
│   │   ├── excel.ts        # Excel 转 MD
│   │   ├── pdf.ts          # PDF 转 MD
│   │   └── markdown.ts     # Markdown 处理
│   ├── database/           # 数据库
│   │   └── index.ts        # SQLite 连接
│   ├── retriever/          # 检索引擎
│   │   └── index.ts        # 语义 + 关键词检索
│   ├── qa/                 # 问答服务
│   │   └── index.ts        # 严格引用问答
│   ├── routes/             # API 路由
│   │   └── index.ts
│   ├── types.ts            # 类型定义
│   └── server.ts           # 入口文件
├── frontend/               # 前端源代码
│   ├── app/
│   │   ├── page.tsx        # 问答首页
│   │   ├── upload/         # 上传页
│   │   ├── files/          # 文件管理页
│   │   └── globals.css     # 全局样式
│   ├── lib/
│   │   ├── store.ts        # Zustand 状态管理
│   │   └── api.ts          # API 封装
│   └── package.json
├── storage/                # 数据目录
│   ├── knowledge.db        # SQLite 数据库
│   ├── index/              # 向量索引
│   └── files/              # 上传的文件
├── docker-compose.yml      # Docker 编排
├── Dockerfile.backend      # 后端镜像
├── .env.example            # 环境变量模板
├── start.sh                # 启动脚本
├── DEPLOYMENT.md           # 部署文档
└── README.md               # 本文件
```

---

## 🛠️ 技术栈

### 后端

- **运行环境**: Node.js v20+
- **语言**: TypeScript
- **Web 框架**: Express.js
- **数据库**: SQLite (better-sqlite3)
- **文档转换**: mammoth, xlsx, pdf-parse
- **向量检索**: OpenAI Embedding（可选）
- **文件上传**: Multer

### 前端

- **框架**: Next.js 16
- **UI**: React 19 + Tailwind CSS 4
- **状态管理**: Zustand 5
- **HTTP 客户端**: Axios

---

## 📦 依赖安装

### 后端依赖（198 个包）

```bash
npm install express multer mammoth xlsx pdf-parse openai uuid cors dotenv better-sqlite3
```

### 前端依赖（360+ 个包）

```bash
npm install next react react-dom axios zustand lucide-react tailwindcss
```

---

## 🔐 安全特性

- ✅ 文件大小限制（50MB）
- ✅ 文件类型白名单
- ✅ 严格引用模式（禁止编造）
- ✅ 非 root 用户运行（Docker）
- ✅ 健康检查（自动检测）
- ✅ 日志轮转（防止磁盘占满）

---

## 📈 性能优化

- **向量索引**: 支持快速语义检索
- **缓存机制**: 检索结果缓存（可扩展）
- **流式响应**: 大文档流式处理
- **并发控制**: 限制同时上传数量

---

## 🐛 故障排查

### 常见问题

**Q: 上传失败？**  
A: 检查文件大小是否超过 50MB，格式是否在白名单内。

**Q: 检索结果为空？**  
A: 检查是否已触发向量化索引（文件管理页点击 "重新索引"）。

**Q: LLM API 错误？**  
A: 检查 `.env` 中的 `LLM_API_KEY` 是否正确。

**Q: 数据库连接失败？**  
A: 检查 `storage/` 目录权限（chmod 777）。

**Q: Docker 启动失败？**  
A: 查看日志 `./logs.sh -f`，检查端口是否被占用。

---

## 📝 开发指南

### 添加新文档格式

1. 在 `src/converter/` 添加转换模块
2. 在 `src/converter/index.ts` 注册
3. 更新 `allowedTypes` 白名单

### 自定义检索策略

修改 `src/retriever/index.ts` 中的检索逻辑。

### 扩展 API

在 `src/routes/` 添加新路由，在 `src/routes/index.ts` 注册。

---

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

---

## 📄 许可证

MIT License

---

## 📞 联系方式

- **项目地址**: [GitHub](https://github.com/your-repo)
- **问题反馈**: [Issues](https://github.com/your-repo/issues)

---

## 🎯 未来计划

- [ ] PPT 完整解析支持
- [ ] 批量操作（删除、索引）
- [ ] 用户权限管理
- [ ] 多租户支持
- [ ] 检索结果缓存优化
- [ ] 移动端响应式优化
- [ ] 设置页面（LLM 配置）
- [ ] 导出问答历史

---

**最后更新**: 2026-04-22  
**版本**: 1.0.0
