/**
 * 文件名处理工具
 * 从 backend/src/routes/upload.ts 抄过来，保持两服务一致
 */
import * as fs from 'fs';
import * as path from 'path';

export function fixEncoding(filename: string): string {
  try {
    const buffer = Buffer.from(filename, 'latin1');
    const decoded = buffer.toString('utf8');
    const hasChinese = /[\u4e00-\u9fa5]/.test(decoded);
    const hasGarbage = /[^\x00-\x7F]/.test(filename);
    if (hasGarbage && hasChinese) return decoded;
    return filename;
  } catch {
    return filename;
  }
}

export function sanitizeFileName(fileName: string): string {
  let cleanName = fixEncoding(fileName);
  const illegalChars = /[<>:"/\\|?*\x00-\x1f]/g;
  cleanName = cleanName.replace(illegalChars, '_').trim();
  cleanName = cleanName.replace(/^\.+|\.+$/g, '');
  cleanName = cleanName.replace(/[/\\]/g, '_');

  const lastDotIndex = cleanName.lastIndexOf('.');
  if (lastDotIndex > 0) {
    const name = cleanName.substring(0, lastDotIndex);
    const ext = cleanName.substring(lastDotIndex);
    cleanName = name.replace(/\./g, '_') + ext;
  }

  return cleanName || 'unnamed_file';
}

/**
 * 生成磁盘安全文件名，含同名冲突自动加后缀
 */
export function safeFilename(originalname: string, uploadDir: string): string {
  const sanitized = sanitizeFileName(originalname);
  let candidate = sanitized;
  let i = 1;
  while (fs.existsSync(path.join(uploadDir, candidate))) {
    const ext = path.extname(sanitized);
    const base = path.basename(sanitized, ext);
    candidate = `${base}_${i}${ext}`;
    i++;
  }
  return candidate;
}
