'use client';

import { useState, useRef, useEffect } from 'react';

// 🔥 调试日志 - 页面加载时立即输出
console.log('🔥🔥🔥 页面已加载 - TechnicalDocumentationCitationSystem Frontend 🔥🔥🔥');
console.log('📍 当前 URL:', typeof window !== 'undefined' ? window.location.href : 'N/A');

interface Message {
  role: 'user' | 'bot';
  text: string;
  sources?: string[];
}

export default function Home() {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [thinkingStep, setThinkingStep] = useState(0);
  const [charCount, setCharCount] = useState(0);
  const [docCount, setDocCount] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingTime, setProcessingTime] = useState<number | null>(null);
  const [showKnowledgeBase, setShowKnowledgeBase] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [showHistoryPanel, setShowHistoryPanel] = useState(false);
  const [historyConversations, setHistoryConversations] = useState<any[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [rawFiles, setRawFiles] = useState<any[]>([]);
  const [rawTotal, setRawTotal] = useState(0);
  const [rawPage, setRawPage] = useState(1);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [isServerConnected, setIsServerConnected] = useState(true);
  const [hasMounted, setHasMounted] = useState(false);
  const [copySuccess, setCopySuccess] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<any[]>(() => {
    try { return JSON.parse(localStorage.getItem('favorites') || '[]'); }
    catch { return []; }
  });
  const [sessionId, setSessionId] = useState<string>('');
  const [showLogPanel, setShowLogPanel] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logStream, setLogStream] = useState<EventSource | null>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);
  // 批量测试相关状态
  const [isBatchUploading, setIsBatchUploading] = useState(false);
  const [batchUploadProgress, setBatchUploadProgress] = useState(0);
  const [batchUploadMessage, setBatchUploadMessage] = useState('');
  const [batchResultFiles, setBatchResultFiles] = useState<any[]>([]);
  const [isLoadingResults, setIsLoadingResults] = useState(false);
  const [resultPage, setResultPage] = useState(1);
  const [resultTotalPages, setResultTotalPages] = useState(1);
  const batchFileInputRef = useRef<HTMLInputElement>(null);
  const resultFileInputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const thinkingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const logPanelRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // API 基础 URL
  const getApiBaseUrl = () => {
    return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3002';
  };

  // 构建完整的 API URL
  const buildApiUrl = (path: string) => {
    const baseUrl = getApiBaseUrl();
    // 确保路径以 / 开头
    const apiPath = path.startsWith('/') ? path : `/${path}`;
    // 如果是相对路径（以 / 开头）
    if (baseUrl.startsWith('/')) {
      // 直接拼接，去除重复的 /
      const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
      return cleanBase + apiPath;
    }
    // 如果是完整 URL，确保以 / 结尾后拼接
    return baseUrl.endsWith('/') ? `${baseUrl}${path}` : `${baseUrl}/${path}`;
  };

  // 初始化时获取文档数量并创建 session
  useEffect(() => {
    setHasMounted(true);
    
    // 1. 创建新 session（每次页面加载都创建）
    const initSession = async () => {
      try {
        // 调用 entrance 的 /api/context/create-session 接口
        // entrance 服务会自动调用 3006 端口生成 session
        const res = await fetch(buildApiUrl('/api/context/create-session'), {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.success) {
          const newSid = data.session_id;
          localStorage.setItem('context_session_id', newSid);
          console.log('✅ 创建新 session:', newSid);
          setSessionId(newSid);
          console.log('📝 当前 session:', newSid);
        } else {
          console.error('❌ 创建 session 失败:', data.error);
        }
      } catch (err) {
        console.error('❌ 创建 session 失败:', err);
      }
    };
    
    initSession();
    
    // 2. 检查后端连接
    const checkConnection = async () => {
      try {
        const res = await fetch(buildApiUrl('/api/qa/stats'));
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
    fetch(buildApiUrl(`/api/upload/raw-files?page=${page}&limit=10`))
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
    const willOpen = !showKnowledgeBase;
    setShowKnowledgeBase(willOpen);
    if (willOpen) {
      setShowResults(false);
      setShowHistoryPanel(false);
      setShowLogPanel(false);
      if (logStream) { logStream.close(); setLogStream(null); }
      setLogLines([]);
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

  // 动态思考步骤动画
  useEffect(() => {
    if (isLoading) {
      const steps = [
        '🔍 正在理解您的问题...',
        '📚 正在检索知识库...',
        '📝 正在生成回答...'
      ];
      let index = 0;
      thinkingIntervalRef.current = setInterval(() => {
        index = (index + 1) % steps.length;
        setThinkingStep(index);
      }, 800);
    } else {
      if (thinkingIntervalRef.current) {
        clearInterval(thinkingIntervalRef.current);
        thinkingIntervalRef.current = null;
      }
      setThinkingStep(0);
    }
    return () => {
      if (thinkingIntervalRef.current) {
        clearInterval(thinkingIntervalRef.current);
      }
    };
  }, [isLoading]);

  // 复制成功提示自动消失
  useEffect(() => {
    if (copySuccess) {
      const timer = setTimeout(() => {
        setCopySuccess(null);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [copySuccess]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuestion(e.target.value);
    setCharCount(e.target.value.length);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (isLoading) { handleStop(); return; }
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

  // ========== 批量测试相关函数 ==========
  
  const handleBatchFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsBatchUploading(true);
    setBatchUploadProgress(30);
    setBatchUploadMessage(`⬆️ 正在上传：${file.name}...`);

    // 2 秒后模拟"上传完成，正在调用远程服务"
    const remoteTimer = setTimeout(() => {
      setBatchUploadMessage(`🌐 上传成功，正在调用远程服务...`);
      setBatchUploadProgress(60);
    }, 2000);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // 模拟上传进度
      setTimeout(() => setBatchUploadProgress(80), 400);

      const response = await fetch(buildApiUrl('/api/batch-test/upload'), {
        method: 'POST',
        body: formData
      });

      clearTimeout(remoteTimer);
      setBatchUploadProgress(90);
      const data = await response.json();
      setBatchUploadProgress(100);

      if (data.success) {
        setBatchUploadMessage(`✅ 处理完成！共 ${data.questionCount} 个问题`);
        // 自动刷新结果列表
        loadResultFiles();
      } else {
        setBatchUploadMessage(`❌ ${data.message || '处理失败'}`);
      }
    } catch (error: any) {
      clearTimeout(remoteTimer);
      console.error('❌ [批量测试] 上传失败:', error);
      setBatchUploadMessage(`❌ 上传失败：${error.message}`);
    } finally {
      setIsBatchUploading(false);
      setBatchUploadProgress(0);
      // 清空文件选择
      if (batchFileInputRef.current) {
        batchFileInputRef.current.value = '';
      }
      // 5 秒后清除消息
      setTimeout(() => {
        setBatchUploadMessage('');
      }, 5000);
    }
  };

  const loadResultFiles = async (page: number = resultPage) => {
    setIsLoadingResults(true);
    try {
      const response = await fetch(buildApiUrl(`/api/batch-test/results?page=${page}&limit=5`));
      const data = await response.json();

      if (data.success) {
        setBatchResultFiles(data.files || []);
        setResultPage(data.page || 1);
        setResultTotalPages(data.totalPages || 1);
      } else {
        console.error('❌ [批量测试] 获取结果列表失败:', data.message);
      }
    } catch (error: any) {
      console.error('❌ [批量测试] 获取结果列表失败:', error);
    } finally {
      setIsLoadingResults(false);
    }
  };

  // 点击结果列表时加载
  const handleResultListClick = () => {
    const willOpen = !showResults;
    setShowResults(willOpen);
    if (willOpen) {
      setShowKnowledgeBase(false);
      setShowHistoryPanel(false);
      setShowLogPanel(false);
      if (logStream) { logStream.close(); setLogStream(null); }
      setLogLines([]);
      loadResultFiles(1);
    }
  };

  // 历史会话切换
  const handleHistoryToggle = async () => {
    const willOpen = !showHistoryPanel;
    setShowHistoryPanel(willOpen);
    if (willOpen) {
      setShowKnowledgeBase(false);
      setShowResults(false);
      setShowLogPanel(false);
      if (logStream) { logStream.close(); setLogStream(null); }
      setLogLines([]);
      setIsLoadingHistory(true);
      console.log('📋 [历史会话] sessionId:', sessionId);
      try {
        const res = await fetch(buildApiUrl(`/api/context/get-all-messages/${sessionId}`));
        const data = await res.json();
        console.log('📋 [历史会话] 返回数据:', JSON.stringify(data, null, 2));
        setHistoryConversations(data.messages || []);
      } catch (e) {
        console.error('获取历史会话失败', e);
        setHistoryConversations([]);
      }
      setIsLoadingHistory(false);
    }
  };

  // 后台日志切换
  const handleLogToggle = () => {
    const willOpen = !showLogPanel;
    setShowLogPanel(willOpen);

    if (willOpen) {
      setShowKnowledgeBase(false);
      setShowResults(false);
      setShowHistoryPanel(false);
      if (logStream) logStream.close();
      const url = buildApiUrl('/api/logs/stream?file=backend.log');
      console.log('📋 [调试] 连接日志服务:', url);
      setLogLines([`正在连接日志服务: ${url}`]);
      const es = new EventSource(url);
      setLogStream(es);

      es.onopen = () => {
        console.log('📋 [调试] EventSource 连接已建立');
        setLogLines(prev => [...prev, '✅ 连接已建立']);
      };

      es.onmessage = (event) => {
        console.log('📋 [调试] 收到消息:', event.data.substring(0, 80));
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'init' && Array.isArray(data.lines)) {
            setLogLines(data.lines);
            console.log(`📋 [调试] 初始日志 ${data.lines.length} 行`);
          } else if (data.type === 'append' && Array.isArray(data.lines)) {
            setLogLines(prev => [...prev, ...data.lines]);
          }
        } catch (e) {
          console.log('📋 [调试] 解析失败:', e);
          setLogLines(prev => [...prev, `⚠️ 解析失败: ${event.data.substring(0, 50)}`]);
        }
      };
      es.onerror = (e) => {
        console.log('📋 [调试] EventSource 错误:', es.readyState, EventSource.CONNECTING, EventSource.OPEN, EventSource.CLOSED);
        setLogLines(prev => [...prev, `⚠️ 连接断开 (readyState=${es.readyState}), 重连中...`]);
      };
    } else {
      if (logStream) { logStream.close(); setLogStream(null); }
      setLogLines([]);
    }
  };

  // 自动滚动日志
  useEffect(() => {
    if (logContainerRef.current && showLogPanel) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logLines, showLogPanel]);

  // 点击空白处关闭弹窗（历史会话、后台日志除外）
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      const inSidebar = sidebarRef.current && sidebarRef.current.contains(target);
      const inLogPanel = logPanelRef.current && logPanelRef.current.contains(target);
      if (!inSidebar && !inLogPanel) {
        setShowKnowledgeBase(false);
        setShowResults(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

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
      const response = await fetch(buildApiUrl('/api/upload'), {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (data.success) {
        console.log('📤 [上传] 本地上传成功，文件数量:', data.files?.length || 0);
        
        // 刷新文档数量
        const statsRes = await fetch(buildApiUrl('/api/qa/stats'));
        const statsData = await statsRes.json();
        setDocCount(statsData.totalFiles || 0);
        console.log('📊 [上传] 本地文档数量已更新:', statsData.totalFiles || 0);
        
        // 开关控制：是否同时上传到远程索引服务器
        const ENABLE_REMOTE_UPLOAD = false;
        console.log('🔧 [上传] 远程上传开关:', ENABLE_REMOTE_UPLOAD);
        
        if (ENABLE_REMOTE_UPLOAD) {
          setUploadMessage(`✅ 本地上传成功，正在上传远程...`);
          setIsProcessing(true);
          setProcessingTime(null);
          const startTime = Date.now();
          
          const remoteUrl = 'http://172.25.178.21:3003/upload?index=true';
          console.log('🌐 [上传] 远程上传地址:', remoteUrl);
          console.log('📁 [上传] 待上传文件:', data.files?.map((f: any) => f.originalName).join(', '));
          
          // 同步逐个上传，等待每个文件处理完成
          let successCount = 0;
          let failCount = 0;
          
          for (let i = 0; i < (data.files || []).length; i++) {
            const file = data.files[i];
            console.log(`📤 [上传] 正在上传第 ${i + 1}/${data.files.length} 个文件：${file.originalName}`);
            
            try {
              // 创建新的 FormData，按照新格式
              const remoteFormData = new FormData();
              // 从本地文件读取内容
              const fileBlob = await fetch(URL.createObjectURL(files[i])).then(res => res.blob());
              remoteFormData.append('files', fileBlob, file.originalName);
              remoteFormData.append('index', 'true');
              
              const resp = await fetch(remoteUrl, {
                method: 'POST',
                body: remoteFormData
              });
              
              const result = await resp.json();
              console.log(`📥 [上传] 第 ${i + 1} 个文件响应:`, result);
              
              if (result.success || resp.ok) {
                successCount++;
                console.log(`✅ [上传] 第 ${i + 1} 个文件上传成功`);
              } else {
                failCount++;
                console.error(`❌ [上传] 第 ${i + 1} 个文件上传失败:`, result.message);
              }
            } catch (err) {
              failCount++;
              console.error(`❌ [上传] 第 ${i + 1} 个文件异常:`, (err as Error).message);
            }
          }
          
          const endTime = Date.now();
          const duration = ((endTime - startTime) / 1000).toFixed(2);
          setProcessingTime(Number(duration));
          
          console.log('📊 [上传] 远程上传完成 - 成功:', successCount, '失败:', failCount, '总用时:', duration, '秒');
          setUploadMessage(`✅ 本地 + 远程上传完成 (${successCount}/${data.files.length}), 用时 ${duration} 秒`);
        } else {
          console.log('⏭️ [上传] 跳过远程上传');
          setUploadMessage(`✅ 上传成功！`);
        }
      } else {
        setUploadMessage(`❌ ${data.message}`);
      }
    } catch (error: unknown) {
      setUploadMessage(`❌ 上传失败: ${(error as Error).message}`);
    } finally {
      setIsUploading(false);
      setIsProcessing(false);
      // 清空文件选择
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      // 3秒后清除消息
      setTimeout(() => { setUploadMessage(""); setProcessingTime(null); }, 5000);
    }
  };

  const formatText = (text: string) => {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\n/g, '<br>');
  };

  // 复制文本功能
  const copyToClipboard = async (text: string, isQuestion: boolean) => {
    try {
      // 优先尝试现代 API
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // 降级方案：使用 execCommand（兼容 HTTP 环境）
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        textarea.style.top = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      
      const message = isQuestion ? '问题已复制' : '答案已复制';
      setCopySuccess(message);
      // 2 秒后自动消失
      setTimeout(() => {
        setCopySuccess(null);
      }, 2000);
    } catch (err) {
      console.error('复制失败:', err);
      setCopySuccess('复制失败');
      setTimeout(() => {
        setCopySuccess(null);
      }, 2000);
    }
  };

  // 收藏切换
  const toggleFavorite = (text: string) => {
    if (favorites.some((f: any) => f.text === text)) {
      const newFavs = favorites.filter((f: any) => f.text !== text);
      setFavorites(newFavs);
      localStorage.setItem('favorites', JSON.stringify(newFavs));
      setCopySuccess('已取消收藏');
    } else {
      const newFavs = [...favorites, { text, timestamp: new Date().toISOString() }];
      setFavorites(newFavs);
      localStorage.setItem('favorites', JSON.stringify(newFavs));
      setCopySuccess('已添加到收藏');
    }
    setTimeout(() => setCopySuccess(null), 2000);
  };

  // 判断是否已收藏
  const isFavorited = (text: string) => favorites.some((f: any) => f.text === text);

  // 停止请求
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsLoading(false);
  };

  const handleSend = async () => {
    const q = question.trim();
    if (!q || isLoading) return;

    // 添加用户消息
    setMessages(prev => [...prev, { role: 'user', text: q }]);
    setQuestion('');
    setCharCount(0);
    setIsLoading(true);
    console.log('🚀 开始思考动画');

    // 记录用户消息到 context memory（不再提前记录，等成功后再一起保存）
    const userQuestion = q;

    try {
      // 创建 AbortController 用于停止请求
      abortControllerRef.current = new AbortController();
      const { signal } = abortControllerRef.current;

      // 调用后端 API
      const response = await fetch(buildApiUrl('/api/qa/ask-stream'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        signal,
        body: JSON.stringify({ 
          question: q,
          session_id: sessionId || undefined  // 传递 session_id
        }),
      });

      if (!response.ok) throw new Error('API 请求失败');

      // 处理流式响应
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let answer = '';
      let sources: string[] = [];
      let classification: any = null;
      let isCompleteAnswer = false; // 标记是否收到完整答案（非流式）

      console.log('📡 开始接收响应...');

      while (true) {
        const { done, value } = await reader!.read();
        if (done) {
          console.log('✅ 响应结束');
          break;
        }

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.trim() === '') continue;
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              console.log('📨 收到事件:', data.type, data);
              
              // 处理不同类型的事件
              if (data.type === 'start') {
                console.log('🚀 开始处理:', data.message);
              } else if (data.type === 'classification') {
                classification = {
                  category: data.category,
                  confidence: data.confidence,
                  description: data.description,
                  searchStrategy: data.searchStrategy
                };
                console.log('📊 分类结果:', classification);
              } else if (data.type === 'answer') {
                // 检查是否是完整答案格式（包含 answer 和 sources 字段）
                if (data.answer && Array.isArray(data.sources)) {
                  // 完整答案格式，直接接收
                  answer = data.answer;
                  sources = data.sources;
                  isCompleteAnswer = true;
                  console.log('✅ 收到完整答案，来源数:', sources.length);
                } else {
                  // 流式答案格式，逐字接收
                  answer += data.text;
                }
              } else if (data.type === 'sources') {
                sources = data.sources;
              } else if (data.type === 'end') {
                console.log('🏁 问答完成:', data.classification);
              } else if (data.type === 'error') {
                const errorMsg = data.message || '发生错误';
                const isLanguageHint = errorMsg.includes('中文') || errorMsg.includes('语言');
                
                console.error('❌ 发生错误:', data.message);
                setIsLoading(false);
                setMessages(prev => [...prev, { 
                  role: 'bot', 
                  text: isLanguageHint ? `💡 ${errorMsg}` : `❌ ${errorMsg}`,
                  sources: []
                }]);
                return;
              }
            } catch (e) {
              console.error('❌ JSON 解析错误:', e, '原始行:', line);
            }
          }
        }
      }

      // 如果没有收到任何答案，显示错误
      if (!answer && !classification) {
        console.error('❌ 未收到任何有效响应');
        setIsLoading(false);
        setMessages(prev => [...prev, { 
          role: 'bot', 
          text: '❌ 抱歉，无法连接到服务，请稍后再试。',
          sources: []
        }]);
        return;
      }

      console.log('📝 最终答案:', answer);
      console.log('📊 最终分类:', classification);
      console.log('📚 最终来源:', sources);

      // 添加 AI 回复（包含分类信息）
      const categoryEmoji: Record<string, string> = {
        'FACT': '📊',
        'PROC': '🔄',
        'EXPL': '💡',
        'COMP': '⚖️',
        'META': '🤔',
        'UNKNOWN': '❓'
      };

      const categoryInfo = classification ? 
        `${categoryEmoji[classification.category] || '❓'} **${classification.category}** (${Math.round(classification.confidence * 100)}% 置信度)\n\n` : '';
      
      const finalAnswer = categoryInfo + answer;
      
      // 提取唯一来源并去重
      const uniqueSources = Array.from(new Set(sources.filter(s => s && s.trim())));
      
      setMessages(prev => [...prev, { 
        role: 'bot', 
        text: finalAnswer,
        sources: uniqueSources.length > 0 ? uniqueSources : undefined
      }]);

      // 记录用户问题和助手回答到 context memory（仅限有效回答）
      if (sessionId && answer && answer !== '' && !answer.includes('检索服务暂时不可用') && !answer.includes('无法连接到知识库服务') && !answer.includes('问题不够清晰')) {
        try {
          // 记录用户问题
          await fetch(buildApiUrl('/api/context/add-user-message'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, content: userQuestion })
          });
          // 记录助手回答
          await fetch(buildApiUrl('/api/context/add-assistant-message'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, content: finalAnswer })
          });
          console.log('✅ 问题和回答已记录到 context memory');
        } catch (err) {
          console.error('❌ 记录到 context memory 失败:', err);
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('⏹ 用户已停止请求');
        return;
      }
      console.error('请求失败:', error);
      setMessages(prev => [...prev, { 
        role: 'bot', 
        text: '抱歉，暂时无法连接到知识库服务，请稍后再试。',
        sources: []
      }]);
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const suggestedQuestions = [
    '公司差旅报销的标准是什么？',
    '如何申请年假？',
    '新员工入职需要准备哪些材料？',
    '产品发布流程是怎样的？'
  ];

  return (
    <div style={styles.container} className="container-mobile">

      <div style={styles.mainContent} className="main-mobile">
        {/* Header */}
        <div style={styles.header}>
          <div style={styles.logo}>
            <div style={styles.logoIcon}>🧠</div>
            <h1 style={styles.title} className="title-mobile">智能知识库问答</h1>
          </div>
          <p style={styles.subtitle} className="subtitle-mobile">基于企业知识库的 AI 智能检索与问答系统</p>
        </div>

        {/* 复制成功提示 Toast - 屏幕中央悬浮 */}
        {copySuccess && (
          <div style={styles.copyToast}>
            <span style={styles.copyToastIcon}>✅</span>
            <span style={styles.copyToastText}>{copySuccess}</span>
          </div>
        )}

        {/* Main card */}
        <div style={styles.card} className="card-mobile">
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
                  {msg.role === 'bot' && (
                    <span style={styles.bubbleName}>
                      知识库助手
                    </span>
                  )}
                  <div 
                    style={{...styles.bubbleText, ...(msg.role === 'user' ? styles.bubbleTextUser : styles.bubbleTextBot)}}
                    dangerouslySetInnerHTML={{ __html: formatText(msg.text) }}
                  />
                  {msg.role === 'user' && (
                    <div style={{ display: 'flex', gap: '4px', marginTop: '6px', justifyContent: 'flex-end' }}>
                      <button 
                        style={styles.copyBtn}
                        onClick={() => copyToClipboard(msg.text, true)}
                        title="复制问题"
                      >
                        📋 复制
                      </button>
                      <button 
                        style={{
                          ...styles.copyBtn,
                          background: isFavorited(msg.text) ? '#e5e7eb' : 'transparent',
                          border: isFavorited(msg.text) ? 'none' : '1px solid var(--border)',
                        }}
                        onClick={() => toggleFavorite(msg.text)}
                        title={isFavorited(msg.text) ? '取消收藏' : '收藏'}
                      >
                        {isFavorited(msg.text) ? '⭐ 已收藏' : '☆ 收藏'}
                      </button>
                    </div>
                  )}
                  {msg.role === 'bot' && (
                    <div style={{ display: 'flex', gap: '4px', marginTop: '6px' }}>
                      <button 
                        style={{...styles.copyBtn, ...styles.copyBtnBot}}
                        onClick={() => copyToClipboard(msg.text, false)}
                        title="复制答案"
                      >
                        📋 复制
                      </button>
                      <button 
                        style={{
                          ...styles.copyBtn,
                          ...styles.copyBtnBot,
                          background: index > 0 && isFavorited(messages[index - 1]?.text) ? '#e5e7eb' : 'transparent',
                          border: index > 0 && isFavorited(messages[index - 1]?.text) ? 'none' : '1px solid var(--border)',
                        }}
                        onClick={() => {
                          if (index > 0) toggleFavorite(messages[index - 1].text);
                        }}
                        title={index > 0 && isFavorited(messages[index - 1]?.text) ? '取消收藏问题' : '收藏问题'}
                      >
                        {index > 0 && isFavorited(messages[index - 1]?.text) ? '⭐ 已收藏' : '☆ 收藏'}
                      </button>
                    </div>
                  )}
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
                <div style={styles.thinkingBubble}>
                  <span style={styles.thinkingIcon}>⏳</span>
                  <span style={styles.thinkingText}>
                    {['🔍 正在理解您的问题...', '📚 正在检索知识库...','📝 正在生成回答...'][thinkingStep]}
                  </span>
                </div>
                {/*<div style={styles.typing}>*/}
                {/*  <span></span>*/}
                {/*  <span></span>*/}
                {/*  <span></span>*/}
                {/*</div>*/}
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
              style={{
                ...styles.sendBtn,
                transform: isLoading ? 'none' : undefined,
                opacity: (!isLoading && !question.trim()) ? 0.4 : 1,
                cursor: (!isLoading && !question.trim()) ? 'default' : 'pointer',
              }}
              onClick={isLoading ? handleStop : handleSend}
              disabled={!isLoading && (!question.trim())}
              title={isLoading ? '停止' : '发送'}
            >
              {isLoading ? '⏹' : '➤'}
            </button>
          </div>
          <p style={styles.hint}>
            按 <kbd style={styles.kbd}>Ctrl</kbd> + <kbd style={styles.kbd}>Enter</kbd> 发送 · 支持多轮对话
          </p>
        </div>
      </div>

      {/* Stats */}
      <div style={styles.stats} className="stats-mobile">
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

      {/* 移动端底部工具栏 */}
      <div className="sidebar-mobile" style={{ display: 'none' }}>
        {/* 按钮行：上传和知识库 */}
        <div className="mobile-btn-row">
          <button 
            style={styles.mobileBtn}
            onClick={handleUploadClick}
            disabled={isUploading}
          >
            <span style={styles.mobileBtnIcon}>{isUploading ? '⏳' : '📁'}</span>
            <span style={styles.mobileBtnText}>{isUploading ? '上传中' : '上传'}</span>
          </button>
          
          <button 
            style={styles.mobileBtn}
            onClick={handleKnowledgeBaseClick}
          >
            <span style={styles.mobileBtnIcon}>📚</span>
            <span style={styles.mobileBtnText}>知识库</span>
          </button>
        </div>
        
        {/* 知识库文档列表（展开时显示） */}
        {showKnowledgeBase && (
          <div className="mobile-info-panel">
            <div className="mobile-panel-title">📚 知识库文档 ({rawTotal} 个)</div>
            {isLoadingFiles ? (
              <div style={{ padding: '10px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                加载中...
              </div>
            ) : rawFiles.length === 0 ? (
              <div style={{ padding: '10px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                暂无文档
              </div>
            ) : (
              rawFiles.slice(0, 5).map((file, idx) => (
                <div key={idx} className="mobile-panel-item">
                  <span className="mobile-panel-icon">📄</span>
                  <span className="mobile-panel-text" title={file.name}>
                    {file.name.length > 15 ? file.name.substring(0, 15) + '...' : file.name}
                  </span>
                  <span className="mobile-panel-meta">{(file.size / 1024).toFixed(1)}KB</span>
                </div>
              ))
            )}
          </div>
        )}
        
        {/* 引用来源 */}
        {(() => {
          const lastMsg = messages[messages.length - 1];
          const hasSources = lastMsg?.sources && lastMsg.sources.length > 0;
          if (!hasSources || !lastMsg.sources) return null;
          return (
            <div className="mobile-info-panel">
              <div className="mobile-panel-title">📚 引用来源 ({lastMsg.sources.length} 个)</div>
              {lastMsg.sources.slice(0, 5).map((source, idx) => (
                <div key={idx} className="mobile-panel-item">
                  <span className="mobile-panel-icon">📄</span>
                  <span className="mobile-panel-text" title={source}>
                    {source.length > 20 ? source.substring(0, 20) + '...' : source}
                  </span>
                </div>
              ))}
              {lastMsg.sources.length > 5 && (
                <div style={{ padding: '10px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                  还有 {lastMsg.sources.length - 5} 个来源...
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {/* 右侧边栏 */}
      <div style={styles.sidebar} className="sidebar-mobile" ref={sidebarRef}>
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
                        <a
                          href={buildApiUrl(file.downloadUrl)}
                          download={file.name}
                          style={{...styles.kbPanelText, color: 'var(--primary)', textDecoration: 'none'}}
                          title="下载"
                        >
                          {file.name.length > 20 ? file.name.substring(0, 20) + '...' : file.name}
                        </a>
                        <span style={styles.kbPanelMeta}>{(file.size / 1024).toFixed(1)}KB</span>
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
          accept=".docx,.xlsx,.pptx,.pdf,.md,.adoc,.jsonl"
          multiple
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        
        {/* 隐藏的批量测试文件输入 */}
        <input
          ref={batchFileInputRef}
          type="file"
          accept=".json,.jsonl,.csv,.txt"
          onChange={handleBatchFileChange}
          style={{ display: 'none' }}
        />
        
        {/* 上传状态提示 */}
        {uploadMessage && (
          <div style={styles.uploadStatus}>{uploadMessage}</div>
        )}

        {/* 批量测试状态提示 */}
        {batchUploadMessage && (
          <div style={styles.uploadStatus}>{batchUploadMessage}</div>
        )}

        {/* 批量测试按钮行 - 和上传文档、知识库按钮并排 */}
        <div style={styles.btnRow}>
          <button 
            className="upload-btn" 
            style={styles.uploadBtn} 
            title="批量测试"
            onClick={() => batchFileInputRef.current?.click()}
            disabled={isBatchUploading}
          >
            <span style={styles.uploadIcon}>{isBatchUploading ? '⏳' : '🧪'}</span>
            <span style={styles.uploadText}>{isBatchUploading ? '处理中...' : '批量测试'}</span>
          </button>
          
          <div style={styles.btnGroup}>
            <button 
              className="upload-btn" 
              style={styles.uploadBtn} 
              title="批量测试结果"
              onClick={handleResultListClick}
              disabled={isLoadingResults}
            >
              <span style={styles.uploadIcon}>📥</span>
              <span style={styles.uploadText}>结果列表</span>
            </button>
            
            {/* 结果文件列表 */}
            {showResults && (
              <div style={styles.knowledgeBasePanel}>
                <div style={styles.kbPanelTitle}>📥 批量测试结果 {isLoadingResults ? '（加载中...）' : `(${batchResultFiles.length} 个)`}</div>
                <div style={{ maxHeight: '180px', overflowY: 'auto', padding: '0 10px 10px' }}>
                  {isLoadingResults ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      加载中...
                    </div>
                  ) : batchResultFiles.length === 0 ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      暂无结果
                    </div>
                  ) : (
                    batchResultFiles.map((file, idx) => (
                      <div key={idx} style={styles.kbPanelItem}>
                        <span style={styles.kbPanelIcon}>📄</span>
                        <a
                          href={buildApiUrl(file.downloadUrl)}
                          download={file.name}
                          style={{...styles.kbPanelText, color: 'var(--primary)', textDecoration: 'none'}}
                          title="下载"
                        >
                          {file.name.length > 20 ? file.name.substring(0, 20) + '...' : file.name}
                        </a>
                        <a
                          href={buildApiUrl(file.downloadUrl)}
                          download={file.name}
                          style={{...styles.kbPanelMeta, color: 'var(--primary)', textDecoration: 'none'}}
                          title="下载"
                        >
                          ⬇️ {(file.size / 1024).toFixed(0)}KB
                        </a>
                      </div>
                    ))
                  )}
                </div>
                {/* 分页控件 */}
                {resultTotalPages > 1 && (
                  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', padding: '8px 10px', borderTop: '1px solid #f0f0f0' }}>
                    <button
                      onClick={() => loadResultFiles(resultPage - 1)}
                      disabled={resultPage <= 1}
                      style={{ ...styles.paginationBtn, opacity: resultPage <= 1 ? 0.4 : 1 }}
                    >
                      ‹ 上一页
                    </button>
                    <span style={{ fontSize: '11px', color: 'var(--text-light)' }}>
                      {resultPage} / {resultTotalPages}
                    </span>
                    <button
                      onClick={() => loadResultFiles(resultPage + 1)}
                      disabled={resultPage >= resultTotalPages}
                      style={{ ...styles.paginationBtn, opacity: resultPage >= resultTotalPages ? 0.4 : 1 }}
                    >
                      下一页 ›
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 历史会话 + 后台日志 */}
        <div style={styles.btnRow}>
          <div style={styles.btnGroup}>
            <button 
              className="upload-btn" 
              style={styles.uploadBtn} 
              title="历史会话"
              onClick={handleHistoryToggle}
            >
              <span style={styles.uploadIcon}>📋</span>
              <span style={styles.uploadText}>历史会话</span>
            </button>
            
            {/* 历史会话列表 */}
            {showHistoryPanel && (
              <div style={styles.knowledgeBasePanel}>
                <div style={styles.kbPanelTitle}>📋 历史会话 {isLoadingHistory ? '（加载中...）' : `(${historyConversations.length} 条)`}</div>
                <div style={{ maxHeight: '555px', overflowY: 'auto', padding: '0 10px 10px' }}>
                  {/* 当前会话 ID */}
                  <div style={styles.kbPanelItem}>
                    <span style={{...styles.kbPanelIcon, fontSize: '10px'}}>🆔</span>
                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{...styles.kbPanelText, fontSize: '10px', color: 'var(--primary)'}}>
                        会话ID:
                      </div>
                      <div style={{...styles.kbPanelText, fontSize: '10px', color: 'var(--text)', wordBreak: 'break-all', marginTop: '2px'}}>
                        {sessionId || '暂无会话'}
                      </div>
                    </div>
                  </div>
                  {isLoadingHistory ? (
                    <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      加载中...
                    </div>
                  ) : historyConversations.length === 0 ? (
                    <div style={{ padding: '10px 0', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
                      暂无历史问答记录
                    </div>
                  ) : (
                    [...historyConversations].reverse().map((msg: any, idx: number) => (
                      <div key={idx} style={{
                        ...styles.kbPanelItem,
                        flexDirection: 'column',
                        alignItems: 'stretch',
                        padding: '10px 8px',
                        gap: '6px',
                        borderBottom: idx < historyConversations.length - 1 ? '1px solid var(--border)' : 'none',
                        transition: 'background 0.3s ease',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                          <span style={{ ...styles.kbPanelIcon, fontSize: '12px', marginTop: '1px' }}>💬</span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{
                              fontSize: '11px',
                              fontWeight: 500,
                              color: '#4b5563',
                              lineHeight: '1.5',
                              wordBreak: 'break-word',
                              whiteSpace: 'pre-wrap',
                              padding: '4px 8px',
                              background: 'var(--surface-2)',
                              borderRadius: '6px',
                            }}>
                              {msg.user ? `Q: ${msg.user}` : `会话 ${idx + 1}`}
                            </div>
                          </div>
                          <span style={{...styles.kbPanelMeta, flexShrink: 0, fontSize: '9px', marginTop: '3px'}}>
                            {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : ''}
                          </span>
                        </div>
                        {msg.assistant && (
                          <div style={{
                            fontSize: '10px',
                            color: '#4338ca',
                            lineHeight: '1.5',
                            wordBreak: 'break-word',
                            whiteSpace: 'pre-wrap',
                            padding: '4px 8px 4px 24px',
                            background: 'var(--primary-light)',
                            borderRadius: '6px',
                            marginTop: '2px',
                          }}>
                            A: {msg.assistant}
                            <div style={{ fontSize: '9px', color: 'var(--text-light)', marginTop: '4px', textAlign: 'right' }}>
                              {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : ''}
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
          <button 
            className="upload-btn" 
            style={styles.uploadBtn} 
            title="后台日志"
            onClick={handleLogToggle}
          >
            <span style={styles.uploadIcon}>📋</span>
            <span style={styles.uploadText}>后台日志</span>
          </button>
        </div>

        {/* 上传文档要求 */}
        <div style={styles.sourcePanel} className="source-panel-mobile-hide">
          <div style={styles.sourcePanelTitle}>📤 上传文档要求</div>
          <div style={{ padding: '10px 12px', fontSize: '11px' }}>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>文件数量：</span>
              <span style={styles.reqValue}>最多 100 个</span>
            </div>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>单个大小：</span>
              <span style={styles.reqValue}>最大 300MB</span>
            </div>
            <div style={styles.reqItem}>
              <span style={styles.reqLabel}>文件格式：</span>
            </div>
            <div style={styles.formatTags}>
              {['PDF', 'Word', 'Excel', 'PPT', 'TXT', 'MD', 'ADOC','文本类'].map(fmt => (
                <span key={fmt} style={styles.formatTag}>{fmt}</span>
              ))}
            </div>
          </div>
        </div>

        {/* 来源显示区域 - 手机端隐藏 */}
        <div style={styles.sourcePanel} className="source-panel-mobile-hide">
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

      {/* 右侧面板 - 后台日志 */}
      <div ref={logPanelRef} style={{
        ...styles.sidebarLeft,
        display: showLogPanel ? 'flex' : 'none',
        overflow: 'hidden',
      }} className="sidebar-mobile-left">
        <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text)', padding: '8px 50px', background: 'var(--surface)', borderBottom: '3px solid var(--border)', width: '100%', flexShrink: 0, borderRadius: 'var(--radius) var(--radius) 0 0' }}>
          📋 后台日志
          <button onClick={handleLogToggle} style={{ float: 'right', border: 'none', background: 'transparent', color: 'var(--text-sub)', cursor: 'pointer', fontSize: '12px' }}>✕</button>
        </div>
        <div ref={logContainerRef} style={{
          flex: 1,
          overflowY: 'auto',
          padding: '3px 3px',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
          fontSize: '10px',
          marginBottom:'10px',
          marginRight:'3px',
          lineHeight: '1.5',
          width: '100%',
          background: 'var(--surface)',
        }}>
          {logLines.length === 0 ? (
            <div style={{ padding: '20px 10px', textAlign: 'center', fontSize: '11px', color: 'var(--text-light)' }}>
              暂无日志
            </div>
          ) : (
          logLines.map((line, i) => {
            const isError = /❌|Error|error/.test(line);
            const isWarn = /⚠️|WARN/.test(line);
            return (
              <div key={i} style={{
                padding: '2px 10px',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                color: isError ? '#ef4444' : isWarn ? '#f59e0b' : '#5b6570',
                fontWeight: isError ? 'bold' : 'normal',
                background: i % 2 === 0 ? 'var(--surface-2)' : 'transparent',
              }}>{line}</div>
            );
          })
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
    width: '100%',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'stretch',
    justifyContent:'center',
    position: 'relative',
    gap: '1px',
    padding: '16px 0 48px 0',
    color: 'var(--text)',
  },
  mainContent: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    flex: 1,
    minWidth: 0,
    maxWidth: '800px',
    paddingTop: '0px',
    paddingBottom: '10px',
    paddingLeft: '3px',
    paddingRight: '3px',
    overflow: 'hidden',
  },
  uploadBtn: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '5px',
    width: '72px',
    height: '72px',
    background: 'var(--surface)',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
    transition: 'all 0.2s',
    padding: '8px',
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
    width: '180px',
    minWidth: '180px',
    height: '553px',
    maxHeight: '553px',
    overflow: 'hidden',
    gap: '10px',
    alignItems: 'center',
    background: 'var(--surface)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 0 0 2px rgba(79,110,247,0.25), 0 0 0 4px rgba(124,58,237,0.15), var(--shadow-lg)',
    padding: '2px',
    // paddingTop: '100px',   ← 删掉这个
    marginTop: '100px',        //← 改成这个！整体下移，阴影也跟着走
    marginBottom:'64px',
  },
  sidebarLeft: {
    display: 'flex',
    flexDirection: 'column',
    width: '190px',
    minWidth: '190px',
    height: '555px',
    maxHeight: '555px',
    overflow: 'hidden',
    gap: '3px',
    position: 'absolute',
    right: 3,
    top: '116px',
    marginBottom:'230px',
    // height: 'calc(100% - 230px)',
    zIndex: 10,
    background: 'var(--surface)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 0 0 2px rgba(79,110,247,0.25), 0 0 0 4px rgba(124,58,237,0.15), var(--shadow-lg)',
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
    gap: '19px',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: '0px',
  },
  btnGroup: {
    display: 'flex',
    flexDirection: 'row',
    gap: '0px',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: '0px',
  },
  knowledgeBasePanel: {
    width: '180px',
    background: 'var(--surface)',
    border: '1.5px solid var(--border)',
    borderRadius: 'var(--radius)',
    boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'absolute',
    left: '86%',
    top: 118,
  },
  // knowledgeBasePanel2: {
  //   width: '140px',
  //   background: 'var(--surface)',
  //   border: '1.5px solid var(--border)',
  //   borderRadius: 'var(--radius)',
  //   boxShadow: '0 2px 12px rgba(79,110,247,0.08)',
  //   overflow: 'hidden',
  //   flexShrink: 0,
  //   position: 'absolute',
  //   left: '89%',
  //   top: '200px',
  // },
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
    alignSelf: 'center',
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
  // 移动端底部样式
  mobileBtnRow: {
    display: 'flex',
    flexDirection: 'row',
    gap: '10px',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '6px 0',
  },
  mobileBtn: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '4px',
    minWidth: '64px',
    maxWidth: '80px',
    height: '56px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: '10px',
    cursor: 'pointer',
    padding: '6px',
    flex: '0 0 auto',
    transition: 'all 0.2s',
  },
  mobileBtnIcon: {
    fontSize: '22px',
  },
  mobileBtnText: {
    fontSize: '10px',
    color: 'var(--text-sub)',
    textAlign: 'center',
    lineHeight: '1.2',
  },
  mobileInfoPanel: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    padding: '8px 0',
    maxHeight: '120px',
    overflowY: 'auto',
    borderTop: '1px solid var(--border)',
    marginTop: '4px',
  },
  mobilePanelTitle: {
    fontSize: '11px',
    fontWeight: 600,
    color: 'var(--text)',
    padding: '0 4px',
  },
  mobilePanelItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 8px',
    background: 'var(--surface)',
    borderRadius: '6px',
    fontSize: '11px',
    color: 'var(--text-sub)',
    border: '1px solid var(--border)',
  },
  mobilePanelIcon: {
    fontSize: '12px',
    flexShrink: 0,
  },
  mobilePanelText: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontSize: '11px',
  },
  mobilePanelMeta: {
    fontSize: '9px',
    color: 'var(--text-light)',
    flexShrink: 0,
    marginLeft: 'auto',
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
    marginTop:'1px',
    display: 'flex',
    flexDirection: 'column',
  },
  resultArea: {
    padding: '24px 28px 20px',
    minHeight: '260px',
    maxHeight: '260px',
    overflowY: 'auto',
    scrollbarGutter: 'stable',
    background: 'var(--surface-2)',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
    position: 'relative',
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
    maxWidth: '60%',
    display: 'flex',
    flexDirection: 'column',
    gap: '1px',
  },
  bubbleName: {
    fontSize: '11px',
    color: 'var(--text-light)',
    padding: '0 4px',
  },
  bubbleText: {
    padding: '10px 10px',
    borderRadius: '16px',
    fontSize: '14px',
    lineHeight: 1.6,
    wordBreak: 'break-word',
  },
  bubbleTextUser: {
    background: 'linear-gradient(135deg, var(--primary), var(--accent))',
    color: '#fff',
    borderBottomRightRadius: '4px',
  },
  bubbleTextBot: {
    background: 'var(--surface)',
    border: '2px solid var(--border)',
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
    padding: '8px 12px',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: '16px',
    borderBottomLeftRadius: '4px',
    marginTop: '4px',
  },
  copyBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '1px',
    padding: '2px 3px',
    background: 'var(--primary-light)',
    border: 'none',
    borderRadius: '5px',
    fontSize: '11px',
    color: 'var(--primary)',
    cursor: 'pointer',
    transition: 'all 0.15s',
    alignSelf: 'flex-start',
    marginTop: '1px',
    fontWeight: 500,
  },
  copyBtnBot: {
    background: 'rgba(255,255,255,0.9)',
    color: 'var(--primary)',
    alignSelf: 'flex-end',
    marginTop: '1px',
    fontWeight: 500,
  },
  copyToast: {
    position: 'fixed',
    top: '25vh',
    left: '45%',
    transform: 'translateX(-50%)',
    background: 'rgba(16, 185, 129, 0.98)',
    color: '#fff',
    padding: '16px 32px',
    borderRadius: '16px',
    fontSize: '16px',
    fontWeight: 600,
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
    zIndex: 10000,
    opacity: 1,
    backdropFilter: 'blur(8px)',
  },
  copyToastIcon: {
    fontSize: '14px',
  },
  copyToastText: {
    fontSize: '13px',
  },
  thinkingBubble: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '2px',
    padding: '10px 14px',
    background: 'linear-gradient(135deg, #f0f4ff, #e8f4f8)',
    border: '1px solid #c9d6ff',
    borderRadius: '14px',
    borderBottomLeftRadius: '4px',
    fontSize: '13px',
    color: 'var(--text)',
  },
  thinkingIcon: {
    fontSize: '16px',
    animation: 'spin 2s linear infinite',
  },
  thinkingText: {
    fontSize: '12px',
    color: 'var(--text)',
    fontWeight: 500,
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
    background: 'var(--surface-2)',
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
    lineHeight: 1.5,
    minHeight: '70px',
    maxHeight: '70px',
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
    gap: '20px',
    marginTop: '10px',
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
  paginationBtn: {
    padding: '4px 10px',
    fontSize: '11px',
    border: '1px solid #e5e7eb',
    borderRadius: '6px',
    background: '#fff',
    cursor: 'pointer',
    color: 'var(--text)',
    lineHeight: '1.4',
  },
};
