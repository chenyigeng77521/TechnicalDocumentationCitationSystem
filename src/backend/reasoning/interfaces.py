"""
Layer 3 接口数据结构定义
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ==================== Layer 2 → Layer 3 输入结构 ====================

class RetrievedChunk(BaseModel):
    """检索层返回的单个 Chunk（对应 retrieval.py 的 Document metadata）"""
    chunk_id: str = ""
    content: str
    doc_path: str       # 文档相对路径，如 docs/react/xxx.md
    anchor: str         # 段落锚点，如 #top 或 #dispatch-actions-with-event-handlers
    score: float = 0.0  # Reranker 精排分（或向量相似度分）
    is_truncated: bool = False
    title_path: Optional[str] = None


# ==================== Web → Layer 3 请求结构 ====================

class QARequest(BaseModel):
    """单条问答请求"""
    id: str = Field(..., description="评测题 ID，原样透传")
    query: str = Field(..., alias="question", description="用户问题")

    model_config = {"populate_by_name": True}


class BatchItem(BaseModel):
    """
    批量请求中的单条记录。
    """
    id: str
    query: str = Field(..., alias="question")
    domain: Optional[str] = None        # 透传字段，如 "React"
    answer_type: Optional[str] = None   # 透传字段，如 "concept"
    difficulty: Optional[str] = None    # 透传字段，如 "easy"

    model_config = {"populate_by_name": True}


class BatchQARequest(BaseModel):
    """批量问答请求"""
    items: list[BatchItem]


# ==================== Layer 3 → Web 响应结构（单条接口，保持原格式）====================

class Citation(BaseModel):
    """引用出处（单条接口使用，保持原格式）"""
    doc_path: str   # 文档路径，如 docs/react/xxx.md
    anchor: str     # 段落锚点，如 #top


class QAResponse(BaseModel):
    """单条问答响应（POST /api/qa，格式不变）"""
    id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    is_refusal: bool = False
    confidence: float = 0.0


class BatchQAResponse(BaseModel):
    """批量请求响应（返回落盘文件路径）"""
    status: str = "success"
    file_path: str
    total: int
    succeeded: int
    failed: int


# ==================== 批量 JSONL 落盘专用格式 ====================

class GoldSource(BaseModel):
    """
    JSONL 输出中的引用条目（新格式）。
    evidence 取命中 chunk 的原始 content，代码直接填入，不经过 LLM。
    """
    doc_path: str
    anchor: str
    evidence: str   # 文档原文片段


class BatchOutputRecord(BaseModel):
    """
    批量落盘 JSONL 每行的完整格式。
    有答/无答字段对齐赛题要求，两种模式共用同一结构，None 字段序列化时剔除。
    """
    id: str
    domain: Optional[str]           # 透传
    question: str                   # 透传原始问题
    is_answerable: bool             # True=有答，False=无答（is_refusal 取反）
    answer: str

    # 有答模式字段
    gold_sources: list[GoldSource] = Field(default_factory=list)
    answer_type: Optional[str] = None   # 透传
    difficulty: Optional[str] = None    # 透传

    # 无答模式字段
    trap_type: Optional[str] = None           # LLM 输出
    unanswerable_reason: Optional[str] = None  # LLM 输出


# ==================== 内部流转结构 ====================

class ReasoningResult(BaseModel):
    """推理内部结果，包含调试信息"""
    answer: str
    citation_ids: list[int] = Field(default_factory=list)   # 引用的 chunk 序号（1-based）
    is_refusal: bool = False
    refuse_reason: Optional[str] = None  # score_below_threshold / empty_retrieval / llm_refuse / invalid_citation / semantic_mismatch / json_parse_error
    max_score: float = 0.0
    confidence: float = 0.0
    # 无答模式扩展字段（由 LLM 输出）
    trap_type: Optional[str] = None
    unanswerable_reason: Optional[str] = None
