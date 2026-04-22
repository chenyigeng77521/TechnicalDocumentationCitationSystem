'use client';

import { useState, useEffect } from 'react';
import { FileText, Trash2 } from 'lucide-react';
import { api, formatFileSize, formatTime } from '@/lib/api';
import Link from 'next/link';

export default function FilesPage() {
  const [files, setFiles] = useState<{name: string; size: number; mtime: string}[]>([]);

  const loadFiles = async () => {
    try {
      const data = await api.getFiles();
      setFiles(data.files || []);
    } catch (error) {
      console.error('加载文件列表失败:', error);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadFiles();
  }, []);

  const handleDelete = async (filename: string) => {
    if (!confirm(`确定要删除文件 "${filename}" 吗？`)) return;
    
    try {
      await api.deleteFile(filename);
      loadFiles();
    } catch (error: Error) {
      alert('删除失败：' + error.message);
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
        <div className="mb-8">
          <h2 className="text-2xl font-semibold text-slate-800 mb-2">文件管理</h2>
          <p className="text-slate-500">管理您的文档库</p>
        </div>

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
              {files.map((file, index) => (
                <div key={index} className="px-6 py-4 flex items-center justify-between hover:bg-slate-50 transition">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
                      <FileText className="w-5 h-5 text-blue-600" />
                    </div>
                    <div>
                      <p className="font-medium text-slate-800">{file.name}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-slate-500">
                          {formatFileSize(file.size)}
                        </span>
                        <span className="text-xs text-slate-400">
                          {formatTime(file.mtime)}
                        </span>
                      </div>
                    </div>
                  </div>
                  <button 
                    onClick={() => handleDelete(file.name)}
                    className="p-2 hover:bg-red-50 rounded-lg transition" 
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4 text-red-500" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
