/**
 * 文件上传路由
 * 直接保存文件到配置路径
 */

import { Router, Request, Response } from 'express';
import multer from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { fileURLToPath } from 'url';
import { config } from '../config.js';

// ESM 兼容：定义 __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const router = Router();

// 写入日志到 backend.log
function logToBackend(message: string, level: string = 'INFO') {
  try {
    const logsDir = path.resolve(__dirname, '../../../../logs');
    if (!fs.existsSync(logsDir)) fs.mkdirSync(logsDir, { recursive: true });
    const logLine = `✅ [${level}] [modify-index] ${message}\n`;
    fs.appendFileSync(path.join(logsDir, 'backend.log'), logLine, 'utf-8');
  } catch (e) {
    console.error('[logToBackend] failed:', e);
  }
}

// 上传目录
const uploadDir = path.resolve(config.upload.uploadDir);
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

// 数据根目录（用于知识库列表递归扫描）
const dataRoot = path.resolve(config.dataRoot.path);

/**
 * 修复 Latin-1 编码导致的中文乱码
 */
function fixEncoding(filename: string): string {
  try {
    // 检测是否是 Latin-1 乱码（Buffer 检测）
    const buffer = Buffer.from(filename, 'latin1');
    const decoded = buffer.toString('utf8');
    
    // 如果解码后包含合理的中文字符，说明是乱码
    const hasChinese = /[\u4e00-\u9fa5]/.test(decoded);
    const hasGarbage = /[^\x00-\x7F]/.test(filename);
    
    if (hasGarbage && hasChinese) {
      return decoded;
    }
    return filename;
  } catch {
    return filename;
  }
}

/**
 * 检查文件名是否合法
 */
function isValidFileName(filename: string): { valid: boolean; error?: string } {
  // 空文件名
  if (!filename || filename.trim() === '') {
    return { valid: false, error: '文件名为空' };
  }
  
  // 文件名过长（超过 255 字符）
  if (filename.length > 255) {
    return { valid: false, error: '文件名过长（最多 255 个字符）' };
  }
  
  // 检查非法字符
  const illegalChars = /[<>:"/\\|?*\x00-\x1f]/;
  if (illegalChars.test(filename)) {
    return { valid: false, error: '文件名包含非法字符' };
  }
  
  // 检查保留名称（Windows）
  const reservedNames = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 
                         'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 
                         'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'];
  const nameWithoutExt = filename.split('.')[0].toUpperCase();
  if (reservedNames.includes(nameWithoutExt)) {
    return { valid: false, error: `文件名不能使用系统保留名称` };
  }
  
  // 检查是否以空格或点开头/结尾
  if (/^[\s.]|[\s.]$/.test(filename)) {
    return { valid: false, error: '文件名不能以空格或点开头/结尾' };
  }
  
  // 检查文件名中间是否有点（扩展名前的点是允许的）
  const lastDotIndex = filename.lastIndexOf('.');
  const baseNameOnly = lastDotIndex > 0 ? filename.substring(0, lastDotIndex) : filename;
  if (/\./.test(baseNameOnly)) {
    return { valid: false, error: '文件名中除扩展名外不允许包含点' };
  }
  
  return { valid: true };
}

/**
 * 清理文件名
 */
function sanitizeFileName(fileName: string): string {
  // 先修复编码
  let cleanName = fixEncoding(fileName);
  
  // 替换非法字符
  const illegalChars = /[<>:"/\\|?*\x00-\x1f]/g;
  cleanName = cleanName.replace(illegalChars, '_').trim();
  
  // 移除开头和结尾的点
  cleanName = cleanName.replace(/^\.+|\.+$/g, '');
  
  // 替换路径分隔符
  cleanName = cleanName.replace(/[/\\]/g, '_');
  
  // 替换文件名中间的点（保留扩展名前的点）
  const lastDotIndex = cleanName.lastIndexOf('.');
  if (lastDotIndex > 0) {
    const name = cleanName.substring(0, lastDotIndex);
    const ext = cleanName.substring(lastDotIndex);
    cleanName = name.replace(/\./g, '_') + ext;
  }
  
  return cleanName || 'unnamed_file';
}

// Multer 配置
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    // 每次上传时确保目录存在，如果不存在则创建
    if (!fs.existsSync(uploadDir)) {
      try {
        fs.mkdirSync(uploadDir, { recursive: true });
        console.log(`✅ 创建上传目录：${uploadDir}`);
      } catch (error: any) {
        console.error(`✅ 创建上传目录失败：${uploadDir}`, error.message);
        cb(error, undefined as any);
        return;
      }
    }
    cb(null, uploadDir);
  },
  filename: (req, file, cb) => {
    // 修复中文乱码，生成安全文件名
    const fixedName = fixEncoding(file.originalname);
    const safeName = sanitizeFileName(fixedName);
    cb(null, safeName);
  }
});

