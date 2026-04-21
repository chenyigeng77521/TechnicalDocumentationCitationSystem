/**
 * 文档转换模块
 * 支持将 Word、Excel、PowerPoint、PDF 转换为 Markdown 格式
 */
import { ConversionResult, LineMapping, FileFormat } from '../types.js';
export declare class DocumentConverter {
    private storagePath;
    constructor(storagePath?: string);
    /**
     * 确保存储目录存在
     */
    private ensureDirectories;
    /**
     * 检测文件格式
     */
    detectFormat(filePath: string): FileFormat;
    /**
     * 转换文件为 Markdown
     */
    convert(filePath: string, originalFileName: string): Promise<ConversionResult>;
    /**
     * 转换 Word 文档
     */
    private convertDocx;
    /**
     * 转换 Excel 表格
     */
    private convertXlsx;
    /**
     * 转换 PowerPoint 演示文稿
     */
    private convertPptx;
    /**
     * 转换 PDF 文档
     */
    private convertPdf;
    /**
     * 转换 Markdown 文件
     */
    private convertMd;
    /**
     * HTML 转 Markdown（简化版）
     */
    private htmlToMarkdown;
    /**
     * 构建行映射
     */
    private buildLineMappings;
    /**
     * 获取位置映射
     */
    getMapping(fileId: string): LineMapping[];
}
//# sourceMappingURL=index.d.ts.map