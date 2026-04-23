/**
 * 文件上传路由
 */

import { Router, Request, Response } from 'express';
import multer from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { DocumentConverter } from '../converter/index.js';
import { chunkDocument } from '../converter/chunker.js';
import { DatabaseManager } from '../database/index.js';
import { FileFormat, FileStatus } from '../types.js';
import * as dotenv from 'dotenv';
dotenv.config();

const router = Router();

// Multer 配置
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const uploadDir = process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw');
    const resolvedDir = path.resolve(uploadDir);
    if (!fs.existsSync(resolvedDir)) {
      fs.mkdirSync(resolvedDir, { recursive: true });
    }
    cb(null, resolvedDir);
  },
  filename: (req, file, cb) => {
    // 文件名策略在 Task 4 处理；此步仍用 UUID 作为过渡
    const uniqueName = `${uuidv4()}${path.extname(file.originalname)}`;
    cb(null, uniqueName);
  }
});

// 文件过滤
const fileFilter = (req: Request, file: Express.Multer.File, cb: multer.FileFilterCallback) => {
  const allowedFormats = ['.docx', '.xlsx', '.pptx', '.pdf', '.md'];
  const ext = path.extname(file.originalname).toLowerCase();
  
  if (allowedFormats.includes(ext)) {
    cb(null, true);
  } else {
    cb(new Error(`不支持的文件格式：${ext}`));
  }
};

const upload = multer({
  storage,
  fileFilter,
  limits: {
    fileSize: 50 * 1024 * 1024 // 50MB
  }
});

/**
 * POST /api/upload
 * 上传文件
 */
router.post('/', upload.array('files', 10), async (req: Request, res: Response) => {
  try {
    const files = req.files as Express.Multer.File[];
    const { category, tags } = req.body;
    
    if (!files || files.length === 0) {
      return res.status(400).json({
        success: false,
        message: '没有上传任何文件'
      });
    }

    const converter = new DocumentConverter();
    const db = new DatabaseManager();
    const uploadedFiles: any[] = [];

    for (const file of files) {
      try {
        const fileId = uuidv4();
        const format = converter.detectFormat(file.path);

        console.log(`📤 开始处理文件：${file.originalname}`);

        // 1. 转换文件
        const conversionResult = await converter.convert(file.path, file.originalname);

        // 2. 先写父表（status='converting'，防止出现 completed + chunks=0 灰态）
        const uploadTime = new Date().toISOString();
        db.insertFile({
          id: fileId,
          original_name: file.originalname,
          original_path: conversionResult.originalPath,
          converted_path: conversionResult.convertedPath,
          format,
          size: file.size,
          upload_time: uploadTime,
          category: category || '',
          status: 'converting',
          tags: tags ? (typeof tags === 'string' ? tags.split(',') : tags) : []
        });

        // 3. 切分并写子表
        try {
          const chunks = chunkDocument({
            fileId,
            format,
            mdContent: conversionResult.mdContent,
            lineMappings: conversionResult.lineMappings
          });
          db.insertChunks(chunks);
          console.log(`✅ 切分完成：${chunks.length} 个 chunk`);

          // 4. 切分成功后标记 completed
          db.updateFileStatus(fileId, 'completed');
        } catch (chunkErr: any) {
          try {
            db.updateFileStatus(fileId, 'failed');
          } catch (statusErr: any) {
            console.error(`⚠️ 无法将 ${fileId} 标记为 failed:`, statusErr.message);
          }
          throw chunkErr;
        }

        uploadedFiles.push({
          id: fileId,
          originalName: file.originalname,
          originalPath: conversionResult.originalPath,
          convertedPath: conversionResult.convertedPath,
          format,
          size: file.size,
          uploadTime,
          status: 'completed' as FileStatus,
          category,
          tags
        });

        console.log(`✅ 文件处理完成：${file.originalname}`);

        // 删除临时文件
        fs.unlinkSync(file.path);

      } catch (error: any) {
        console.error(`❌ 文件处理失败：${file.originalname}`, error.message);
        
        // 记录失败文件
        uploadedFiles.push({
          id: uuidv4(),
          originalName: file.originalname,
          error: error.message,
          status: 'failed' as FileStatus
        });
      }
    }

    db.close();

    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.json({
      success: true,
      files: uploadedFiles,
      message: `成功处理 ${uploadedFiles.filter(f => f.status === 'completed').length} / ${files.length} 个文件`
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

/**
 * POST /api/upload/url
 * 从 URL 上传文件
 */
router.post('/url', async (req: Request, res: Response) => {
  res.status(501).json({
    success: false,
    message: 'URL 上传功能暂未实现'
  });
});

export default router;
