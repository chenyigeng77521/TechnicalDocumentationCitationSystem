"""
推理与引用层 - 类型定义
Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any
from enum import Enum


# ============================================================
class VerificationStatus(str, Enum):
    PENDING   = 'pending'
    VERIFIED  = 'verified'
    UNCERTAIN = 'uncertain'
    FAILED    = 'failed'


# ============================================================
@dataclass
class RetrievedChunk:
    """检索到的文档块（带完整元数据）"""
    chunk_id: str                        # sha256(file_path + chunk_index + content[:100])
    file_path: str                       # 文件路径
    file_hash: str                       # 文件哈希
    content: str                         # 块内容
    anchor_id: str                       # 锚点 ID: file_path#char_offset_start
    title_path: Optional[str]            # 可读标题路径: Authentication > OAuth2 > Token Refresh
    char_offset_start: int               # 字符偏移开始
    char_offset_end: int                 # 字符偏移结束
    char_count: int                      # 字符数
    is_truncated: bool                   # 是否被截断
    chunk_index: int                     # 块索引
    content_type: Literal['document', 'code', 'structured_data'] = 'document'
    language: Optional[str] = None       # 编程语言（代码类）
    embedding: Optional[List[float]] = None  # 向量
    reranker_score: Optional[float] = None   # Reranker 打分
    raw_text: Optional[str] = None           # 原始文本（用于验证）


# ============================================================
@dataclass
class ContextBlock:
    """上下文块（注入格式）"""
    id: int                              # 从 1 开始的序号
    source: str                          # Source: file_path | title_path
    content: str                         # 块内容
    is_truncated: bool                   # 是否截断
    anchor_id: str                       # 锚点 ID
    title_path: Optional[str]            # 可读标题路径
    reranker_score: float                # 检索得分


# ============================================================
@dataclass
class CitationSource:
    """引用来源（用于前端展示）"""
    id: int                                         # 引用 ID（与 ContextBlock.id 对应）
    anchor_id: str                                  # 锚点 ID
    title_path: Optional[str]                       # 可读标题路径
    score: float                                    # 检索得分
    verification_status: VerificationStatus         # 验证状态
    file_path: str                                  # 文件路径
    snippet: str                                    # 内容摘要（前 N 字符）


# ============================================================
@dataclass
class VerificationResult:
    """验证结果"""
    citation_id: int
    key_tokens: List[str]                # 关键 token（名词、数字、版本号）
    matched_tokens: List[str]            # 匹配到的 token
    match_ratio: float                   # 匹配率
    status: VerificationStatus


# ============================================================
@dataclass
class ClaimedCitation:
    """声称的引用（从 LLM 回答中提取）"""
    citation_id: int                     # 引用的 [n] ID
    claim_text: str                      # 声称的内容
    key_tokens: List[str]                # 关键 token


# ============================================================
@dataclass
class ReasoningRequest:
    """推理请求"""
    query: str                           # 用户问题
    chunks: List[RetrievedChunk]         # 检索到的 chunks
    max_tokens: Optional[int] = None     # 最大 token 数
    strict_mode: Optional[bool] = None  # 严格模式（必须引用）
    enable_async_verification: Optional[bool] = None  # 启用异步验证


# ============================================================
@dataclass
class ReasoningResponse:
    """推理响应"""
    answer: str                                          # 回答内容
    citations: List[CitationSource]                      # 引用的来源列表
    no_evidence: bool                                    # 是否无证据拒答
    max_score: float                                     # 最高检索得分
    confidence: float                                    # 置信度
    context_truncated: bool                              # 上下文是否被截断
    rejected_reason: Optional[str] = None               # 拒答原因（如果有）
    verification_results: Optional[List[VerificationResult]] = None  # 验证结果


# ============================================================
@dataclass
class GovernanceConfig:
    """上下文治理配置"""
    max_context_tokens: int = 6000
    conflict_resolution: Literal['keep_both', 'keep_higher_score', 'merge'] = 'keep_higher_score'
    deduplication_threshold: float = 0.95


# ============================================================
# 流式事件类型
# ============================================================
@dataclass
class StreamEventToken:
    type: Literal['token'] = 'token'
    content: str = ''


@dataclass
class StreamEventCitation:
    type: Literal['citation'] = 'citation'
    citation: Optional[CitationSource] = None


@dataclass
class StreamEventVerification:
    type: Literal['verification'] = 'verification'
    result: Optional[VerificationResult] = None


@dataclass
class StreamEventDone:
    type: Literal['done'] = 'done'
    response: Optional[ReasoningResponse] = None


@dataclass
class StreamEventError:
    type: Literal['error'] = 'error'
    message: str = ''


# ============================================================
# 常量（默认值，可由 reasoning_config.yaml 覆盖）
# ============================================================

DEFAULT_GOVERNANCE_CONFIG = GovernanceConfig(
    max_context_tokens=6000,
    conflict_resolution='keep_higher_score',
    deduplication_threshold=0.95,
)

RERANKER_SCORE_THRESHOLD: float = 0.4

DEFAULT_MAX_TOKENS: int = 6000