// 文件过滤
const fileFilter = (req: Request, file: Express.Multer.File, cb: multer.FileFilterCallback) => {
  // 修复文件名编码
  const fixedName = fixEncoding(file.originalname);
  const ext = path.extname(fixedName).toLowerCase();
  
  // 检查文件名合法性
  const validation = isValidFileName(fixedName);
  if (!validation.valid) {
    cb(new Error(`文件名不合法：${validation.error} - ${fixedName}`));
    return;
  }
  
  // 检查文件格式
  if (config.upload.allowedFormats.includes(ext)) {
    cb(null, true);
  } else {
    cb(new Error(`不支持的文件格式：${ext}，支持的格式：${config.upload.allowedFormats.join(', ')}`));
  }
};

const upload = multer({
  storage,
  fileFilter,
  limits: {
    fileSize: config.upload.maxFileSize * 1024 * 1024
  }
});

/**
 * POST /api/upload
 * 上传文件
 */
router.post('/', upload.array('files', config.upload.maxFiles), async (req: Request, res: Response) => {
  try {
    const files = req.files as Express.Multer.File[];
    
    if (!files || files.length === 0) {
      return res.status(400).json({
        success: false,
        message: '没有上传任何文件'
      });
    }

    const uploadedFiles: any[] = [];

    for (const file of files) {
      try {
        // 修复文件名编码
        const fixedOriginalName = fixEncoding(file.originalname);
        const ext = path.extname(fixedOriginalName).replace('.', '');
        
        console.log(`✅ 上传文件：${fixedOriginalName}`);
        
        uploadedFiles.push({
          id: uuidv4(),
          originalName: fixedOriginalName,
          originalPath: file.path,
          format: ext,
          size: file.size,
          uploadTime: new Date().toISOString(),
          status: 'completed'
        });
        
        console.log(`✅ 上传完成：${fixedOriginalName}`);
        
      } catch (error: any) {
        console.error(`✅ 上传失败：`, error.message);
        
        uploadedFiles.push({
          id: uuidv4(),
          originalName: file.originalname,
          error: error.message,
          status: 'failed'
        });
      }
    }

    // 上传完成后批量调用索引创建服务
    let indexResult: any = null;
    const completedFiles = uploadedFiles.filter(f => f.status === 'completed');
    if (completedFiles.length > 0) {
      try {
        // 收集所有文件的相对路径
        const relPaths = completedFiles.map(uf => path.relative(dataRoot, uf.originalPath));
        const indexUrl = `http://localhost:3003/index`;
        logToBackend(`上传后批量请求索引服务: ${JSON.stringify(relPaths)} → POST ${indexUrl}`);
        console.log(`✅ [上传] 批量通知索引服务：POST ${indexUrl}`);

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 300000);
        const response = await fetch(indexUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ add: relPaths }),
          signal: controller.signal,
        });
        clearTimeout(timeout);
        const data = response.ok ? await response.json() : null;
        logToBackend(`上传后批量索引服务响应: status=${response.status} data=${JSON.stringify(data)}`);
        console.log(`✅ [上传] 批量索引服务响应：${JSON.stringify(data)}`);
        const idxData: any = data;
        const addStatus = (idxData?.status || idxData?.results?.[0]?.status || '').toString();
        if (response.ok && addStatus === 'indexed') {
          indexResult = { success: true, result: data };
        } else {
          indexResult = { success: false, error: `状态异常: ${addStatus || '未知'}` };
        }
      } catch (fetchError: any) {
        const errMsg = fetchError.message || '未知错误';
        logToBackend(`上传后批量索引服务请求失败: ${errMsg}`, 'ERROR');
        console.error(`✅ [上传] 批量索引服务调用失败：`, errMsg);
        indexResult = { success: false, error: errMsg };
      }
    }

    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.json({
      success: true,
      files: uploadedFiles,
      indexResult,
      message: `成功上传 ${completedFiles.length} / ${files.length} 个文件`
    });

  } catch (error: any) {
    console.error('✅ 上传失败:', error);
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.status(500).json({
      success: false,
      message: error.message || '上传失败'
    });
  }
});

