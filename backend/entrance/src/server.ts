/**
 * 智能问答系统 - 主入口
 */

import * as path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

// ES Module 兼容
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ⚠️ 必须在导入任何使用 process.env 的模块之前加载环境变量！
const envPath = path.join(__dirname, '../.env');
dotenv.config({ path: envPath });
console.log(`📝 已加载环境变量：${envPath}`);
console.log(`🔧 ENABLE_QUESTION_CLASSIFICATION: ${process.env.ENABLE_QUESTION_CLASSIFICATION}`);

// 延迟导入 config，确保 dotenv 已加载
const configModule = await import('./config.js');
const config = configModule.config;

// 调试输出 config
console.log(`🔧 Config loaded: firstlayer.enabled = ${config.firstlayer.enabled}`);

import express from 'express';
import cors from 'cors';
import multer from 'multer';
import uploadRoutes from './routes/upload.js';
import qaRoutes from './routes/qa.js';

const app = express();
const PORT = process.env.PORT || 3002;
const HOST = process.env.HOST||'0.0.0.0' ;

// 请求超时配置（20分钟）
app.use((req, res, next) => {
  req.setTimeout(20 * 60 * 1000, () => {
    console.error('❌ 请求超时（20分钟）');
  });
  res.setTimeout(20 * 60 * 1000, () => {
    console.error('❌ 响应超时（20分钟）');
  });
  next();
});

// 中间件
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// 静态文件服务
app.use('/storage', express.static(path.join(process.cwd(), 'storage')));

// API 路由
app.use('/api/upload', uploadRoutes);
app.use('/api/qa', qaRoutes);

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
    name: 'File Upload Service',
    version: '1.0.0',
    description: '文件上传与管理服务',
    endpoints: {
      upload: 'POST /api/upload',
      files: 'GET /api/qa/files',
      stats: 'GET /api/qa/stats',
      deleteFile: 'DELETE /api/qa/files/:filename'
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
        message: '文件大小超过限制（最大 300MB）'
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
app.listen(port, HOST, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║                                                          ║');
  console.log('║     📁 文件上传服务 已启动                               ║');
  console.log('║                                                          ║');
  console.log('╚══════════════════════════════════════════════════════════╝');
  console.log('');
  console.log(`📡 服务器地址：http://${HOST}:${PORT}`);
  console.log(`📊 健康检查：http://${HOST}:${PORT}/health`);
  console.log('');
  console.log('📚 API 端点:');
  console.log('   POST   /api/upload          - 上传文件');
  console.log('   GET    /api/qa/files         - 文件列表');
  console.log('   GET    /api/qa/stats         - 统计信息');
  console.log('   DELETE /api/qa/files/:name  - 删除文件');
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
