/**
 * 文件上传路由
 */
import { Router } from 'express';
import multer from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { DocumentConverter } from '../converter/index.js';
import { DatabaseManager } from '../database/index.js';
const router = Router();
// Multer 配置
const storage = multer.diskStorage({
    destination: (req, file, cb) => {
        const uploadDir = path.join(process.cwd(), 'storage', 'temp');
        if (!fs.existsSync(uploadDir)) {
            fs.mkdirSync(uploadDir, { recursive: true });
        }
        cb(null, uploadDir);
    },
    filename: (req, file, cb) => {
        const uniqueName = `${uuidv4()}${path.extname(file.originalname)}`;
        cb(null, uniqueName);
    }
});
// 文件过滤
const fileFilter = (req, file, cb) => {
    const allowedFormats = ['.docx', '.xlsx', '.pptx', '.pdf', '.md'];
    const ext = path.extname(file.originalname).toLowerCase();
    if (allowedFormats.includes(ext)) {
        cb(null, true);
    }
    else {
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
router.post('/', upload.array('files', 10), async (req, res) => {
    try {
        const files = req.files;
        const { category, tags } = req.body;
        if (!files || files.length === 0) {
            return res.status(400).json({
                success: false,
                message: '没有上传任何文件'
            });
        }
        const converter = new DocumentConverter();
        const db = new DatabaseManager();
        const uploadedFiles = [];
        for (const file of files) {
            try {
                const fileId = uuidv4();
                const format = converter.detectFormat(file.path);
                console.log(`📤 开始处理文件：${file.originalname}`);
                // 1. 转换文件
                const conversionResult = await converter.convert(file.path, file.originalname);
                // 2. 保存文件记录
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
                    status: 'completed',
                    tags: tags ? (typeof tags === 'string' ? tags.split(',') : tags) : []
                });
                uploadedFiles.push({
                    id: fileId,
                    originalName: file.originalname,
                    originalPath: conversionResult.originalPath,
                    convertedPath: conversionResult.convertedPath,
                    format,
                    size: file.size,
                    uploadTime,
                    status: 'completed',
                    category,
                    tags
                });
                console.log(`✅ 文件处理完成：${file.originalname}`);
                // 删除临时文件
                fs.unlinkSync(file.path);
            }
            catch (error) {
                console.error(`❌ 文件处理失败：${file.originalname}`, error.message);
                // 记录失败文件
                uploadedFiles.push({
                    id: uuidv4(),
                    originalName: file.originalname,
                    error: error.message,
                    status: 'failed'
                });
            }
        }
        db.close();
        res.json({
            success: true,
            files: uploadedFiles,
            message: `成功处理 ${uploadedFiles.filter(f => f.status === 'completed').length} / ${files.length} 个文件`
        });
    }
    catch (error) {
        console.error('❌ 上传失败:', error);
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
router.post('/url', async (req, res) => {
    res.status(501).json({
        success: false,
        message: 'URL 上传功能暂未实现'
    });
});
export default router;
//# sourceMappingURL=upload.js.map