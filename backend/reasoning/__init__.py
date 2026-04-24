"""
推理与引用层 (Reasoning Layer)
Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline

核心要求：
1. 精准注入（转化）- 将检索到的"最小充分信息集合"封装并注入模型
2. 双重溯源（验证）- 同步 + 异步验证机制，确保引用 ID 真实存在
3. 动态治理（清理）- 实时剔除冗余或冲突信息
4. 边界严控（拒答）- 严格限制推理范围，杜绝模型幻觉
5. 效能平衡（分级）- 通过异步校对与分级验证实现最优解

对齐 TypeScript: backend/chunking-rag/src/Reasoning/index.ts
"""

# 导出类型 - 对齐 TS: export * from './types.js'
from .types import (
    VerificationStatus,
    RetrievedChunk,
    ContextBlock,
    CitationSource,
    VerificationResult,
    ClaimedCitation,
    ReasoningRequest,
    ReasoningResponse,
    GovernanceConfig,
    DEFAULT_GOVERNANCE_CONFIG,
    RERANKER_SCORE_THRESHOLD,
    DEFAULT_MAX_TOKENS,
    StreamEventToken,
    StreamEventCitation,
    StreamEventVerification,
    StreamEventDone,
    StreamEventError,
)

# 导出组件 - 对齐 TS 各 export
from .context_injector import ContextInjector, create_context_injector
from .prompt_builder import PromptBuilder, create_prompt_builder
from .citation_verifier import CitationVerifier, create_citation_verifier
from .rejection_guard import RejectionGuard, create_rejection_guard, RejectionReason
from .context_governance import ContextGovernor, create_context_governor
from .reasoning_pipeline import (
    ReasoningPipeline,
    ReasoningPipelineConfig,
    LLMConfig,
    create_reasoning_pipeline,
)
from .webui import ReasoningWebUI, create_reasoning_web_ui

# 主类别名 - 对齐 TS: export { ReasoningPipeline as ReasoningEngine }
ReasoningEngine = ReasoningPipeline

__all__ = [
    # types
    'VerificationStatus', 'RetrievedChunk', 'ContextBlock', 'CitationSource',
    'VerificationResult', 'ClaimedCitation', 'ReasoningRequest', 'ReasoningResponse',
    'GovernanceConfig', 'DEFAULT_GOVERNANCE_CONFIG', 'RERANKER_SCORE_THRESHOLD',
    'DEFAULT_MAX_TOKENS',
    'StreamEventToken', 'StreamEventCitation', 'StreamEventVerification',
    'StreamEventDone', 'StreamEventError',
    # components
    'ContextInjector', 'create_context_injector',
    'PromptBuilder', 'create_prompt_builder',
    'CitationVerifier', 'create_citation_verifier',
    'RejectionGuard', 'create_rejection_guard', 'RejectionReason',
    'ContextGovernor', 'create_context_governor',
    'ReasoningPipeline', 'ReasoningPipelineConfig', 'LLMConfig',
    'create_reasoning_pipeline',
    'ReasoningWebUI', 'create_reasoning_web_ui',
    # alias
    'ReasoningEngine',
]
