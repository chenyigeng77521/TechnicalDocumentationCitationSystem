'use client';

import { useState, useRef, useEffect } from 'react';

interface Message {
  role: 'user' | 'bot';
  text: string;
  sources?: string[];
}

interface ApiResponse {
  answer: string;
  sources: string[];
}

export default function Home() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [charCount, setCharCount] = useState(0);
  const [docCount, setDocCount] = useState(0);
  const resultRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 初始化时获取文档数量
  useEffect(() => {
    fetch('http://localhost:3002/api/qa/stats')
      .then(res => res.json())
      .then(data => {
        setDocCount(data.totalFiles || 0);
      })
      .catch(() => setDocCount(0));
  }, []);

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
            } catch (e) {
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
            <div style={styles.textareaWrap}>
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
              style={{...styles.sendBtn, ...(question.trim() ? styles.sendBtnActive : styles.sendBtnDisabled)}} 
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
          <span style={{...styles.statDot, ...styles.dotGreen}}></span>
          <span>知识库已连接</span>
        </div>
        <div style={styles.statItem}>
          <span style={{...styles.statDot, ...styles.dotBlue}}></span>
          <span>文档数：<b>{docCount.toLocaleString()}</b></span>
        </div>
      </div>
    </div>
  );
}

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif',
    background: '#f0f4ff',
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    paddingTop: '20px',
    paddingBottom: '48px',
    color: '#1a1f36',
  },
  header: {
    textAlign: 'center',
    marginBottom: '18px',
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
    background: 'linear-gradient(135deg, #4f6ef7, #7c3aed)',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '20px',
  },
  title: {
    fontSize: '22px',
    fontWeight: 700,
    background: 'linear-gradient(135deg, #4f6ef7, #7c3aed)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
    margin: 0,
  },
  subtitle: {
    fontSize: '13px',
    color: '#6b7280',
    marginTop: '4px',
  },
  card: {
    width: '100%',
    maxWidth: '780px',
    background: '#ffffff',
    borderRadius: '16px',
    boxShadow: '0 8px 40px rgba(79,110,247,0.14)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  resultArea: {
    padding: '24px 28px 20px',
    minHeight: '360px',
    maxHeight: '520px',
    overflowY: 'auto',
    background: '#f8faff',
    borderBottom: '1px solid #e5e9f8',
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
    color: '#9ca3af',
    gap: '12px',
    padding: '40px 0',
  },
  emptyIcon: {
    width: '56px',
    height: '56px',
    background: '#eef1fe',
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
    background: 'linear-gradient(135deg, #4f6ef7, #7c3aed)',
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
    color: '#9ca3af',
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
    background: 'linear-gradient(135deg, #4f6ef7, #7c3aed)',
    color: '#fff',
    borderBottomRightRadius: '4px',
  },
  bubbleTextBot: {
    background: '#ffffff',
    border: '1px solid #e5e9f8',
    color: '#1a1f36',
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
    background: '#eef1fe',
    color: '#4f6ef7',
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
    background: '#ffffff',
    border: '1px solid #e5e9f8',
    borderRadius: '16px',
    borderBottomLeftRadius: '4px',
  },
  toolbar: {
    padding: '10px 20px',
    background: '#ffffff',
    borderBottom: '1px solid #e5e9f8',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    flexWrap: 'wrap',
  },
  toolbarLabel: {
    fontSize: '12px',
    color: '#6b7280',
    marginRight: '4px',
  },
  chip: {
    background: '#eef1fe',
    color: '#4f6ef7',
    border: 'none',
    borderRadius: '20px',
    padding: '4px 12px',
    fontSize: '12px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  inputArea: {
    padding: '20px 24px 24px',
    background: '#ffffff',
  },
  inputRow: {
    display: 'flex',
    gap: '10px',
    alignItems: 'flex-end',
  },
  textareaWrap: {
    flex: 1,
    border: '1.5px solid #e5e9f8',
    borderRadius: '10px',
    overflow: 'hidden',
    transition: 'border-color 0.2s, box-shadow 0.2s',
    background: '#f8faff',
  },
  textarea: {
    width: '100%',
    border: 'none',
    outline: 'none',
    background: 'transparent',
    resize: 'none',
    padding: '14px 16px 4px',
    fontSize: '14px',
    color: '#1a1f36',
    fontFamily: 'inherit',
    lineHeight: 1.6,
    minHeight: '56px',
    maxHeight: '140px',
    overflowY: 'auto',
  },
  inputFooter: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '6px 12px 8px',
  },
  charCount: {
    fontSize: '11px',
    color: '#9ca3af',
  },
  inputActions: {
    display: 'flex',
    gap: '6px',
  },
  actionBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: '#9ca3af',
    fontSize: '16px',
    padding: '2px 4px',
    borderRadius: '6px',
    transition: 'color 0.15s, background 0.15s',
  },
  sendBtn: {
    width: '52px',
    height: '52px',
    border: 'none',
    borderRadius: '10px',
    cursor: 'pointer',
    color: '#fff',
    fontSize: '20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    transition: 'transform 0.15s, box-shadow 0.15s, opacity 0.15s',
  },
  sendBtnActive: {
    background: 'linear-gradient(135deg, #4f6ef7, #7c3aed)',
    boxShadow: '0 4px 14px rgba(79,110,247,0.35)',
  },
  sendBtnDisabled: {
    background: '#e5e9f8',
    color: '#9ca3af',
    cursor: 'not-allowed',
    opacity: 0.5,
  },
  hint: {
    fontSize: '12px',
    color: '#9ca3af',
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
    color: '#6b7280',
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
    background: '#4f6ef7',
  },
  dotPurple: {
    background: '#7c3aed',
  },
};
