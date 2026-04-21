/**
 * 文档转换模块
 * 支持将 Word、Excel、PowerPoint、PDF 转换为 Markdown 格式
 */

import * as fs from 'fs';
import * as path from 'path';
import { v4 as uuidv4 } from 'uuid';
import mammoth from 'mammoth';
import XLSX from 'xlsx';
import pdfParse from 'pdf-parse';
import { ConversionResult, LineMapping, FileFormat } from '../types.js';

export class DocumentConverter {
  private storagePath: string;

  constructor(storagePath: string = './storage') {
    this.storagePath = storagePath;
    this.ensureDirectories();
  }

  /**
   * 确保存储目录存在
   */
  private ensureDirectories(): void {
    const dirs = [
      path.join(this.storagePath, 'original'),
      path.join(this.storagePath, 'converted'),
      path.join(this.storagePath, 'mappings')
    ];
    
    for (const dir of dirs) {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }
  }

  /**
   * 检测文件格式
   */
  detectFormat(filePath: string): FileFormat {
    const ext = path.extname(filePath).toLowerCase();
    
    switch (ext) {
      case '.docx':
        return 'docx';
      case '.xlsx':
        return 'xlsx';
      case '.pptx':
        return 'pptx';
      case '.pdf':
        return 'pdf';
      case '.md':
        return 'md';
      default:
        throw new Error(`不支持的文件格式：${ext}`);
    }
  }

  /**
   * 转换文件为 Markdown
   */
  async convert(filePath: string, originalFileName: string): Promise<ConversionResult> {
    const format = this.detectFormat(filePath);
    const fileId = uuidv4();
    
    console.log(`🔄 开始转换文件：${originalFileName} (格式：${format})`);
    
    let mdContent: string;
    let lineMappings: LineMapping[] = [];
    
    switch (format) {
      case 'docx':
        ({ mdContent, lineMappings } = await this.convertDocx(filePath));
        break;
      case 'xlsx':
        ({ mdContent, lineMappings } = await this.convertXlsx(filePath));
        break;
      case 'pptx':
        ({ mdContent, lineMappings } = await this.convertPptx(filePath));
        break;
      case 'pdf':
        ({ mdContent, lineMappings } = await this.convertPdf(filePath));
        break;
      case 'md':
        ({ mdContent, lineMappings } = await this.convertMd(filePath));
        break;
      default:
        throw new Error(`不支持的格式：${format}`);
    }
    
    // 保存转换后的文件
    const convertedPath = path.join(this.storagePath, 'converted', `${fileId}.md`);
    fs.writeFileSync(convertedPath, mdContent, 'utf-8');
    
    // 保存位置映射
    const mappingPath = path.join(this.storagePath, 'mappings', `${fileId}.json`);
    fs.writeFileSync(mappingPath, JSON.stringify(lineMappings, null, 2), 'utf-8');
    
    // 复制原始文件
    const ext = path.extname(originalFileName);
    const originalPath = path.join(this.storagePath, 'original', `${fileId}${ext}`);
    fs.copyFileSync(filePath, originalPath);
    
    console.log(`✅ 转换完成：${convertedPath}`);
    
    return {
      mdContent,
      lineMappings,
      convertedPath,
      originalFile: originalFileName,
      originalPath
    };
  }

  /**
   * 转换 Word 文档
   */
  private async convertDocx(filePath: string): Promise<{ mdContent: string; lineMappings: LineMapping[] }> {
    const result = await mammoth.convertToHtml({ path: filePath });
    const html = result.value;
    
    // 简单的 HTML 转 Markdown（保留基本结构）
    let mdContent = this.htmlToMarkdown(html);
    
    // 构建行映射
    const lineMappings = this.buildLineMappings(mdContent, 'Word 文档');
    
    return { mdContent, lineMappings };
  }

  /**
   * 转换 Excel 表格
   */
  private async convertXlsx(filePath: string): Promise<{ mdContent: string; lineMappings: LineMapping[] }> {
    const workbook = XLSX.readFile(filePath);
    const sheets = workbook.SheetNames;
    
    const sections: string[] = [];
    let currentLine = 1;
    const lineMappings: LineMapping[] = [];
    
    for (const sheetName of sheets) {
      const sheet = workbook.Sheets[sheetName];
      const csvData = XLSX.utils.sheet_to_csv(sheet);
      const rows = csvData.split('\n');
      
      sections.push(`## ${sheetName}\n`);
      lineMappings.push({
        mdLine: sections.length,
        originalLine: currentLine,
        content: `Sheet: ${sheetName}`,
        context: `工作表名称：${sheetName}`
      });
      
      sections.push('\n| 列 | 数据 |\n|----|------|\n');
      
      rows.forEach((row, idx) => {
        if (row.trim()) {
          const cells = row.split(',');
          const mdRow = `| ${cells.join(' | ')} |`;
          sections.push(mdRow + '\n');
          
          lineMappings.push({
            mdLine: sections.length,
            originalLine: currentLine + idx,
            content: row,
            context: `工作表 ${sheetName}, 行 ${idx + 1}`
          });
        }
      });
      
      sections.push('\n---\n\n');
      currentLine += rows.length;
    }
    
    return {
      mdContent: sections.join(''),
      lineMappings
    };
  }

