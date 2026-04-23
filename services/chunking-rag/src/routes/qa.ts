/**
 * 问答路由
 */

import { Router, Request, Response } from 'express';
import * as fs from 'fs';
import * as path from 'path';
import { DatabaseManager } from '../database/index.js';
import { Retriever } from '../retriever/index.js';
import { QAAgent } from '../qa/index.js';
import { QARequest } from '../types.js';

const router = Router();

let qaAgent: QAAgent | null = null;

/**
 * 初始化问答服务（单例）
 */
function getQAAgent(): QAAgent {
  if (!qaAgent) {
    const db = new DatabaseManager();
    const retriever = new Retriever(db, {
      llmApiKey: process.env.LLM_API_KEY,
      llmBaseUrl: process.env.LLM_BASE_URL,
      embeddingModel: process.env.EMBEDDING_MODEL || 'text-embedding-3-large',
      embeddingDimension: parseInt(process.env.EMBEDDING_DIMENSION || '1536'),
      topKDefault: parseInt(process.env.TOP_K_DEFAULT || '5')
    });
    
    qaAgent = new QAAgent(db, retriever, {
      llmApiKey: process.env.LLM_API_KEY,
      llmBaseUrl: process.env.LLM_BASE_URL,
      llmModel: process.env.LLM_MODEL || 'gpt-4-turbo',
      strictModeDefault: true
    });
  }
  
  return qaAgent;
}

/**
 * POST /api/qa/ask
 * 回答问题
 */
router.post('/ask', async (req: Request, res: Response) => {
  try {
    const request: QARequest = {
      question: req.body.question,
      topK: req.body.topK || 5,
      strictMode: req.body.strictMode !== false
    };

    if (!request.question || request.question.trim() === '') {
      return res.status(400).json({
        success: false,
        message: '问题不能为空'
      });
    }

    console.log(`❓ 收到问题：${request.question}`);
    
    const qa = getQAAgent();
    const response = await qa.answer(request);

    res.json({
      success: true,
      ...response
    });

  } catch (error: any) {
    console.error('❌ 问答失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '问答处理失败'
    });
  }
});

/**
 * POST /api/qa/search
 * 仅检索，不生成回答
 */
router.post('/search', async (req: Request, res: Response) => {
  try {
    const { query, topK, filters } = req.body;

    if (!query || query.trim() === '') {
      return res.status(400).json({
        success: false,
        message: '查询不能为空'
      });
    }

    const db = new DatabaseManager();
    const retriever = new Retriever(db, {
      llmApiKey: process.env.LLM_API_KEY,
      llmBaseUrl: process.env.LLM_BASE_URL
    });

    const response = await retriever.search({
      query,
      topK: topK || 5,
      filters
    });

    db.close();

    res.json({
      success: true,
      ...response
    });

  } catch (error: any) {
    console.error('❌ 检索失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '检索失败'
    });
  }
});

/**
 * GET /api/qa/files
 * 前端契约：{name, size, mtime} + 兼容字段 {id, format, uploadTime, category}
 * mtime 从磁盘 raw/ 文件读取；其他字段来自 DB
 */
router.get('/files', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const files = db.getAllFiles({ status: 'completed' });

    const uploadDir = path.resolve(process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw'));

    const responseFiles = files.map(f => {
      // mtime 从磁盘读（raw/<original_name>）
      let mtime = f.upload_time;  // fallback 用 upload_time
      try {
        const rawPath = path.join(uploadDir, f.original_name);
        if (fs.existsSync(rawPath)) {
          mtime = fs.statSync(rawPath).mtime.toISOString();
        }
      } catch {
        // best-effort
      }

      return {
        // 前端 page.tsx 和 files/page.tsx 都需要的字段
        name: f.original_name,
        size: f.size,
        mtime,
        // 兼容字段
        id: f.id,
        format: f.format,
        uploadTime: f.upload_time,
        category: f.category
      };
    });

    db.close();

    res.json({
      success: true,
      files: responseFiles,
      total: responseFiles.length
    });
  } catch (error: any) {
    console.error('❌ 获取文件列表失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * GET /api/qa/stats
 * 前端契约：顶层 totalFiles 字段（frontend page.tsx 读 data.totalFiles）
 * 兼容字段：stats.fileCount/chunkCount/indexedCount（v1 API）
 */
router.get('/stats', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const stats = db.getStats();

    db.close();

    res.json({
      success: true,
      // 前端 page.tsx 期望的字段
      totalFiles: stats.fileCount,
      // 兼容 v1 老字段
      stats: {
        fileCount: stats.fileCount,
        chunkCount: stats.chunkCount,
        indexedCount: stats.chunkCount
      }
    });
  } catch (error: any) {
    console.error('❌ 获取统计信息失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * POST /api/qa/index
 * 触发向量化索引
 */
router.post('/index', async (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();

    // 守卫：无可索引 chunks 时直接返回 warning，避免误报成功
    const stats = db.getStats();
    if (stats.chunkCount === 0) {
      db.close();
      return res.json({
        success: false,
        warning: '数据库中无可索引的 chunks，请先上传并切分文档'
      });
    }

    const retriever = new Retriever(db, {
      llmApiKey: process.env.LLM_API_KEY,
      llmBaseUrl: process.env.LLM_BASE_URL
    });

    console.log('📚 开始批量向量化...');
    await retriever.indexAllFiles();

    db.close();

    res.json({
      success: true,
      message: '向量化索引完成'
    });

  } catch (error: any) {
    console.error('❌ 向量化失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

export default router;
