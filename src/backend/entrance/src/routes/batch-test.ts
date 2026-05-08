/**
 * 批量测试路由
 * 上传问题文件 → 解析 id + question → 调用远程批量接口（同步）→ 前端提示完成
 *
 * 存储路径：backend/storage/batchtest/  (上传临时文件)
 * 结果路径：backend/storage/result/     (远程服务写入结果文件)
 */

import { Router, Request, Response } from 'express';
import multer from 'multer';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import csv from 'csv-parser';
import { Readable } from 'stream';
import { config } from '../config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// 日志目录：项目根目录下的 logs/
const LOGS_DIR = path.resolve(__dirname, '../../../../logs');

const router = Router();

// ========== 目录配置（从 config 读取，可环境变量覆盖）==========
const BATCH_TEST_UPLOAD_DIR =
  process.env.BATCH_TEST_UPLOAD_DIR ||
  path.resolve(config.upload.batchTestDir);
const RESULT_DIR =
  process.env.RESULT_DIR ||
  path.resolve(config.storage.resultDir);

// 确保目录存在
function ensureDirs() {
  if (!fs.existsSync(BATCH_TEST_UPLOAD_DIR)) {
    fs.mkdirSync(BATCH_TEST_UPLOAD_DIR, { recursive: true });
    console.log('✅ [批量测试] 创建上传目录:', BATCH_TEST_UPLOAD_DIR);
  }
  if (!fs.existsSync(RESULT_DIR)) {
    fs.mkdirSync(RESULT_DIR, { recursive: true });
    console.log('✅ [批量测试] 创建结果目录:', RESULT_DIR);
  }
}
ensureDirs();

// ========== Multer 配置 ==========
const batchStorage = multer.diskStorage({
  destination: (req, file, cb) => {
    ensureDirs();
    cb(null, BATCH_TEST_UPLOAD_DIR);
  },
  filename: (req, file, cb) => {
    // 保留原始文件名（修复中文乱码）
    const originalName = Buffer.from(file.originalname, 'latin1').toString('utf8');
    cb(null, originalName);
  },
});

const batchUpload = multer({
  storage: batchStorage,
  limits: { fileSize: 100 * 1024 * 1024 }, // 100MB
  fileFilter: (req, file, cb) => {
    const originalName = Buffer.from(file.originalname, 'latin1').toString('utf8');
    const ext = path.extname(originalName).toLowerCase();
    const allowed = ['.json', '.jsonl', '.txt', '.csv', '.md', '.adoc'];
    if (allowed.includes(ext)) {
      cb(null, true);
    } else {
      cb(new Error(`不支持的文件格式：${ext}，只支持 ${allowed.join(', ')}`));
    }
  },
});

// ========== 文件解析函数 ==========

/** 解析 JSON 文件 [{id, question}, ...] */
function parseJSON(content: string): Array<{ id: string; question: string }> {
  const data = JSON.parse(content);
  if (!Array.isArray(data)) throw new Error('JSON 格式错误：根元素必须是数组');
  return data
    .filter((item: any) => item.id !== undefined && item.question !== undefined)
    .map((item: any) => ({ id: String(item.id), question: String(item.question) }));
}

/** 解析 JSONL 文件（每行一个 JSON） */
function parseJSONL(content: string): Array<{ id: string; question: string }> {
  const lines = content.split('\n').filter(l => l.trim());
  const results: Array<{ id: string; question: string }> = [];
  for (const line of lines) {
    try {
      const item = JSON.parse(line.trim());
      if (item.id !== undefined && item.question !== undefined) {
        results.push({ id: String(item.id), question: String(item.question) });
      }
    } catch {
      console.warn(`⚠️ [批量测试] 跳过无效行：${line.substring(0, 50)}`);
    }
  }
  return results;
}

/** 解析 TXT 文件（每行一个 JSON） */
function parseTXT(content: string): Array<{ id: string; question: string }> {
  return parseJSONL(content); // TXT 格式同 JSONL
}