  /**
   * 转换 PowerPoint 演示文稿
   */
  private async convertPptx(filePath: string): Promise<{ mdContent: string; lineMappings: LineMapping[] }> {
    // 简化的 PPT 转换（实际项目中需要使用 pptxjs 或其他库）
    const mdContent = `# 演示文稿：${path.basename(filePath)}\n\n`;
    const lineMappings: LineMapping[] = [{
      mdLine: 1,
      originalLine: 1,
      content: mdContent,
      context: '演示文稿标题'
    }];
    
    // TODO: 使用 pptxjs 完整实现 PPT 解析
    console.warn('⚠️ PPT 转换功能待完善，当前仅返回基本信息');
    
    return { mdContent, lineMappings };
  }

  /**
   * 转换 PDF 文档
   */
  private async convertPdf(filePath: string): Promise<{ mdContent: string; lineMappings: LineMapping[] }> {
    const data = await pdfParse(filePath);
    const text = data.text;
    
    const pages = text.split('\f'); // PDF 分页符
    const sections: string[] = [];
    const lineMappings: LineMapping[] = [];
    let currentLine = 1;
    
    pages.forEach((page, idx) => {
      const pageText = page.trim();
      if (pageText) {
        sections.push(`## 第 ${idx + 1} 页\n\n`);
        sections.push(pageText + '\n\n');
        
        const lines = pageText.split('\n');
        lines.forEach((line, lineIdx) => {
          if (line.trim()) {
            lineMappings.push({
              mdLine: sections.length,
              originalLine: currentLine + lineIdx,
              content: line,
              context: `第 ${idx + 1} 页，行 ${lineIdx + 1}`
            });
          }
        });
        
        currentLine += lines.length;
      }
    });
    
    return {
      mdContent: sections.join(''),
      lineMappings
    };
  }

  /**
   * 转换 Markdown 文件
   */
  private async convertMd(filePath: string): Promise<{ mdContent: string; lineMappings: LineMapping[] }> {
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');
    
    const lineMappings: LineMapping[] = lines
      .map((line, idx) => ({
        mdLine: idx + 1,
        originalLine: idx + 1,
        content: line,
        context: `行 ${idx + 1}`
      }))
      .filter(l => l.content.trim());
    
    return {
      mdContent: content,
      lineMappings
    };
  }

  /**
   * HTML 转 Markdown（简化版）
   */
  private htmlToMarkdown(html: string): string {
    let md = html;
    
    // 标签转换
    md = md.replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n\n');
    md = md.replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n\n');
    md = md.replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n\n');
    md = md.replace(/<p[^>]*>(.*?)<\/p>/gi, '$1\n\n');
    md = md.replace(/<strong[^>]*>(.*?)<\/strong>/gi, '**$1**');
    md = md.replace(/<b[^>]*>(.*?)<\/b>/gi, '**$1**');
    md = md.replace(/<em[^>]*>(.*?)<\/em>/gi, '*$1*');
    md = md.replace(/<i[^>]*>(.*?)<\/i>/gi, '*$1*');
    md = md.replace(/<br\s*\/?>/gi, '\n');
    md = md.replace(/<[^>]+>/g, ''); // 移除其他标签
    
    // 清理空白
    md = md.replace(/\n{3,}/g, '\n\n');
    md = md.trim();
    
    return md;
  }

  /**
   * 构建行映射
   */
  private buildLineMappings(mdContent: string, prefix: string = ''): LineMapping[] {
    const lines = mdContent.split('\n');
    const mappings: LineMapping[] = [];
    
    lines.forEach((line, idx) => {
      if (line.trim()) {
        mappings.push({
          mdLine: idx + 1,
          originalLine: idx + 1,
          content: line,
          context: `${prefix}, 行 ${idx + 1}`
        });
      }
    });
    
    return mappings;
  }

  /**
   * 获取位置映射
   */
  getMapping(fileId: string): LineMapping[] {
    const mappingPath = path.join(this.storagePath, 'mappings', `${fileId}.json`);
    
    if (!fs.existsSync(mappingPath)) {
      throw new Error(`映射文件不存在：${fileId}`);
    }
    
    return JSON.parse(fs.readFileSync(mappingPath, 'utf-8'));
  }
}