/**
 * 递归遍历目录下所有文件
 */
function walkDir(dir: string, baseDir: string): any[] {
  const results: any[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'batchtest') {
        continue;
      }
      results.push(...walkDir(fullPath, baseDir));
    } else if (entry.isFile()) {
      const stats = fs.statSync(fullPath);
      // 相对 data/ 的相对路径，如 documents/subdir/file.pdf
      const relPath = path.relative(baseDir, fullPath);
      results.push({
        name: entry.name,
        path: fullPath,
        displayPath: relPath,                // 相对路径，用于 API 调用
        size: stats.size,
        createdAt: stats.birthtime,
        modifiedAt: stats.mtime,
        downloadUrl: `/api/upload/download/${encodeURIComponent(relPath)}`,
      });
    }
  }
  return results;
}

/**
 * 获取 data/ 目录下所有子目录的文件列表
 * GET /api/upload/raw-files?page=1&limit=10
 */
router.get('/raw-files', (req, res) => {
  try {
    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 10;
    const skip = (page - 1) * limit;

    // 如果目录不存在，返回空列表
    if (!fs.existsSync(dataRoot)) {
      console.log(`✅ 数据根目录不存在：${dataRoot}，返回空列表`);
      return res.json({
        success: true,
        files: [],
        total: 0,
        page,
        limit,
        totalPages: 0
      });
    }

    const allFiles = walkDir(dataRoot, dataRoot)
      .sort((a, b) => b.modifiedAt.getTime() - a.modifiedAt.getTime());

    const total = allFiles.length;
    const paginatedFiles = allFiles.slice(skip, skip + limit);

    res.json({
      success: true,
      files: paginatedFiles,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit)
    });

  } catch (error: any) {
    console.error('✅ 获取文档列表失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '获取文档列表失败'
    });
  }
});

/**
 * GET /api/upload/download/:filename
 * 下载 data/ 目录下的文件（支持子目录路径）
 */
router.get('/download/:filename', (req: Request, res: Response) => {
  try {
    const filename = decodeURIComponent(req.params.filename);
    const filePath = path.resolve(dataRoot, filename);

    // 安全检查：确保文件在 dataRoot 内，防止路径穿越
    if (!filePath.startsWith(dataRoot)) {
      return res.status(403).json({ success: false, message: '非法路径' });
    }

    if (!fs.existsSync(filePath)) {
      console.log(`✅ [上传] 文件不存在：${filename}`);
      return res.status(404).json({ success: false, message: '文件不存在' });
    }

    console.log(`✅ [上传] 下载文件：${filename}`);
    res.download(filePath, path.basename(filename), (err) => {
      if (err) console.error(`✅ [上传] 下载失败：`, err);
    });
  } catch (error: any) {
    console.error('✅ [上传] 下载失败：', error);
    res.status(500).json({ success: false, message: `下载失败：${error.message}` });
  }
});

/**
 * DELETE /api/upload/delete
 * 删除 data/ 目录下的文件（先调索引，成功后再删文件）
 */
