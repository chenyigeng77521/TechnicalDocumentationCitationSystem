'use client';

import { useState, useRef } from 'react';
import { Upload, X, CheckCircle, AlertCircle, FileText } from 'lucide-react';
import { api, formatFileSize } from '@/lib/api';
import Link from 'next/link';

export default function UploadPage() {
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [category, setCategory] = useState('');
  const [tags, setTags] = useState('');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{message: string; files?: {originalName: string; status: string; error?: string}[]} | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 文件扩展名映射
  const allowedExtensions = [
    '.json', '.yaml', '.yml', '.cpp', '.java', '.py', '.xml', '.sql',
    '.html', '.md', '.txt', '.ppt', '.pptx', '.xls', '.xlsx',
    '.doc', '.docx', '.pdf'
  ];

  // 验证文件格式
  const validateFile = (file: File): { valid: boolean; error?: string } => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    
    // 检查扩展名
    if (!allowedExtensions.includes(ext)) {
      return {
        valid: false,
        error: `不支持的文件格式：${ext}。仅支持 PDF、Word、Excel、TXT、MD 文件`
      };
    }
    
    // 检查文件大小（300MB）
    if (file.size > 300 * 1024 * 1024) {
      return {
        valid: false,
        error: `文件过大：${file.name} (${(file.size / 1024 / 1024).toFixed(2)}MB)。单个文件最大 300MB`
      };
    }
    
    return { valid: true };
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragging(true);
    } else {
      setDragging(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    setError(null);
    
    const droppedFiles = Array.from(e.dataTransfer.files);
    
    // 检查总数限制
    if (files.length + droppedFiles.length > 30) {
      setError(`文件数量超过限制。最多支持 30 个文件，当前已选择 ${files.length} 个，尝试添加 ${droppedFiles.length} 个`);
      return;
    }
    
    // 验证每个文件
    const validFiles: File[] = [];
    const errors: string[] = [];
    
    for (const file of droppedFiles) {
      const validation = validateFile(file);
      if (validation.valid) {
        validFiles.push(file);
      } else {
        errors.push(`${file.name}: ${validation.error}`);
      }
    }
    
    if (errors.length > 0) {
      setError('以下文件验证失败:\n' + errors.join('\n'));
    }
    
    if (validFiles.length > 0) {
      setFiles(prev => [...prev, ...validFiles]);
    }
  };

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files);
      setError(null);
      
      // 检查总数限制
      if (files.length + selectedFiles.length > 30) {
        setError(`文件数量超过限制。最多支持 30 个文件，当前已选择 ${files.length} 个，尝试添加 ${selectedFiles.length} 个`);
        return;
      }
      
      // 验证每个文件
      const validFiles: File[] = [];
      const errors: string[] = [];
      
      for (const file of selectedFiles) {
        const validation = validateFile(file);
        if (validation.valid) {
          validFiles.push(file);
        } else {
          errors.push(`${file.name}: ${validation.error}`);
        }
      }
      
      if (errors.length > 0) {
        setError('以下文件验证失败:\n' + errors.join('\n'));
      }
      
      if (validFiles.length > 0) {
        setFiles(prev => [...prev, ...validFiles]);
      }
    }
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleUpload = async () => {
    if (files.length === 0) {
      setError('请选择要上传的文件');
      return;
    }
    
    if (files.length > 30) {
      setError(`文件数量超过限制。最多支持 30 个文件，当前已选择 ${files.length} 个`);
      return;
    }

    // 上传前最终验证
    const validationErrors: string[] = [];
    for (const file of files) {
      const validation = validateFile(file);
      if (!validation.valid) {
        validationErrors.push(`${file.name}: ${validation.error}`);
      }
    }
    
    if (validationErrors.length > 0) {
      setError('以下文件验证失败:\n' + validationErrors.join('\n'));
      return;
    }

    setUploading(true);
    setError(null);
    try {
      const tagsArray = tags.split(',').map(t => t.trim()).filter(t => t);
      const data = await api.uploadFiles(files, category || undefined, tagsArray);
      setResult(data);
      setFiles([]);
      setCategory('');
      setTags('');
    } catch (error: Error) {
      setError('上传失败：' + error.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-violet-50 via-purple-50 to-indigo-50">
      {/* 顶部导航 - 玻璃态 */}
      <nav className="nav-glass px-6 py-4 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <div className="w-12 h-12 bg-gradient-to-br from-violet-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg">
              <FileText className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gradient">文档问答</h1>
              <p className="text-sm text-slate-500">智能文档检索系统</p>
            </div>
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/" className="text-sm text-slate-600 hover:text-violet-600 transition font-medium px-4 py-2 rounded-lg hover:bg-violet-50">
              问答首页
            </Link>
            <Link href="/files" className="text-sm text-slate-600 hover:text-violet-600 transition font-medium px-4 py-2 rounded-lg hover:bg-violet-50">
              文件管理
            </Link>
          </div>
        </div>
      </nav>

      {/* 主内容 */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-slate-800 mb-2">上传文档</h2>
          <p className="text-slate-600">支持 Word、Excel、PDF、Markdown 格式</p>
        </div>

        {/* 上传区域 - WinClaw 风格 */}
        <div
          className={`border-2 border-dashed rounded-3xl p-14 text-center transition cursor-pointer upload-zone ${
            dragging ? 'dragging' : 'border-violet-300 bg-white/80 backdrop-blur-sm'
          } card-shadow`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".json,.yaml,.yml,.cpp,.java,.py,.xml,.sql,.html,.md,.txt,.ppt,.pptx,.xls,.xlsx,.doc,.docx,.pdf"
            onChange={handleSelect}
            className="hidden"
          />
          <Upload className="w-16 h-16 text-violet-400 mx-auto mb-5" />
          <p className="text-xl font-semibold text-slate-700 mb-3">
            拖拽文件到此处，或点击选择
          </p>
          <p className="text-sm text-slate-500 mb-1">
            支持代码、文档、表格、演示文稿等常见文件格式
          </p>
          <p className="text-xs text-slate-400 font-medium">
            最多 30 个文件，单个文件最大 300MB
          </p>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium text-red-800">上传错误</p>
              <p className="text-sm text-red-600 mt-1 whitespace-pre-line">{error}</p>
            </div>
          </div>
        )}

        {/* 文件列表 */}
        {files.length > 0 && (
          <div className="mt-6 bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700">
                已选择 {files.length} / 30 个文件
              </p>
              <button
                onClick={() => {
                  setFiles([]);
                  setError(null);
                }}
                className="text-sm text-red-600 hover:text-red-700"
              >
                清空全部
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {files.map((file, idx) => (
                <div key={idx} className="px-4 py-3 flex items-center justify-between border-b border-slate-100 last:border-0">
                  <div className="flex items-center gap-3">
                    <FileText className="w-5 h-5 text-blue-500" />
                    <div>
                      <p className="text-sm font-medium text-slate-700">{file.name}</p>
                      <p className="text-xs text-slate-500">{formatFileSize(file.size)}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => removeFile(idx)}
                    className="p-1 hover:bg-slate-100 rounded transition"
                  >
                    <X className="w-4 h-4 text-slate-400" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 分类和标签 */}
        <div className="mt-6 grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              分类（可选）
            </label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="例如：产品文档"
              className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              标签（可选，逗号分隔）
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="例如：产品，说明，最新"
              className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>
        </div>

        {/* 上传按钮 */}
        <div className="mt-6">
          <button
            onClick={handleUpload}
            disabled={files.length === 0 || uploading}
            className="w-full px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white rounded-xl font-medium btn-transition"
          >
            {uploading ? '上传中...' : `上传 ${files.length} 个文件${files.length >= 30 ? '（已达上限）' : ''}`}
          </button>
        </div>

        {/* 上传结果 */}
        {result && (
          <div className="mt-6 bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 bg-green-50 border-b border-green-200 flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-green-600" />
              <p className="font-medium text-green-800">上传成功</p>
            </div>
            <div className="p-4">
              <p className="text-sm text-slate-600 mb-3">{result.message}</p>
              <p className="text-sm text-blue-600 mb-3">
                📁 文件存储位置：<span className="font-mono bg-blue-50 px-2 py-1 rounded">./storage/raw/</span>
              </p>
              <div className="space-y-2">
                {result.files?.map((file, idx: number) => (
                  <div key={idx} className="flex items-center gap-2 text-sm">
                    {file.status === 'completed' ? (
                      <CheckCircle className="w-4 h-4 text-green-500" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-red-500" />
                    )}
                    <span className={file.status === 'completed' ? 'text-slate-700' : 'text-red-600'}>
                      {file.originalName}
                      {file.error && ` - ${file.error}`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
