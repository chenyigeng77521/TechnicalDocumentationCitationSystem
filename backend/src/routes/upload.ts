/**
 * 文件上传路由
 * 直接保存文件到配置路径
 */

import { Router, Request, Response } from 'express';
import multer from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { config } from '../config.js';

const router = Router();

// 上传目录
const uploadDir = path.resolve(config.upload.uploadDir);
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

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
        
        console.log(`📤 上传文件：${fixedOriginalName}`);
        
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
        console.error(`❌ 上传失败：`, error.message);
        
        uploadedFiles.push({
          id: uuidv4(),
          originalName: file.originalname,
          error: error.message,
          status: 'failed'
        });
      }
    }

    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.json({
      success: true,
      files: uploadedFiles,
      message: `成功上传 ${uploadedFiles.filter(f => f.status === 'completed').length} / ${files.length} 个文件`
    });

  } catch (error: any) {
    console.error('❌ 上传失败:', error);
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.status(500).json({
      success: false,
      message: error.message || '上传失败'
    });
  }
});

export default router;
