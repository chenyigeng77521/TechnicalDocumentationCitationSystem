/**
 * 智能问答系统 - 主入口
 * 集成 Layer 3: 推理与引用层
 */

import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import * as path from 'path';
import * as http from 'http';
import multer from 'multer';
import uploadRoutes from './routes/upload.js';
import qaRoutes from './routes/qa.js';
import qaStreamRoutes from './routes/qa-stream.js';
import { createReasoningRouter } from './routes/reasoning.js';
import { DatabaseManager } from './database/index.js';

// 加载环境变量
dotenv.config();

const app = express();
const server = http.createServer(app);
const PORT = process.env.PORT || 3002;
const HOST = process.env.HOST || '0.0.0.0';

// 初始化数据库
const db = new DatabaseManager(process.env.DB_PATH || './storage/knowledge.db');

// 中间件
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// 静态文件服务
app.use('/storage', express.static(path.join(process.cwd(), 'storage')));

// API 路由
app.use('/api/upload', uploadRoutes);
app.use('/api/qa', qaRoutes);
app.use('/api/qa', qaStreamRoutes); // 流式问答

// 推理与引用层路由 (Layer 3)
const { router: reasoningRouter, webUI } = createReasoningRouter(db);
app.use('/api/reasoning', reasoningRouter);

// 设置 WebSocket 服务器
webUI.setWebSocketServer(server);

// 健康检查
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    version: '1.0.0'
  });
});

// 根路径
app.get('/', (req, res) => {
  res.json({
    name: 'Knowledge QA System',
    version: '1.0.0',
    description: '知识库驱动的智能问答系统',
    endpoints: {
      upload: 'POST /api/upload',
      ask: 'POST /api/qa/ask',
      askStream: 'POST /api/qa/ask-stream (流式)',
      search: 'POST /api/qa/search',
      files: 'GET /api/qa/files',
      stats: 'GET /api/qa/stats',
      index: 'POST /api/qa/index'
    }
  });
});

// 404 处理
app.use((req, res) => {
  res.status(404).json({
    success: false,
    message: '接口不存在'
  });
});

// 错误处理
app.use((err: any, req: express.Request, res: express.Response, next: express.NextFunction) => {
  console.error('❌ 服务器错误:', err);
  
  if (err instanceof multer.MulterError) {
    if (err.code === 'LIMIT_FILE_SIZE') {
      return res.status(400).json({
        success: false,
        message: '文件大小超过限制（最大 50MB）'
      });
    }
  }
  
  res.status(500).json({
    success: false,
    message: err.message || '服务器内部错误'
  });
});

// 启动服务器
const port = parseInt(PORT as string, 10);
server.listen(port, HOST, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║                                                          ║');
  console.log('║     🎯 知识库智能问答系统 已启动                          ║');
  console.log('║     ⚡ 推理与引用层 (Layer 3) 已集成                      ║');
  console.log('║                                                          ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
  console.log('');
  console.log(`📡 服务器地址：http://${HOST}:${PORT}`);
  console.log(`📊 健康检查：http://${HOST}:${PORT}/health`);
  console.log('');
  console.log('📚 API 端点:');
  console.log('   POST   /api/upload          - 上传文件');
  console.log('   POST   /api/qa/ask          - 回答问题（普通）');
  console.log('   POST   /api/qa/ask-stream   - 回答问题（流式）');
  console.log('   POST   /api/qa/search       - 检索文档');
  console.log('   GET    /api/qa/files        - 文件列表');
  console.log('   GET    /api/qa/stats        - 统计信息');
  console.log('   POST   /api/qa/index        - 向量化索引');
  console.log('');
  console.log('⚡ 推理与引用层端点:');
  console.log('   POST   /api/reasoning/ask         - 推理问答（普通）');
  console.log('   POST   /api/reasoning/ask-stream  - 推理问答（流式 SSE）');
  console.log('   WS     /ws/reasoning              - WebSocket 推理');
  console.log('   POST   /api/reasoning/direct      - 直接推理');
  console.log('   POST   /api/reasoning/stream      - 流式推理');
  console.log('');
  console.log(`⚙️  配置:`);
  console.log(`   LLM API: ${process.env.LLM_API_KEY ? '已配置' : '未配置（仅关键词检索）'}`);
  console.log(`   严格模式：${process.env.STRICT_MODE !== 'false' ? '启用' : '禁用'}`);
  console.log(`   拒答阈值: ${process.env.SCORE_THRESHOLD || '0.4'}`);
  console.log(`   最大上下文: ${process.env.MAX_CONTEXT_TOKENS || '6000'} tokens`);
  console.log(`   异步验证: ${process.env.ENABLE_ASYNC_VERIFICATION !== 'false' ? '启用' : '禁用'}`);
  console.log(`   动态治理: ${process.env.ENABLE_GOVERNANCE !== 'false' ? '启用' : '禁用'}`);
  console.log('');
});

// 优雅关闭
process.on('SIGINT', () => {
  console.log('\n👋 正在关闭服务器...');
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n👋 正在关闭服务器...');
  process.exit(0);
});
