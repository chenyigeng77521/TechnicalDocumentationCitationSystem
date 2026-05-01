/**
 * 修复乱码文件名脚本
 * 将 Latin-1 误读的 UTF-8 文件名还原为正确的中文
 */

import * as fs from 'fs';
import * as path from 'path';

const storagePath = path.join(__dirname, '../../storage');

function fixEncoding(fileName: string): string {
  try {
    const buffer = Buffer.from(fileName, 'latin1');
    const decoded = buffer.toString('utf8');
    const hasChinese = /[\u4e00-\u9fff]/.test(decoded);
    const hasReadableChars = /[a-zA-Z0-9_\-\s]/.test(decoded);
    
    if (hasChinese && hasReadableChars && decoded !== fileName) {
      return decoded;
    }
  } catch (e) {
    // 解码失败，使用原始名称
  }
  return fileName;
}

function processDirectory(dir: string): void {
  if (!fs.existsSync(dir)) {
    console.log(`目录不存在: ${dir}`);
    return;
  }

  const files = fs.readdirSync(dir);
  
  for (const file of files) {
    const oldPath = path.join(dir, file);
    const stat = fs.statSync(oldPath);
    
    if (stat.isFile()) {
      const fixedName = fixEncoding(file);
      if (fixedName !== file) {
        const newPath = path.join(dir, fixedName);
        fs.renameSync(oldPath, newPath);
        console.log(`✅ 重命名: ${file} -> ${fixedName}`);
      }
    }
  }
}

console.log('🔧 开始修复乱码文件名...\n');

// 修复上传文件目录
processDirectory(path.join(storagePath, 'raw'));

console.log('\n✅ 修复完成！');
