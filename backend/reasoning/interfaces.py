"""
Layer 3 接口数据结构定义
严格对齐 requirment.md 的提交格式要求
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
    anchor: str         # 段落锚点，如 #top 或 #dispatch-actions-from-event-handlers
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
    """批量请求中的单条记录"""
    id: str
    query: str = Field(..., alias="question")

    model_config = {"populate_by_name": True}


class BatchQARequest(BaseModel):
    """批量问答请求"""
    items: list[BatchItem]


# ==================== Layer 3 → Web 响应结构 ====================

class Citation(BaseModel):
    """引用出处（严格对齐赛题 citations 格式）"""
    doc_path: str   # 文档路径，如 docs/react/xxx.md
    anchor: str     # 段落锚点，如 #top


class QAResponse(BaseModel):
    """单条问答响应（对齐赛题提交格式）"""
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


# ==================== 内部流转结构 ====================

class ReasoningResult(BaseModel):
    """推理内部结果，包含调试信息"""
    answer: str
    citation_ids: list[int] = Field(default_factory=list)   # 引用的 chunk 序号（1-based）
    is_refusal: bool = False
    refuse_reason: Optional[str] = None  # score_below_threshold / empty_retrieval / llm_refuse / invalid_citation / semantic_mismatch / json_parse_error
    max_score: float = 0.0
    confidence: float = 0.0