/** 解析 CSV 文件（必须有 id, question 列） */
async function parseCSV(content: string): Promise<Array<{ id: string; question: string }>> {
  const csv = require('csv-parser');
  return new Promise((resolve, reject) => {
    const results: Array<{ id: string; question: string }> = [];
    const { Readable } = require('stream');
    const stream = Readable.from(content);

    stream
      .pipe(csv())
      .on('data', (row: any) => {
        if (row.id !== undefined && row.question !== undefined) {
          results.push({ id: String(row.id), question: String(row.question) });
        }
      })
      .on('end', () => resolve(results))
      .on('error', reject);
  });
}

/**
 * 解析上传文件，提取 id + question 列表
 */
async function parseFile(filePath: string, originalName: string): Promise<Array<{ id: string; question: string }>> {
  const content = fs.readFileSync(filePath, 'utf-8');
  const ext = path.extname(originalName).toLowerCase();

  switch (ext) {
    case '.json':
      return parseJSON(content);
    case '.jsonl':
      return parseJSONL(content);
    case '.txt':
      return parseTXT(content);
    case '.csv':
      return parseCSV(content);
    default:
      throw new Error(`不支持的文件格式：${ext}`);
  }
}

/** 构造 JSONL 格式的请求体 */
function buildJSONLBody(questions: Array<{ id: string; question: string }>): string {
  return questions.map(q => JSON.stringify({ id: q.id, question: q.question })).join('\n');
}

// ========== 路由 ==========

/**
 * POST /api/batch-test/upload
 * 上传批量测试文件，解析后调用远程接口
 */
router.post('/upload', batchUpload.single('file'), async (req: Request, res: Response) => {
  let uploadedFilePath: string | null = null;
  const startTime = Date.now();

  try {
    console.log('✅ [批量测试] 收到上传请求');

    if (!req.file) {
      console.log('✅ [批量测试] 未找到上传文件');
      return res.status(400).json({ success: false, message: '未找到上传文件' });
    }

    uploadedFilePath = req.file.path;
    const originalName = req.file.originalname;
    console.log(`✅ [批量测试] 文件接收成功：${originalName} (${req.file.size} bytes)`);

    // 解析文件
    const questions = await parseFile(uploadedFilePath, originalName);
    if (questions.length === 0) {
      fs.unlinkSync(uploadedFilePath);
      console.log('✅ [批量测试] 文件中未找到有效的 id 和 question');
      return res.status(400).json({ success: false, message: '文件中未找到有效的 id 和 question 字段' });
    }
    console.log(`✅ [批量测试] 解析成功，问题数量：${questions.length}`);

    // 构造远程请求 URL（可通过环境变量 BATCH_QUERY_URL 覆盖）
    const remoteUrl = process.env.BATCH_QUERY_URL || 'http://localhost:8001';
    const jsonlBody = buildJSONLBody(questions);

    console.log(`✅ [批量测试] 调用远程接口：${remoteUrl}`);
    console.log(`📦 [批量测试] 发送数据（只展示前 200 个字符）：${jsonlBody.substring(0, 200)}...`);

    // 同步调用远程批量接口（超时 10 分钟）
    const response = await fetch(remoteUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/jsonl+json' },
      body: jsonlBody,
      signal: AbortSignal.timeout(90 * 60 * 1000),
    });

    // ========== 保存批量测试文件到 data/batchtest ==========
    console.log(`🔍 [调试] process.cwd() = ${process.cwd()}`);
    const resolvedPath = path.resolve(process.cwd(), '..', '..', 'data', 'batchtest');
    console.log(`🔍 [调试] 目标路径 = ${resolvedPath}`);
    const batchtestDir = path.join(process.cwd(), '..', '..', 'data', 'batchtest');
    console.log(`🔍 [调试] uploadedFilePath = ${uploadedFilePath}`);
    try {
      fs.mkdirSync(batchtestDir, { recursive: true });
      console.log(`✅ [批量测试] 目录已创建/存在：${batchtestDir}`);
      const saveFileName = `${Date.now()}_${originalName}`;
      const saveFilePath = path.join(batchtestDir, saveFileName);
      console.log(`🔍 [调试] 准备保存文件到：${saveFilePath}`);
      fs.copyFileSync(uploadedFilePath, saveFilePath);
      console.log(`✅ [批量测试] 文件已保存：${saveFilePath}`);
      // 验证文件是否真的写入了
      if (fs.existsSync(saveFilePath)) {
        console.log(`✅ [批量测试] 验证：文件确实存在！大小=${fs.statSync(saveFilePath).size} bytes`);
      } else {
        console.error(`❌ [批量测试] 验证失败：文件不存在！`);
      }
    } catch (err: any) {
      console.error(`❌ [批量测试] 文件保存失败：${err.message}`);
      console.error(`❌ [批量测试] 错误堆栈：${err.stack}`);
    }

    // 删除临时上传文件
    try { fs.unlinkSync(uploadedFilePath); } catch {}

    if (response.ok) {
      const result = await response.json();
      console.log(`✅ [批量测试] 远程处理成功`, result);

      const duration = ((Date.now() - startTime) / 1000).toFixed(2);
      return res.json({
        success: true,
        message: '批量测试处理完成',
        questionCount: questions.length,
        result,
        duration,
      });
    } else {
      const errorText = await response.text();
      console.error(`✅ [批量测试] 远程处理失败：${response.status} - ${errorText}`);
      return res.status(500).json({
        success: false,
        message: `远程处理失败：${response.status} ${response.statusText}`,
      });
    }
  } catch (error: any) {
    console.error('✅ [批量测试] 处理失败：', error);

    // 清理临时文件
    if (uploadedFilePath) {
      try { fs.unlinkSync(uploadedFilePath); } catch {}
    }

    return res.status(500).json({
      success: false,
      message: `处理失败：${error.message}`,
    });
  }
});

