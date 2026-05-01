// API 地址配置
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3002';

/**
 * 构建 API URL
 * @param path - API 路径（如 '/api/qa/ask'）
 * @returns 完整的 API URL
 */
export function buildApiUrl(path: string): string {
  // 确保路径以 /api 开头
  const apiPath = path.startsWith('/api') ? path : `/api${path.startsWith('/') ? path : `/${path}`}`;
  return `${API_BASE_URL}${apiPath}`;
}

/**
 * 获取 API 基础 URL（不含 /api 前缀）
 */
export function getApiBaseUrl(): string {
  return API_BASE_URL;
}
