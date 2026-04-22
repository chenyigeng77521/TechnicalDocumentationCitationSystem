'use client';

import { useState, useRef, useEffect } from 'react';

interface Message {
  role: 'user' | 'bot';
  text: string;
  sources?: string[];
}

export default function Home() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [charCount, setCharCount] = useState(0);
  // 从 localStorage 读取上次保存的状态，刷新时保持显示
  const [docCount, setDocCount] = useState(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('kb_docCount');
      return saved ? parseInt(saved, 10) : 0;
    }
    return 0;
  });
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [showKnowledgeBase, setShowKnowledgeBase] = useState(false);
  const [rawFiles, setRawFiles] = useState<any[]>([]);
  const [rawTotal, setRawTotal] = useState(0);
  const [rawPage, setRawPage] = useState(1);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [isServerConnected, setIsServerConnected] = useState(true);
  const [hasMounted, setHasMounted] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 初始化时获取文档数量
  useEffect(() => {
    setHasMounted(true);
    const checkConnection = async () => {
      try {
        const res = await fetch('http://localhost:3002/api/qa/stats');
        const data = await res.json();
        const count = data.totalFiles || 0;
        setIsServerConnected(true);
        setDocCount(count);
        localStorage.setItem('kb_connected', 'true');
        localStorage.setItem('kb_docCount', count.toString());
      } catch {
        setIsServerConnected(false);
        localStorage.setItem('kb_connected', 'false');
      }
    };
    
    checkConnection();
  }, []);

  // 获取 raw 目录文档列表
  const loadRawFiles = (page: number = 1) => {
    setIsLoadingFiles(true);
    fetch(`http://localhost:3002/api/upload/raw-files?page=${page}&limit=10`)
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setRawFiles(data.files);
          setRawTotal(data.total);
          setRawPage(data.page);
        }
      })
      .catch(err => {
        console.error('加载文档列表失败:', err);
      })
      .finally(() => setIsLoadingFiles(false));
  };

  // 点击知识库时加载文档列表
  const handleKnowledgeBaseClick = () => {
    setShowKnowledgeBase(!showKnowledgeBase);
    if (!showKnowledgeBase) {
      loadRawFiles(1);
    }
  };

  // 翻页
  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= Math.ceil(rawTotal / 10)) {
      loadRawFiles(newPage);
    }
  };

  // 自动滚动到底部（仅在有消息时）
  useEffect(() => {
    if (messages.length > 0 && resultRef.current) {
      resultRef.current.scrollTop = resultRef.current.scrollHeight;
    }
  }, [messages]);

  // 自动调整 textarea 高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 140) + 'px';
    }
  }, [question]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuestion(e.target.value);
    setCharCount(e.target.value.length);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  const fillQuestion = (q: string) => {
    setQuestion(q);
    setCharCount(q.length);
    textareaRef.current?.focus();
  };

  const clearInput = () => {
    setQuestion('');
    setCharCount(0);
    textareaRef.current?.focus();
  };

  const clearChat = () => {
    setMessages([]);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setIsUploading(true);
    setUploadMessage(`正在上传 ${files.length} 个文件...`);

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append('files', files[i]);
    }

    try {
      const response = await fetch('http://localhost:3002/api/upload', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (data.success) {
        setUploadMessage(`✅ ${data.message}`);
        // 刷新文档数量
        const statsRes = await fetch('http://localhost:3002/api/qa/stats');
        const statsData = await statsRes.json();
        setDocCount(statsData.totalFiles || 0);
      } else {
        setUploadMessage(`❌ ${data.message}`);
      }
    } catch (error: unknown) {
      setUploadMessage(`❌ 上传失败: ${(error as Error).message}`);
    } finally {
      setIsUploading(false);
      // 清空文件选择
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      // 3秒后清除消息
      setTimeout(() => setUploadMessage(''), 3000);
    }
  };

  const formatText = (text: string) => {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\n/g, '<br>');
  };

  const handleSend = async () => {
    const q = question.trim();
    if (!q || isLoading) return;

    // 添加用户消息
    setMessages(prev => [...prev, { role: 'user', text: q }]);
    setQuestion('');
    setCharCount(0);
    setIsLoading(true);

    try {
      // 调用后端 API
      const response = await fetch('http://localhost:3002/api/qa/ask-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: q }),
      });

      if (!response.ok) throw new Error('API 请求失败');

      // 处理流式响应
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let answer = '';
      let sources: string[] = [];

      while (true) {
        const { done, value } = await reader!.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.answer) answer += data.answer;
              if (data.sources) sources = data.sources;
            } catch {
              // 忽略解析错误
            }
          }
        }
      }

      // 添加 AI 回复
      setMessages(prev => [...prev, { 
        role: 'bot', 
        text: answer,
        sources: sources.length > 0 ? sources : ['知识库文档']
      }]);
    } catch (error) {
      console.error('请求失败:', error);
      setMessages(prev => [...prev, { 
        role: 'bot', 
        text: '抱歉，暂时无法连接到知识库服务，请稍后再试。',
        sources: []
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const suggestedQuestions = [
    '公司差旅报销的标准是什么？',
    '如何申请年假？',
    '新员工入职需要准备哪些材料？',
    '产品发布流程是怎样的？'
  ];

  return (
    <div style={styles.container}>
      <div style={styles.mainContent}>
        {/* Header */}
        <div style={styles.header}>
          <div style={styles.logo}>
            <div style={styles.logoIcon}>🧠</div>
            <h1 style={styles.title}>智能知识库问答</h1>
          </div>
          <p style={styles.subtitle}>基于企业知识库的 AI 智能检索与问答系统</p>
        </div>

        {/* Main card */}
        <div style={styles.card}>
        {/* Result area */}
        <div 
          ref={resultRef} 
          style={{
            ...styles.resultArea,
            overflowY: messages.length > 0 ? 'auto' : 'hidden',
            scrollbarWidth: messages.length > 0 ? 'auto' : 'none',
          }}
        >
          {messages.length === 0 ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyIcon}>💬</div>
              <p>在下方输入问题，AI 将从知识库中检索并回答</p>
            </div>
          ) : (
            messages.map((msg, index) => (
              <div key={index} style={{...styles.bubble, ...(msg.role === 'user' ? styles.bubbleUser : styles.bubbleBot)}}>
                <div style={{...styles.avatar, ...(msg.role === 'user' ? styles.avatarUser : styles.avatarBot)}}>
                  {msg.role === 'user' ? '我' : 'AI'}
                </div>
                <div style={styles.bubbleBody}>
                  <span style={styles.bubbleName}>
                    {msg.role === 'user' ? '你' : '知识库助手'}
                  </span>
                  <div 
                    style={{...styles.bubbleText, ...(msg.role === 'user' ? styles.bubbleTextUser : styles.bubbleTextBot)}}
                    dangerouslySetInnerHTML={{ __html: formatText(msg.text) }}
                  />
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={styles.sources}>
                      {msg.sources.map((source, idx) => (
                        <span key={idx} style={styles.sourceTag}>📄 {source}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          {isLoading && (
            <div style={{...styles.bubble, ...styles.bubbleBot}}>
              <div style={{...styles.avatar, ...styles.avatarBot}}>AI</div>
              <div style={styles.bubbleBody}>
                <div style={styles.typing}>
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Toolbar */}
        <div style={styles.toolbar}>
          <span style={styles.toolbarLabel}>推荐问题：</span>
          {suggestedQuestions.map((q, idx) => (
            <button key={idx} style={styles.chip} onClick={() => fillQuestion(q)}>
              {q.split('？')[0]}
            </button>
          ))}
        </div>

        {/* Input area */}
        <div style={styles.inputArea}>
          <div style={styles.inputRow}>
            <div className="textarea-wrap" style={styles.textareaWrap}>
              <textarea
                ref={textareaRef}
                value={question}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder="请输入您的问题，例如：项目管理流程是怎样的？"
                maxLength={500}
                style={styles.textarea}
              />
              <div style={styles.inputFooter}>
                <span style={styles.charCount}>{charCount} / 500</span>
                <div style={styles.inputActions}>
                  <button style={styles.actionBtn} onClick={clearInput} title="清空">🗑️</button>
                  <button style={styles.actionBtn} onClick={clearChat} title="清空对话">🔄</button>
                </div>
              </div>
            </div>
            <button 
              style={styles.sendBtn} 
              onClick={handleSend}
              disabled={!question.trim() || isLoading}
            >
              ➤
            </button>
          </div>
          <p style={styles.hint}>
            按 <kbd style={styles.kbd}>Ctrl</kbd> + <kbd style={styles.kbd}>Enter</kbd> 发送 · 支持多轮对话
          </p>
        </div>
      </div>

      {/* Stats */}
      <div style={styles.stats}>
        <div style={styles.statItem}>
          <span style={{...styles.statDot, ...(hasMounted && isServerConnected ? styles.dotGreen : styles.dotGray)}}></span>
          <span>{hasMounted && isServerConnected ? '知识库已连接' : '知识库未连接'}</span>
        </div>
        <div style={styles.statItem}>
          <span style={{...styles.statDot, ...(hasMounted && docCount > 0 ? styles.dotBlue : styles.dotGray)}}></span>
          <span>文档数：<b>{docCount.toLocaleString()}</b></span>
        </div>
      </div>
      </div>

      {/* 右侧边栏 */}
      <div style={styles.sidebar}>
        {/* 按钮行：上传按钮在左，知识库按钮和知识库列表在右 */}
        <div style={styles.btnRow}>
          <button 
            className="upload-btn" 
            style={styles.uploadBtn} 
            title="上传知识库文档"
            onClick={handleUploadClick}
            disabled={isUploading}
          >
            <span style={styles.uploadIcon}>{isUploading ? '⏳' : '📁'}</span>
            <span style={styles.uploadText}>{isUploading ? '上传中...' : '上传文档'}</span>
          </button>
          
          <div style={styles.btnGroup}>
            <button 
              className="upload-btn" 
              style={styles.uploadBtn} 
              title="管理知识库"
              onClick={handleKnowledgeBaseClick}
            >
              <span style={styles.uploadIcon}>⚙️</span>
              <span style={styles.uploadText}>知识库</span>
            </button>
            
            {/* 知识库文档列表 - 显示在知识库按钮右侧 */}
            {showKnowledgeBase && (
              <div style={styles.knowledgeBasePanel}>
                <div style={styles.kbPanelTitle}>📚 知识库文档 ({rawTotal} 个)</div>
                <div style={{ maxHeight: '180px', overflowY: 'auto', padding: '0 10px 10px' }}>
                  {isLoadingFiles ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      加载中...
                    </div>
                  ) : rawFiles.length === 0 ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      暂无文档
                    </div>
                  ) : (
                    rawFiles.map((file, idx) => (
                      <div key={idx} style={styles.kbPanelItem}>
                        <span style={styles.kbPanelIcon}>📄</span>
                        <span style={styles.kbPanelText} title={file.name}>
                          {file.name.length > 20 ? file.name.substring(0, 20) + '...' : file.name}
                        </span>
                        <span style={styles.kbPanelMeta}>{(file.size / 1024 / 1024).toFixed(1)}MB</span>
                      </div>
                    ))
                  )}
                </div>
                {/* 分页 */}
                {rawTotal > 10 && (
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px', padding: '6px 0' }}>
                    <button 
                      style={styles.pageBtn}
                      onClick={() => handlePageChange(rawPage - 1)}
                      disabled={rawPage <= 1}
                    >
                      上一页
                    </button>
                    <span style={{ fontSize: '10px', color: 'var(--text-sub)' }}>
                      {rawPage}/{Math.ceil(rawTotal / 10)}
                    </span>
                    <button 
                      style={styles.pageBtn}
                      onClick={() => handlePageChange(rawPage + 1)}
                      disabled={rawPage >= Math.ceil(rawTotal / 10)}
                    >
                      下一页
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        
        {/* 隐藏的文件输入 */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".docx,.xlsx,.pptx,.pdf,.md"
          multiple
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        
        {/* 上传状态提示 */}
        {uploadMessage && (
          <div style={styles.uploadStatus}>{uploadMessage}</div>
        )}

        {/* 上传文档要求 */}
        <div style={styles.sourcePanel}>
          <div style={styles.sourcePanelTitle}>📤 上传文档要求</div>
          <div style={{ padding: '10px 12px', fontSize: '11px' }}>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>文件数量：</span>
              <span style={styles.reqValue}>最多 30 个</span>
            </div>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>单个大小：</span>
              <span style={styles.reqValue}>最大 300MB</span>
            </div>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>文件格式：</span>
            </div>
            <div style={styles.formatTags}>
              {['PDF', 'Word', 'Excel', 'PPT', 'TXT', 'MD', 'JSON', 'XML', 'SQL', '文本类'].map(fmt => (
                <span key={fmt} style={styles.formatTag}>{fmt}</span>
              ))}
            </div>
          </div>
        </div>

        {/* 来源显示区域 */}
        <div style={styles.sourcePanel}>
          <div style={styles.sourcePanelTitle}>📖 引用来源</div>
          <div style={styles.sourcePanelList}>
            {messages.length > 0 && messages[messages.length - 1].sources ? (
              messages[messages.length - 1].sources?.map((source, idx) => (
                <div key={idx} style={styles.sourcePanelItem}>
                  <span style={styles.sourcePanelIcon}>📄</span>
                  <span style={styles.sourcePanelText}>{source}</span>
                </div>
              ))
            ) : (
              <div style={styles.sourcePanelEmpty}>暂无引用来源</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif',
    background: 'var(--bg)',
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'center',
    gap: '5px',
    padding: '16px 0 48px 0',
    color: 'var(--text)',
    marginLeft: '160px',
  },
  mainContent: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  uploadBtn: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    width: '72px',
    height: '72px',
    background: 'var(--surface)',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
    transition: 'all 0.2s',
    padding: '8px',
    marginRight: '2px',
  },
  uploadIcon: {
    fontSize: '24px',
  },
  uploadText: {
    fontSize: '11px',
    color: 'var(--text-sub)',
    textAlign: 'center',
  },
  sidebar: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    paddingTop: '100px',
    alignItems: 'flex-end',
  },
  reqItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '6px',
  },
  reqLabel: {
    color: 'var(--text-sub)',
    flexShrink: 0,
  },
  reqValue: {
    color: 'var(--primary)',
    fontWeight: 600,
  },
  formatTags: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '4px',
    marginTop: '4px',
  },
  formatTag: {
    background: 'var(--primary-light)',
    color: 'var(--primary)',
    padding: '2px 8px',
    borderRadius: '10px',
    fontSize: '10px',
    fontWeight: 500,
  },
  btnRow: {
    display: 'flex',
    flexDirection: 'row',
    gap: '10px',
    width: '180px',
    alignItems: 'flex-start',
    justifyContent: 'flex-end',
  },
  btnGroup: {
    display: 'flex',
    flexDirection: 'row',
    gap: '12px',
    alignItems: 'flex-start',
    position: 'relative',
  },
  knowledgeBasePanel: {
    width: '150px',
    background: 'var(--surface)',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'absolute',
    left: '78px',
    top: 0,
  },
  kbPanelTitle: {
    padding: '8px 10px',
    fontSize: '11px',
    fontWeight: 600,
    color: 'var(--text)',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface-2)',
  },
  kbPanelItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    padding: '4px 8px',
    fontSize: '10px',
    color: 'var(--text-sub)',
    borderRadius: '4px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  kbPanelIcon: {
    fontSize: '11px',
  },
  kbPanelText: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  kbPanelMeta: {
    fontSize: '9px',
    color: 'var(--text-sub)',
    marginLeft: 'auto',
    flexShrink: 0,
  },
  sourcePanel: {
    width: '160px',
    background: 'var(--surface)',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
    overflow: 'hidden',
    alignSelf: 'flex-end',
  },
  sourcePanelTitle: {
    padding: '10px 12px',
    fontSize: '12px',
    fontWeight: 600,
    color: 'var(--text)',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface-2)',
  },
  sourcePanelList: {
    padding: '8px',
    maxHeight: '200px',
    overflowY: 'auto',
  },
  sourcePanelItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 8px',
    fontSize: '11px',
    color: 'var(--text-sub)',
    borderRadius: '6px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  sourcePanelIcon: {
    fontSize: '12px',
  },
  sourcePanelText: {
    flex: 1,
  },
  sourcePanelEmpty: {
    padding: '12px 8px',
    fontSize: '11px',
    color: 'var(--text-light)',
    textAlign: 'center',
  },
  pageBtn: {
    background: 'var(--primary-light)',
    color: 'var(--primary)',
    border: 'none',
    borderRadius: '4px',
    padding: '2px 6px',
    fontSize: '9px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  uploadStatus: {
    width: '140px',
    padding: '8px 12px',
    fontSize: '11px',
    color: 'var(--text)',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    textAlign: 'center',
    marginTop: '8px',
  },
  header: {
    textAlign: 'center',
    marginBottom: '16px',
  },
  logo: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '10px',
    marginBottom: '8px',
  },
  logoIcon: {
    width: '40px',
    height: '40px',
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '20px',
  },
  title: {
    fontSize: '22px',
    fontWeight: 700,
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
    margin: 0,
  },
  subtitle: {
    fontSize: '13px',
    color: 'var(--text-sub)',
    marginTop: '4px',
  },
  card: {
    width: '100%',
    maxWidth: '780px',
    background: 'var(--surface)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 0 0 2px rgba(79,110,247,0.25), 0 0 0 4px rgba(124,58,237,0.15), var(--shadow-lg)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  resultArea: {
    padding: '24px 28px 20px',
    minHeight: '260px',
    maxHeight: '520px',
    overflowY: 'auto',
    background: 'var(--surface-2)',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'var(--text-light)',
    gap: '12px',
    padding: '40px 0',
    border: '1.5px dashed var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--surface)',
  },
  emptyIcon: {
    width: '56px',
    height: '56px',
    background: 'var(--primary-light)',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '26px',
  },
  bubble: {
    display: 'flex',
    gap: '12px',
    animation: 'fadeInUp 0.3s ease',
  },
  bubbleUser: {
    flexDirection: 'row-reverse',
  },
  avatar: {
    width: '36px',
    height: '36px',
    borderRadius: '50%',
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '16px',
    fontWeight: 600,
  },
  avatarUser: {
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    color: '#fff',
  },
  avatarBot: {
    background: 'linear-gradient(135deg, #10b981, #059669)',
    color: '#fff',
  },
  bubbleBody: {
    maxWidth: '80%',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  bubbleName: {
    fontSize: '11px',
    color: 'var(--text-light)',
    padding: '0 4px',
  },
  bubbleText: {
    padding: '12px 16px',
    borderRadius: '16px',
    fontSize: '14px',
    lineHeight: 1.7,
    wordBreak: 'break-word',
  },
  bubbleTextUser: {
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    color: '#fff',
    borderBottomRightRadius: '4px',
  },
  bubbleTextBot: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    color: 'var(--text)',
    borderBottomLeftRadius: '4px',
    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
  },
  sources: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    marginTop: '6px',
  },
  sourceTag: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    background: 'var(--primary-light)',
    color: 'var(--primary)',
    borderRadius: '20px',
    padding: '3px 10px',
    fontSize: '11px',
    fontWeight: 500,
  },
  typing: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '12px 16px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: '16px',
    borderBottomLeftRadius: '4px',
  },
  toolbar: {
    padding: '10px 20px',
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    flexWrap: 'wrap',
  },
  toolbarLabel: {
    fontSize: '12px',
    color: 'var(--text-sub)',
    marginRight: '4px',
  },
  chip: {
    background: 'var(--primary-light)',
    color: 'var(--primary)',
    border: 'none',
    borderRadius: '20px',
    padding: '4px 12px',
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  inputArea: {
    padding: '20px 24px 24px',
    background: 'var(--surface)',
  },
  inputRow: {
    display: 'flex',
    gap: '10px',
    alignItems: 'flex-end',
  },
  textareaWrap: {
    flex: 1,
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    overflow: 'hidden',
    transition: 'border-color 0.2s, box-shadow 0.2s',
    background: 'var(--surface-2)',
  },
  textarea: {
    width: '100%',
    border: 'none',
    outline: 'none',
    background: 'transparent',
    resize: 'none',
    padding: '14px 16px 4px',
    fontSize: '14px',
    color: 'var(--text)',
    fontFamily: 'inherit',
    lineHeight: 1.6,
    minHeight: '52px',
    maxHeight: '140px',
    overflowY: 'auto',
    height: 'auto',
  },
  inputFooter: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px 8px',
  },
  charCount: {
    fontSize: '11px',
    color: 'var(--text-light)',
  },
  inputActions: {
    display: 'flex',
    gap: '6px',
  },
  actionBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-light)',
    fontSize: '16px',
    padding: '2px 4px',
    borderRadius: '6px',
    transition: 'color 0.15s, background 0.15s',
  },
  sendBtn: {
    width: '52px',
    height: '52px',
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    border: 'none',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    color: '#fff',
    fontSize: '20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 14px rgba(79,110,247,0.35)',
    transition: 'transform 0.15s, box-shadow 0.15s, opacity 0.15s',
    flexShrink: 0,
  },
  sendBtnActive: {
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
  },
  sendBtnDisabled: {
    background: 'var(--primary-light)',
    color: 'var(--text-light)',
    cursor: 'not-allowed',
    opacity: 0.5,
    boxShadow: 'none',
  },
  hint: {
    fontSize: '12px',
    color: 'var(--text-light)',
    marginTop: '10px',
    textAlign: 'center',
  },
  kbd: {
    background: '#f3f4f6',
    border: '1px solid #d1d5db',
    borderRadius: '4px',
    padding: '1px 5px',
    fontSize: '11px',
  },
  stats: {
    display: 'flex',
    justifyContent: 'center',
    gap: '24px',
    marginTop: '20px',
  },
  statItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12px',
    color: 'var(--text-sub)',
  },
  statDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
  },
  dotGreen: {
    background: '#10b981',
  },
  dotBlue: {
    background: 'var(--primary)',
  },
  dotGray: {
    background: '#9ca3af',
  },
  dotPurple: {
    background: 'var(--accent)',
  },
};
