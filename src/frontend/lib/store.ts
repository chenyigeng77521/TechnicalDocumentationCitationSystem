import { create } from 'zustand';

interface FileRecord {
  id: string;
  name: string;
  format: string;
  size: number;
  uploadTime: string;
  category?: string;
}

interface QuestionState {
  question: string;
  answer: string | null;
  citations: string[];
  loading: boolean;
  error: string | null;
}

interface AppState {
  // 问答状态
  question: QuestionState;
  setQuestion: (q: string) => void;
  setAnswer: (answer: string, citations: string[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearAnswer: () => void;
  
  // 文件列表
  files: FileRecord[];
  setFiles: (files: FileRecord[]) => void;
  addFile: (file: FileRecord) => void;
  removeFile: (fileId: string) => void;
  
  // 上传状态
  uploading: boolean;
  setUploading: (uploading: boolean) => void;
  
  // API 配置
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 问答状态
  question: {
    question: '',
    answer: null,
    citations: [],
    loading: false,
    error: null,
  },
  
  setQuestion: (q) => set((state) => ({
    question: { ...state.question, question: q }
  })),
  
  setAnswer: (answer, citations) => set((state) => ({
    question: { ...state.question, answer, citations, error: null }
  })),
  
  setLoading: (loading) => set((state) => ({
    question: { ...state.question, loading }
  })),
  
  setError: (error) => set((state) => ({
    question: { ...state.question, error, answer: null, citations: [] }
  })),
  
  clearAnswer: () => set((state) => ({
    question: { ...state.question, answer: null, citations: [], error: null }
  })),
  
  // 文件列表
  files: [],
  setFiles: (files) => set({ files }),
  addFile: (file) => set((state) => ({ files: [...state.files, file] })),
  removeFile: (fileId) => set((state) => ({
    files: state.files.filter(f => f.id !== fileId)
  })),
  
  // 上传状态
  uploading: false,
  setUploading: (uploading) => set({ uploading }),
  
  // API 配置
  apiBaseUrl: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3002',
  setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
}));
