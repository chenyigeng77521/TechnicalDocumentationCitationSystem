/**
 * 日志流式接口 - SSE (Server-Sent Events)
 * GET /api/logs/stream?file=backend.log
 * 支持 tail -f 风格实时推送日志更新
 */

import { Router, Request, Response } from 'express';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 日志目录：项目根目录下的 logs/
const LOGS_DIR = path.resolve(__dirname, '../../../../logs');

const router = Router();

/**
 * GET /api/logs/stream
 * SSE 流式推送日志内容，支持 tail -f 风格
 * Query: file=backend.log (默认), tail=true (是否只读尾部)
 */
router.get('/stream', (req: Request, res: Response) => {
  const fileParam = (req.query.file as string) || 'backend.log';
  const tailOnly = req.query.tail !== 'false';

  // 安全检查：防止路径穿越
  const safeFile = path.basename(fileParam);
  const logFile = path.join(LOGS_DIR, safeFile);

  console.log(`✅ [调试] 日志请求: file=${fileParam}`);
  console.log(`✅ [调试] LOGS_DIR=${LOGS_DIR}`);
  console.log(`✅ [调试] logFile=${logFile}`);
  console.log(`✅ [调试] 文件存在: ${fs.existsSync(logFile)}`);

  // 检查文件是否存在
  if (!fs.existsSync(logFile)) {
    console.log(`✅ [调试] 文件不存在，返回404`);
    res.status(404).json({ success: false, message: `日志文件不存在：${safeFile}` });
    return;
  }

  // SSE 头部
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',  // 禁用 nginx 缓冲
    'Access-Control-Allow-Origin': '*',
    'X-No-Buffering': '1',      // 禁用中间代理缓冲
  });

  console.log(`✅ [日志] 开始推送：${safeFile}`);

  let fileSize = 0;

  // 初始发送：读取文件全部内容
  const sendInitial = () => {
    try {
      const stats = fs.statSync(logFile);
      fileSize = stats.size;

      const content = fs.readFileSync(logFile, 'utf-8');
      let lines = content.split('\n');

      console.log(`✅ [调试] 读取日志完成: ${lines.length} 行 (原始 ${stats.size} 字节)`);

      if (tailOnly) {
        const tailLines = lines.slice(-100);
        res.write(`data: ${JSON.stringify({ type: 'init', lines: tailLines, total: lines.length })}\n\n`);
        console.log(`✅ [调试] 发送尾部 ${tailLines.length} 行`);
      } else {
        res.write(`data: ${JSON.stringify({ type: 'init', lines, total: lines.length })}\n\n`);
        console.log(`✅ [调试] 发送全部 ${lines.length} 行`);
      }
    } catch (err: any) {
      console.log(`✅ [调试] 读取失败: ${err.message}`);
      res.write(`data: ${JSON.stringify({ type: 'error', message: `读取日志失败: ${err.message}` })}\n\n`);
    }
  };

  sendInitial();

  // 定时轮询文件变更（兼容性更好，无需 fs.watch 的跨平台问题）
  const pollInterval = setInterval(() => {
    try {
      const stats = fs.statSync(logFile);
      if (stats.size > fileSize) {
        // 文件有新增内容
        const fd = fs.openSync(logFile, 'r');
        const buffer = Buffer.alloc(stats.size - fileSize);
        fs.readSync(fd, buffer, 0, buffer.length, fileSize);
        fs.closeSync(fd);

        const newContent = buffer.toString('utf-8');
        const newLines = newContent.split('\n').filter(l => l.trim());

        if (newLines.length > 0) {
          res.write(`data: ${JSON.stringify({ type: 'append', lines: newLines })}\n\n`);
        }
        fileSize = stats.size;
      }
    } catch (err) {
      // 文件可能被轮转，忽略错误
    }
  }, 1000); // 每秒检测

  // 心跳保持连接
  const heartbeat = setInterval(() => {
    res.write(':heartbeat\n\n');
  }, 15000);

  // 客户端断开时清理
  req.on('close', () => {
    clearInterval(pollInterval);
    clearInterval(heartbeat);
    console.log(`✅ [日志] 客户端断开：${safeFile}`);
  });
});

/**
 * GET /api/logs/read
 * 读取日志文件内容，返回普通 JSON（无 SSE，兼容 Cloudflare Tunnel）
 * Query: file=backend.log (默认)
 */
router.get('/read', (req: Request, res: Response) => {
  const fileParam = (req.query.file as string) || 'backend.log';
  const safeFile = path.basename(fileParam);
  const logFile = path.join(LOGS_DIR, safeFile);

  if (!fs.existsSync(logFile)) {
    res.json({ success: true, lines: [], total: 0, file: safeFile });
    return;
  }

  try {
    const stats = fs.statSync(logFile);
    const content = fs.readFileSync(logFile, 'utf-8');
    let lines = content.split('\n').filter(l => l.trim());
    const tailLines = lines.slice(-200);
    res.json({ success: true, lines: tailLines, total: lines.length, file: safeFile });
  } catch (err: any) {
    res.json({ success: false, lines: [], message: err.message });
  }
});

/**
 * POST /api/logs/write
 * 前端主动写入日志到 backend.log
 * Body: { message: string, level?: string }
 */
router.post('/write', (req: Request, res: Response) => {
  try {
    const { message, level } = req.body;
    if (!message) {
      res.status(400).json({ success: false, message: 'message 不能为空' });
      return;
    }
    const logLine = `✅ [${level || 'INFO'}] [frontend] ${message}\n`;
    const logFile = path.join(LOGS_DIR, 'backend.log');
    fs.appendFileSync(logFile, logLine, 'utf-8');
    res.json({ success: true });
  } catch (err: any) {
    console.error('✅ 写入日志失败:', err.message);
    res.status(500).json({ success: false, message: err.message });
  }
});

export default router;
