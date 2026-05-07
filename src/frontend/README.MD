# Frontend - 智能知识库问答系统前端

## 📁 目录结构

```
frontend/
├── app/                          # Next.js App Router 目录
│   ├── page.tsx                  # 首页 - 问答系统主界面
│   ├── layout.tsx                # 根布局组件
│   ├── globals.css               # 全局样式
│   ├── FileEditModal.tsx         # 文件编辑弹窗组件
│   ├── files/
│   │   └── page.tsx              # 文件管理页面
│   ├── upload/
│   │   └── page.tsx              # 文件上传页面
│   └── lib/
│       ├── api.ts                # API 调用封装
│       └── langLoader.ts         # CodeMirror 语言加载器
├── lib/                          # 公共工具库
│   ├── api.ts                    # API 封装（兼容旧版）
│   └── store.ts                  # Zustand 状态管理
├── public/                       # 静态资源目录
├── types/                        # TypeScript 类型定义
├── next.config.ts                # Next.js 配置
├── package.json                  # 项目依赖
├── tsconfig.json                 # TypeScript 配置
└── tailwind.config.js            # Tailwind CSS 配置
```

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| **Next.js 16.2.4** | React 框架 |
| **React 19.2.4** | UI 库 |
| **Tailwind CSS 4** | 样式框架 |
| **Zustand** | 状态管理 |
| **CodeMirror** | 代码编辑器 |
| **Lucide React** | 图标库 |
| **Axios** | HTTP 请求 |

## 📱 页面功能

### 1. 首页 (page.tsx)
**主问答界面**，核心功能：
- **问答输入**：文本框输入问题，AI 智能检索回答
- **文档上传**：拖拽/点击上传文档到知识库
- **批量测试**：批量上传测试问题文件
- **引用来源**：点击可打开源文件并定位到引用位置
- **历史记录**：保存会话历史
- **收藏功能**：收藏常用问答
- **后台日志**：实时查看后端日志（鼠标移入/滚动暂停轮询）

### 2. 文件上传页 (upload/page.tsx)
- 拖拽上传区域，支持 100 个文件
- 文件格式验证（PDF、Word、Excel、MD、代码文件等）
- 单文件最大 300MB
- 分类和标签设置
- 上传结果展示

### 3. 文件管理页 (files/page.tsx)
- 文件列表展示
- 文件大小、修改时间显示
- 文件删除功能

## 🔌 API 接口

前端通过代理访问后端 API：

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/upload` | POST | 上传文件 |
| `/api/qa/files` | GET | 获取文件列表 |
| `/api/qa/stats` | GET | 获取统计信息 |
| `/api/qa/files/:name` | DELETE | 删除文件 |
| `/api/qa/query` | POST | 问答查询 |
| `/api/batch-test/submit` | POST | 批量测试 |
| `/api/context/create-session` | GET | 创建会话 |
| `/api/logs/write` | POST | 写入日志 |

## 🚀 启动方式

```bash
# 开发模式
npm run dev

# 生产构建
npm run build

# 生产启动
npm run start

# 代码检查
npm run lint
```

## ⚙️ 环境配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `NEXT_PUBLIC_API_URL` | 后端 API 地址 | `http://localhost:3002` |

## 🎨 代码编辑器

使用 **CodeMirror** 支持多种语言语法高亮：
- JSON, YAML, Python, JavaScript, TypeScript
- XML, HTML, SQL, Markdown
- Shell 等