/**
 * GET /api/batch-test/results
 * 获取结果文件列表（分页，每页 5 条）
 */
router.get('/results', (req: Request, res: Response) => {
  try {
    console.log('✅ [批量测试] 获取结果文件列表');

    if (!fs.existsSync(RESULT_DIR)) {
      return res.json({ success: true, files: [], total: 0, page: 1, totalPages: 0 });
    }

    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 5;
    const skip = (page - 1) * limit;

    const allFiles = fs.readdirSync(RESULT_DIR)
      .filter(file => {
        const ext = path.extname(file).toLowerCase();
        return ['.json', '.jsonl', '.csv', '.txt'].includes(ext);
      })
      .map(file => {
        const filePath = path.join(RESULT_DIR, file);
        const stats = fs.statSync(filePath);
        return {
          name: file,
          size: stats.size,
          createdAt: stats.birthtime.toISOString(),
          modifiedAt: stats.mtime.toISOString(),
          downloadUrl: `/api/batch-test/download/${encodeURIComponent(file)}`,
        };
      })
      .sort((a, b) => new Date(b.modifiedAt).getTime() - new Date(a.modifiedAt).getTime());

    const total = allFiles.length;
    const totalPages = Math.ceil(total / limit);
    const paginated = allFiles.slice(skip, skip + limit);

    console.log(`✅ [批量测试] 第 ${page}/${totalPages} 页，共 ${total} 个文件`);

    res.json({
      success: true,
      files: paginated,
      total,
      page,
      limit,
      totalPages,
    });
  } catch (error: any) {
    console.error('✅ [批量测试] 获取结果列表失败：', error);
    res.status(500).json({ success: false, message: `获取失败：${error.message}` });
  }
});

/**
 * GET /api/batch-test/download/:filename
 * 下载结果文件
 */
