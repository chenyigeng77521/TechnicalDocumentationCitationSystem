/**
 * 文件管理路由
 */

import { Router, Request, Response } from 'express';
import * as path from 'path';
import * as fs from 'fs';
import { config } from '../config.js';

const router = Router();

// 获取上传目录
function getUploadDir(): string {
  return path.resolve(config.upload.uploadDir);
}

/**
 * 修复 Latin-1 编码导致的中文乱码
 */
function fixEncoding(filename: string): string {
  try {
    const buffer = Buffer.from(filename, 'latin1');
    const decoded = buffer.toString('utf8');
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
 * GET /api/qa/files
 * 获取已上传文件列表
 */
router.get('/files', (req: Request, res: Response) => {
  try {
    const uploadDir = getUploadDir();
    
    if (!fs.existsSync(uploadDir)) {
      return res.json({
        success: true,
        files: [],
        total: 0
      });
    }

    const files = fs.readdirSync(uploadDir).map(filename => {
      const filePath = path.join(uploadDir, filename);
      const stats = fs.statSync(filePath);
      
      // 提取原始文件名（去掉 UUID 前缀）
      let originalName = filename.replace(/^[a-f0-9-]{36}_/, '');
      
      // 修复文件名编码
      originalName = fixEncoding(originalName);
      
      const ext = path.extname(originalName).replace('.', '');
      
      return {
        id: filename,
        name: originalName,
        format: ext || 'unknown',
        size: stats.size,
        uploadTime: stats.birthtime.toISOString(),
        category: ''
      };
    });

    res.json({
      success: true,
      files,
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
    const uploadDir = getUploadDir();
    let fileCount = 0;
    let totalSize = 0;
    
    if (fs.existsSync(uploadDir)) {
      const files = fs.readdirSync(uploadDir);
      fileCount = files.length;
      
      for (const file of files) {
        const filePath = path.join(uploadDir, file);
        const stats = fs.statSync(filePath);
        totalSize += stats.size;
      }
    }

    res.json({
      success: true,
      totalFiles: fileCount,
      stats: {
        fileCount,
        totalSize,
        uploadDir: config.upload.uploadDir
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
 * DELETE /api/qa/files/:filename
 * 删除指定文件
 */
router.delete('/files/:filename', (req: Request, res: Response) => {
  try {
    const { filename } = req.params;
    const uploadDir = getUploadDir();
    const filePath = path.join(uploadDir, filename);
    
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({
        success: false,
        message: '文件不存在'
      });
    }

    fs.unlinkSync(filePath);
    
    res.json({
      success: true,
      message: '文件已删除'
    });

  } catch (error: any) {
    console.error('❌ 删除文件失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

export default router;
