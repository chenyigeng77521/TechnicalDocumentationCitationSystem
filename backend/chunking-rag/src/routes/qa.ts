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

/**
 * DELETE /api/qa/files/:filename
 * 级联删除：raw/ 物理文件 + DB file 记录 + chunks + converted/mappings sidecar
 * Best-effort 策略（见 spec D3）：DB 失败 throw；raw/sidecar 失败 warn 不回滚
 */
router.delete('/files/:filename', (req: Request, res: Response) => {
  const { filename } = req.params;
  const db = new DatabaseManager();
  const uploadDir = path.resolve(process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw'));
  const convertedDir = './storage/converted';
  const mappingsDir = './storage/mappings';

  // 防路径穿越：:filename 必须是单一文件名，不能含路径分隔符或 ..
  if (filename.includes('/') || filename.includes('\\') || filename.includes('..')) {
    db.close();
    return res.status(400).json({
      success: false,
      message: '文件名非法'
    });
  }

  const rawPath = path.join(uploadDir, filename);
  // 双重保护：resolve 后必须仍在 uploadDir 里
  if (!path.resolve(rawPath).startsWith(uploadDir + path.sep) && path.resolve(rawPath) !== uploadDir) {
    db.close();
    return res.status(400).json({
      success: false,
      message: '文件名非法'
    });
  }
  const rawExists = fs.existsSync(rawPath);

  // 1. 查 DB：同名 original_name 的记录（理论上 0 或 1 条）
  const allFiles = db.getAllFiles();
  const matches = allFiles.filter(f => f.original_name === filename);

  if (!rawExists && matches.length === 0) {
    db.close();
    return res.status(404).json({
      success: false,
      message: '文件不存在'
    });
  }

  let warning: string | undefined;

  // 2. DB 删除：放 try/catch，失败直接 500
  try {
    for (const f of matches) {
      db.deleteFileChunks(f.id);
      db.deleteFile(f.id);
    }
  } catch (dbErr: any) {
    db.close();
    console.error('❌ DB 删除失败:', dbErr);
    return res.status(500).json({
      success: false,
      message: `DB 删除失败: ${dbErr.message}`
    });
  }

  // 3. raw 文件删除：失败 warn 不报错
  if (rawExists) {
    try {
      fs.unlinkSync(rawPath);
    } catch (rawErr: any) {
      console.warn(`⚠️ raw 文件删除失败: ${rawErr.message}`);
      warning = `DB 已清理，但 raw 文件未能删除：${rawErr.message}`;
    }
  }

  // 4. sidecar 删除（converted + mappings）：失败 warn 不报错
  for (const f of matches) {
    for (const sidecarDir of [convertedDir, mappingsDir]) {
      const ext = sidecarDir === convertedDir ? '.md' : '.json';
      const sidecarPath = path.join(sidecarDir, `${f.id}${ext}`);
      if (fs.existsSync(sidecarPath)) {
        try {
          fs.unlinkSync(sidecarPath);
        } catch (sideErr: any) {
          console.warn(`⚠️ sidecar 删除失败 ${sidecarPath}: ${sideErr.message}`);
        }
      }
    }
  }

  db.close();

  const response: any = {
    success: true,
    message: !rawExists && matches.length > 0
      ? '文件不存在但清理了 DB 记录'
      : '文件已删除'
  };
  if (warning) response.warning = warning;

  res.json(response);
});

export default router;
