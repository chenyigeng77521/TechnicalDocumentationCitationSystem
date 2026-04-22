import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3002';

// axios 全局配置（10分钟超时）
axios.defaults.timeout = 10 * 60 * 1000;

export const api = {
  // 上传文件
  async uploadFiles(files: File[], category?: string, tags?: string[]) {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    if (category) formData.append('category', category);
    if (tags) formData.append('tags', tags.join(','));

    const response = await axios.post(`${API_BASE}/api/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  },

  // 获取文件列表
  async getFiles() {
    const response = await axios.get(`${API_BASE}/api/qa/files`);
    return response.data;
  },

  // 获取统计信息
  async getStats() {
    const response = await axios.get(`${API_BASE}/api/qa/stats`);
    return response.data;
  },

  // 删除文件
  async deleteFile(filename: string) {
    const response = await axios.delete(`${API_BASE}/api/qa/files/${filename}`);
    return response.data;
  }
};

// 格式化文件大小
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 格式化时间
export function formatTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  if (hours < 24) return `${hours} 小时前`;
  if (days < 7) return `${days} 天前`;
  
  return date.toLocaleDateString('zh-CN');
}