router.delete('/delete', async (req: Request, res: Response) => {
  try {
    const { path: filePath } = req.body;
    if (!filePath) {
      return res.status(400).json({ success: false, message: '缺少 path 参数' });
    }

    const fullPath = path.resolve(dataRoot, filePath);
    // 安全检查：确保文件在 dataRoot 内
    if (!fullPath.startsWith(dataRoot)) {
      return res.status(403).json({ success: false, message: '非法路径' });
    }

    if (!fs.existsSync(fullPath)) {
      return res.status(404).json({ success: false, message: '文件不存在' });
    }
    console.log(`✅ [删除] 文件确认存在: ${fullPath}`);

    // 第一步：先调用索引服务删除索引
    try {
      const encodedPath = encodeURIComponent(filePath);
      const indexUrl = `http://localhost:3003/index?delete=${encodedPath}`;
      console.log(`✅ [删除] 通知索引服务：POST ${indexUrl}`);
      logToBackend(`删除请求索引服务: ${filePath} → POST ${indexUrl}`);

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 300000);
      const response = await fetch(indexUrl, {
        method: 'POST',
        headers: { 'accept': 'application/json' },
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!response.ok) {
        const errMsg = `索引服务 HTTP ${response.status}`;
        logToBackend(`删除索引服务 HTTP 错误: ${errMsg}`, 'ERROR');
        console.error(`✅ [删除] 索引服务 HTTP 错误: ${errMsg}`);
        return res.status(502).json({ success: false, message: '删除失败：索引服务错误', deleteIndexResult: { success: false, error: errMsg } });
      }

      const delData: any = await response.json();
      logToBackend(`删除索引服务响应: status=${response.status} data=${JSON.stringify(delData)}`);
      console.log(`✅ [删除] 索引服务响应: ${JSON.stringify(delData)}`);

      // 判断删除状态：根级 status 或 results[0].status === "deleted"
      const deleteStatus = (delData?.status || delData?.results?.[0]?.status || '').toString();
      if (deleteStatus !== 'deleted') {
        const errMsg = `索引服务返回状态 ${deleteStatus || '未知'}`;
        logToBackend(`删除索引服务状态错误: ${errMsg}`, 'ERROR');
        console.error(`✅ [删除] 索引服务状态错误: ${errMsg}`);
        return res.status(502).json({ success: false, message: '删除失败：索引服务返回异常状态', deleteIndexResult: { success: false, error: errMsg } });
      }

      console.log(`✅ [删除] 索引服务返回 deleted，准备删除本地文件: ${fullPath}`);
    } catch (fetchError: any) {
      const errMsg = fetchError.message || '未知错误';
      logToBackend(`删除索引服务请求异常: ${errMsg}`, 'ERROR');
      console.error('✅ [删除] 索引服务请求异常:', errMsg);
      return res.status(502).json({ success: false, message: '删除失败：索引服务不可用', deleteIndexResult: { success: false, error: errMsg } });
    }

    // 第二步：索引成功，再删除本地文件
    try {
      fs.unlinkSync(fullPath);
      const stillExists = fs.existsSync(fullPath);
      if (stillExists) {
        console.error(`✅ [删除] ⚠️ fs.unlinkSync 执行后文件仍存在: ${fullPath}`);
        return res.status(500).json({ success: false, message: '删除失败：文件删除后仍存在' });
      }
      console.log(`✅ [删除] 文件已删除: ${filePath}`);
    } catch (unlinkError: any) {
      console.error(`✅ [删除] fs.unlinkSync 异常: ${unlinkError.message}`);
      return res.status(500).json({ success: false, message: `删除失败：${unlinkError.message}` });
    }

    res.json({ success: true, message: '删除成功', deleteIndexResult: { success: true } });
  } catch (error: any) {
    console.error('✅ [上传] 删除失败：', error);
    res.status(500).json({ success: false, message: `删除失败：${error.message}` });
  }
});

/**
 * GET /api/upload/read
 * 读取 data/ 目录下的文件内容
 * 查询参数：path（相对路径）
 */
router.get('/read', (req: Request, res: Response) => {
  try {
    const filePath = req.query.path as string;
    if (!filePath) {
      return res.status(400).json({ success: false, message: '缺少 path 参数' });
    }

    const fullPath = path.resolve(dataRoot, filePath);
    console.log(`✅ [上传] 读取请求: path="${filePath}" → fullPath="${fullPath}"`);
    if (!fullPath.startsWith(dataRoot)) {
      return res.status(403).json({ success: false, message: '非法路径' });
    }

    if (!fs.existsSync(fullPath)) {
      console.log(`✅ [上传] 文件不存在: ${fullPath}`);
      return res.status(404).json({ success: false, message: '文件不存在' });
    }

    const content = fs.readFileSync(fullPath, 'utf-8');
    console.log(`✅ [上传] 读取文件成功：${filePath} (${content.length} 字节)`);
    console.log(`✅ [上传] 读取文件：${filePath} (${content.length} 字节)`);
    res.json({ success: true, content, path: filePath, name: path.basename(filePath) });
  } catch (error: any) {
    console.error('✅ [上传] 读取文件失败：', error);
    res.status(500).json({ success: false, message: `读取文件失败：${error.message}` });
  }
});

