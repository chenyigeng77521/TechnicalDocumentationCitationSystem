'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { loadLanguage } from './lib/langLoader';

interface FileEditModalProps {
  open: boolean;
  filePath: string;
  fileName: string;
  onClose: () => void;
  onSaveSuccess?: () => void;
  buildApiUrl: (path: string) => string;
}

export default function FileEditModal({ open, filePath, fileName, onClose, onSaveSuccess, buildApiUrl }: FileEditModalProps) {
  const [content, setContent] = useState('');
  const originalRef = useRef('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const hasChanges = content !== originalRef.current;

  // 读取文件（二进制文件不读取）
  useEffect(() => {
    if (!open || !filePath || isBinaryFile) return;
    setContent('');
    originalRef.current = '';
    setLoading(true);
    setError('');
    setSuccessMsg('');
    const url = buildApiUrl(`/api/upload/read?path=${encodeURIComponent(filePath)}`);
    console.log('[FileEditModal] 读取文件:', url);
    fetch(url)
      .then(r => {
        console.log('[FileEditModal] 响应状态:', r.status);
        return r.json();
      })
      .then(data => {
        console.log('[FileEditModal] 响应数据:', data);
        if (data.success) {
          originalRef.current = data.content || '';
          setContent(data.content || '');
        } else {
          setError(data.message || '读取文件失败');
        }
      })
      .catch(e => {
        console.error('[FileEditModal] 读取失败:', e);
        setError('读取文件失败：' + e.message);
      })
      .finally(() => setLoading(false));
  }, [open, filePath]);

  // 保存文件（后端负责保存+索引+回滚）
  const handleSave = useCallback(async () => {
    if (!hasChanges) return;
    setSaving(true);
    setError('');
    setSuccessMsg('正在保存文件...');

    try {
      const res = await fetch(buildApiUrl('/api/upload/save'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, content }),
      });
      const data = await res.json();
      if (!data.success) {
        setSaving(false);
        setError('保存失败：' + (data.message || (data.rollback ? '文件已回滚' : '未知错误')));
        return;
      }

      originalRef.current = content;
      setSuccessMsg('✅ 文件保存成功，索引已更新！');
      onSaveSuccess?.();
    } catch (e: any) {
      setError('操作失败：' + e.message);
    } finally {
      setSaving(false);
    }
  }, [filePath, content, hasChanges, onSaveSuccess]);

  // Ctrl+S 快捷键
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's' && hasChanges) {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, handleSave]);

  // 根据文件名推断语言
  const ext = fileName.split('.').pop()?.toLowerCase() || '';
  const lang = loadLanguage(ext);
  const isBinaryFile = ext === 'pdf' || ext === 'docx' || ext === 'doc';

  if (!open) return null;

  const styles: Record<string, React.CSSProperties> = {
    overlay: {
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.4)', zIndex: 10000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    },
    modal: {
      background: 'var(--surface, #fff)', borderRadius: '12px', width: '80vw', maxWidth: '900px',
      height: '80vh', display: 'flex', flexDirection: 'column',
      boxShadow: '0 8px 32px rgba(0,0,0,0.15)', border: '1.5px solid var(--border, #e5e7eb)',
    },
    header: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 20px', borderBottom: '1px solid var(--border, #e5e7eb)',
      color: 'var(--text, #1a1f36)', fontSize: '14px', fontWeight: 500,
    },
    actions: {
      display: 'flex', gap: '10px', alignItems: 'center',
    },
    btn: {
      padding: '6px 16px', borderRadius: '6px', border: 'none', cursor: 'pointer',
      fontSize: '12px', fontWeight: 500,
    },
    editorWrap: {
      flex: 1, overflow: 'hidden', background: 'var(--surface-2, #f8faff)',
    },
    status: {
      padding: '8px 20px', fontSize: '12px', textAlign: 'center' as const,
      borderTop: '1px solid var(--border, #e5e7eb)', color: 'var(--text-sub, #6b7280)',
    },
  };

  return (
    <div style={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={styles.modal}>
        <div style={styles.header}>
          <span>{ext === 'pdf' ? '📄' : ext === 'docx' || ext === 'doc' ? '📝' : '📝'} {fileName}</span>
          <div style={styles.actions}>
            {error && <span style={{ color: 'var(--text-sub, #6b7280)', fontSize: '12px', background: '#fff0f0', padding: '2px 8px', borderRadius: '4px' }}>{error}</span>}
            {successMsg && <span style={{ color: 'var(--text-sub, #6b7280)', fontSize: '12px', background: '#f0fff0', padding: '2px 8px', borderRadius: '4px' }}>{successMsg}</span>}
            {!isBinaryFile && (
              <button
                onClick={handleSave}
                disabled={saving || loading || !hasChanges}
                style={{...styles.btn, background: saving || !hasChanges ? '#ccc' : 'var(--primary, #4f6ef7)', color: '#fff'}}
              >
                {saving ? '保存中...' : '保存 (Ctrl+S)'}
              </button>
            )}
            <button
              onClick={onClose}
              style={{...styles.btn, background: 'var(--surface, #f0f4ff)', color: 'var(--text-sub, #6b7280)', border: '1px solid var(--border, #e5e7eb)'}}
            >
              关闭
            </button>
          </div>
        </div>
        <div style={styles.editorWrap}>
          {loading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-light, #9ca3af)', fontSize: '14px' }}>加载中...</div>
          ) : isBinaryFile ? (
            ext === 'pdf' ? (
              <embed
                src={buildApiUrl(`/api/upload/download/${encodeURIComponent(filePath)}`)}
                type="application/pdf"
                style={{ width: '100%', height: '100%', border: 'none' }}
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px', color: 'var(--text-sub, #6b7280)' }}>
                <span style={{ fontSize: '40px' }}>📝</span>
                <div style={{ fontSize: '14px', fontWeight: 500 }}>Word 文件预览</div>
                <div style={{ fontSize: '12px' }}>Word 文件不支持在线编辑，请下载后使用 Word 编辑</div>
                <a
                  href={buildApiUrl(`/api/upload/download/${encodeURIComponent(filePath)}`)}
                  download
                  style={{ ...styles.btn, background: 'var(--primary, #4f6ef7)', color: '#fff', textDecoration: 'none', display: 'inline-block' }}
                >
                  下载文件
                </a>
              </div>
            )
          ) : (
            <CodeMirror
              value={content}
              onChange={setContent}
              lang={lang}
              height="100%"
              theme="light"
              basicSetup={{
                lineNumbers: true,
                foldGutter: true,
                highlightActiveLine: true,
                autocompletion: true,
                bracketMatching: true,
                closeBrackets: true,
                indentOnInput: true,
              }}
              style={{ height: '100%' }}
            />
          )}
        </div>
        <div style={styles.status}>
          <span style={{ color: 'var(--text-sub, #6b7280)', fontSize: '11px' }}>
            {isBinaryFile
              ? `文件路径: ${filePath} | ${ext === 'pdf' ? 'PDF 预览模式' : 'Word 文件（仅供下载）'}`
              : `文件路径: ${filePath} | 大小: ${(content.length / 1024).toFixed(1)}KB`}
          </span>
        </div>
      </div>
    </div>
  );
}
