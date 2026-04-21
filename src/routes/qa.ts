/**
 * 问答路由
 */

import { Router, Request, Response } from 'express';
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
 * 获取可用文件列表
 */
router.get('/files', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const files = db.getAllFiles({ status: 'completed' });
    
    db.close();

    res.json({
      success: true,
      files: files.map(f => ({
        id: f.id,
        name: f.original_name,
        format: f.format,
        size: f.size,
        uploadTime: f.upload_time,
        category: f.category
      })),
      total: files.length
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
 * 获取系统统计信息
 */
router.get('/stats', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const stats = db.getStats();
    
    db.close();

    res.json({
      success: true,
      stats: {
        fileCount: stats.fileCount,
        chunkCount: stats.chunkCount,
        indexedCount: stats.chunkCount // TODO: 实际应统计带向量的块数
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