router.get('/download/:filename', (req: Request, res: Response) => {
  try {
    const filename = decodeURIComponent(req.params.filename);
    const filePath = path.join(RESULT_DIR, filename);

    if (!fs.existsSync(filePath)) {
      console.log(`✅ [批量测试] 文件不存在：${filename}`);
      return res.status(404).json({ success: false, message: '文件不存在' });
    }

    console.log(`✅ [批量测试] 下载文件：${filename}`);
    res.download(filePath, filename, (err) => {
      if (err) console.error(`✅ [批量测试] 下载失败：`, err);
    });
  } catch (error: any) {
    console.error('✅ [批量测试] 下载失败：', error);
    res.status(500).json({ success: false, message: `下载失败：${error.message}` });
  }
});

/**
 * POST /api/batch-test/submit
 * 接收前端解析好的批量测试数据，转发到推理层批量查询服务
 * Body: { items: [{ id, question, domain, answer_type, difficulty }] }
 * Response: { status, succeeded, failed, total, file_path }
 */
router.post('/submit', async (req: Request, res: Response) => {
  try {
    const { items } = req.body;
    if (!items || !Array.isArray(items) || items.length === 0) {
      return res.json({ status: 'error', succeeded: 0, failed: 0, total: 0, message: 'items 不能为空' });
    }

    console.log(`✅ [批量测试] 收到 ${items.length} 条测试数据，第一项：${items[0]?.question?.substring(0, 30)}`);

    // ========== 保存批量测试文件到项目根目录 data/batchtest ==========
    const batchtestDir = path.resolve(process.cwd(), '..', '..', '..', 'data', 'batchtest');
    try {
      if (!fs.existsSync(batchtestDir)) {
        fs.mkdirSync(batchtestDir, { recursive: true });
        console.log(`✅ [批量测试] 创建保存目录: ${batchtestDir}`);
      }
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const saveFileName = `${timestamp}_batch_${items.length}.json`;
      const saveFilePath = path.join(batchtestDir, saveFileName);
      fs.writeFileSync(saveFilePath, JSON.stringify(items, null, 2), 'utf-8');
      console.log(`✅ [批量测试] 文件已保存: ${saveFilePath} (${items.length} 条)`);
    } catch (err: any) {
      console.error(`❌ [批量测试] 保存文件失败: ${err.message}`);
    }
    // ========================================================

    // 构造请求体
    const body = { items };

    // 调用推理层批量查询服务
    const remoteUrl = config.retrieval.batchQueryUrl;
    console.log(`✅ [批量测试] 请求地址: ${remoteUrl}`);
    console.log(`✅ [批量测试] 请求参数: ${JSON.stringify({ items_count: items.length, first_item: items[0] })}`);

    const response = await fetch(remoteUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(90 * 60 * 1000),
    });

    if (response.ok) {
      const result: any = await response.json();
      console.log(`✅ [批量测试] 推理层原始返回:`, JSON.stringify(result, null, 2));
      const succeeded = result.succeeded || 0;
      const failed = result.failed || 0;
      const total = result.total || items.length;
      console.log(`✅ [批量测试] 推理层返回，status=${result.status}, succeeded=${succeeded}, failed=${failed}, total=${total}`);
      return res.json({
        status: result.status || 'success',
        succeeded,
        failed,
        total,
        file_path: result.file_path || '',
      });
    } else {
      const errorText = await response.text();
      const errorMsg = `❌ [批量测试] 推理层错误：${response.status} - ${errorText}`;
      fs.appendFileSync(path.join(LOGS_DIR, 'backend.log'), errorMsg, 'utf-8');
      fs.appendFileSync(path.join(LOGS_DIR, 'backend.log'), errorText, 'utf-8');
      console.error(errorMsg.trim());
      console.error(`❌ [批量测试] 推理层原始响应体:`, errorText);
      return res.json({ status: 'error', succeeded: 0, failed: items.length, total: items.length, message: `推理层返回 ${response.status}` });
    }
  } catch (error: any) {
    console.error('✅ [批量测试] 提交失败：', error);
    console.error('❌ [批量测试] 错误详情：', {
      name: error.name,
      message: error.message,
      code: error.code,
      stack: error.stack?.substring(0, 500)
    });
    return res.json({ status: 'error', succeeded: 0, failed: 0, total: 0, message: `提交失败：${error.message}` });
  }
});

export default router;
