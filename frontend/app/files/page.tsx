'use client';

import { useState, useEffect } from 'react';
import { FileText, Trash2, Download, RefreshCw, Database } from 'lucide-react';
import { api, formatFileSize, formatTime } from '@/lib/api';
import Link from 'next/link';

export default function FilesPage() {
  const [files, setFiles] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [indexing, setIndexing] = useState(false);

  useEffect(() => {
    loadFiles();
    loadStats();
  }, []);

  const loadFiles = async () => {
    try {
      const data = await api.getFiles();
      setFiles(data.files || []);
    } catch (error) {
      console.error('加载文件列表失败:', error);
    }
  };

  const loadStats = async () => {
    try {
      const data = await api.getStats();
      setStats(data.stats);
    } catch (error) {
      console.error('加载统计信息失败:', error);
    }
  };

  const handleIndex = async () => {
    setIndexing(true);
    try {
      await api.triggerIndex();
      alert('向量化索引完成');
    } catch (error: any) {
      alert('向量化失败：' + error.message);
    } finally {
      setIndexing(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* 顶部导航 */}
      <nav className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center">
                <FileText className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-semibold text-slate-800">文档问答</h1>
                <p className="text-sm text-slate-500">智能文档检索系统</p>
              </div>
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/" className="text-sm text-slate-600 hover:text-blue-600 transition">
              问答首页
            </Link>
            <Link href="/upload" className="text-sm text-slate-600 hover:text-blue-600 transition">
              上传文件
            </Link>
          </div>
        </div>
      </nav>

      {/* 主内容 */}
      <main className="max-w-6xl mx-auto px-6 py-12">
        {/* 页面标题 */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-semibold text-slate-800 mb-2">文件管理</h2>
            <p className="text-slate-500">管理您的文档库</p>
          </div>
          <button
            onClick={handleIndex}
            disabled={indexing}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-slate-300 text-white rounded-lg font-medium flex items-center gap-2 btn-transition"
          >
            <RefreshCw className={`w-4 h-4 ${indexing ? 'animate-spin' : ''}`} />
            {indexing ? '索引中...' : '重新索引'}
          </button>
        </div>

        {/* 统计卡片 */}
        {stats && (
          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="bg-white rounded-xl p-6 border border-slate-200">
              <div className="flex items-center gap-3 mb-2">
                <Database className="w-5 h-5 text-blue-500" />
                <p className="text-sm text-slate-500">文档数量</p>
              </div>
              <p className="text-3xl font-semibold text-slate-800">{stats.fileCount}</p>
            </div>
            <div className="bg-white rounded-xl p-6 border border-slate-200">
              <div className="flex items-center gap-3 mb-2">
                <FileText className="w-5 h-5 text-green-500" />
                <p className="text-sm text-slate-500">文档块数</p>
              </div>
              <p className="text-3xl font-semibold text-slate-800">{stats.chunkCount}</p>
            </div>
            <div className="bg-white rounded-xl p-6 border border-slate-200">
              <div className="flex items-center gap-3 mb-2">
                <RefreshCw className="w-5 h-5 text-purple-500" />
                <p className="text-sm text-slate-500">索引状态</p>
              </div>
              <p className="text-3xl font-semibold text-green-600">
                {stats.indexedCount === stats.chunkCount ? '100%' : `${stats.indexedCount}/${stats.chunkCount}`}
              </p>
            </div>
          </div>
        )}

        {/* 文件列表 */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-6 py-4 bg-slate-50 border-b border-slate-200">
            <p className="font-medium text-slate-700">文档列表 ({files.length})</p>
          </div>

          {files.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <FileText className="w-12 h-12 text-slate-300 mx-auto mb-4" />
              <p className="text-slate-500 mb-4">暂无文档</p>
              <Link
                href="/upload"
                className="text-blue-600 hover:text-blue-700 font-medium"
              >
                上传第一个文档
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {files.map((file) => (
                <div key={file.id} className="px-6 py-4 flex items-center justify-between hover:bg-slate-50 transition">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
                      <FileText className="w-5 h-5 text-blue-600" />
                    </div>
                    <div>
                      <p className="font-medium text-slate-800">{file.name}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded uppercase">
                          {file.format}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatFileSize(file.size)}
                        </span>
                        <span className="text-xs text-slate-400">
                          {formatTime(file.uploadTime)}
                        </span>
                      </div>
                      {file.category && (
                        <p className="text-xs text-slate-500 mt-1">
                          分类：{file.category}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="p-2 hover:bg-slate-100 rounded-lg transition" title="下载">
                      <Download className="w-4 h-4 text-slate-600" />
                    </button>
                    <button className="p-2 hover:bg-red-50 rounded-lg transition" title="删除">
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