/**
 * POST /api/upload/save
 * 保存文件内容到 data/ 目录
 * 请求体：{ path: string, content: string }
 */
router.post('/save', (req: Request, res: Response) => {
  try {
    const { path: filePath, content } = req.body;
    if (!filePath || content === undefined) {
      return res.status(400).json({ success: false, message: '缺少 path 或 content 参数' });
    }

    const fullPath = path.resolve(dataRoot, filePath);
    if (!fullPath.startsWith(dataRoot)) {
      return res.status(403).json({ success: false, message: '非法路径' });
    }

    // 确保父目录存在
    const dir = path.dirname(fullPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    fs.writeFileSync(fullPath, content, 'utf-8');
    const stats = fs.statSync(fullPath);
    console.log(`✅ [上传] 保存文件：${filePath} (${content.length} 字节)`);
    res.json({ success: true, size: stats.size, message: '保存成功' });
  } catch (error: any) {
    console.error('✅ [上传] 保存文件失败：', error);
    res.status(500).json({ success: false, message: `保存文件失败：${error.message}` });
  }
});

/**
 * POST /api/upload/modify-index
 * 通知索引服务重新索引文件
 * 请求体：{ path: string }（dataRoot 下的相对路径）
 */
router.post('/modify-index', async (req: Request, res: Response) => {
  try {
    const { path: filePath } = req.body;
    if (!filePath) {
      logToBackend(`请求缺少 path 参数`, 'ERROR');
      return res.status(400).json({ success: false, message: '缺少 path 参数' });
    }

    const fullPath = path.resolve(dataRoot, filePath);
    if (!fullPath.startsWith(dataRoot)) {
      logToBackend(`非法路径: ${filePath}`, 'ERROR');
      return res.status(403).json({ success: false, message: '非法路径' });
    }

    if (!fs.existsSync(fullPath)) {
      logToBackend(`文件不存在: ${filePath}`, 'ERROR');
      return res.status(404).json({ success: false, message: '文件不存在' });
    }

    const encodedPath = encodeURIComponent(filePath);
    const indexUrl = `http://localhost:3003/index?modify=${encodedPath}`;
    logToBackend(`请求索引服务: ${filePath} → POST ${indexUrl}`);
    console.log(`✅ [上传] 通知索引服务：POST ${indexUrl}`);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 300000);

    try {
      const response = await fetch(indexUrl, {
        method: 'POST',
        headers: { 'accept': 'application/json' },
        signal: controller.signal,
      });
      clearTimeout(timeout);
      const data = await response.json();
      const idxResp: any = data;
      logToBackend(`索引服务响应: status=${response.status} data=${JSON.stringify(idxResp)}`);
      console.log(`✅ [上传] 索引服务响应：${JSON.stringify(idxResp)}`);

      const modifyStatus = (idxResp?.status || idxResp?.results?.[0]?.status || '').toString();
      if (modifyStatus !== 'indexed') {
        res.json({ success: false, message: '索引更新失败', indexResult: idxResp });
      } else {
        res.json({ success: true, indexResult: idxResp, message: '索引更新已通知' });
      }
    } catch (fetchError: any) {
      clearTimeout(timeout);
      const errMsg = fetchError.message || '未知错误';
      logToBackend(`索引服务请求失败: status=0 error=${errMsg}`, 'ERROR');
      console.error('✅ [上传] 索引服务调用失败：', errMsg);
      res.json({ success: false, indexResult: { warning: `索引服务调用失败: ${errMsg}` }, message: '索引更新失败' });
    }
  } catch (error: any) {
    logToBackend(`modify-index 异常: ${error.message}`, 'ERROR');
    console.error('✅ [上传] modify-index 失败：', error);
    res.status(500).json({ success: false, message: `索引更新失败：${error.message}` });
  }
});

export default router;
