"""
推理管道
核心：retrieval.py → 上下文注入 → LLM 推理 → 引用验证 Pipeline
对齐 TypeScript: backend/chunking-rag/src/Reasoning/reasoning_pipeline.ts

集成说明：
- 直接调用 backend/LLM/retrieval.py 的 pipeline() 和 init_retrieval_system()
- retrieval.py 返回 List[langchain_core.documents.Document]
- 本层将 Document 转换为 RetrievedChunk，补充 retrieval.py 未提供的字段
  （详见 README.md 中的"预留接口"部分）
"""

from __future__ import annotations
import sys
import os
import re
import asyncio
import hashlib
import logging
from typing import List, Optional, AsyncGenerator, Callable
from dataclasses import dataclass

# ── 导入 retrieval.py（不修改任何数据处理层代码）──────────────────────────
_RETRIEVAL_DIR = os.path.join(os.path.dirname(__file__), '..', 'LLM')
sys.path.insert(0, os.path.abspath(_RETRIEVAL_DIR))

try:
    from retrieval import (           # type: ignore
        pipeline as retrieval_pipeline,
        init_retrieval_system,
        adaptive_topk_simple,
    )
    _RETRIEVAL_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ retrieval.py 导入失败，将使用 Mock 模式: {e}")
    _RETRIEVAL_AVAILABLE = False
    retrieval_pipeline = None
    init_retrieval_system = None
    adaptive_topk_simple = None
# ─────────────────────────────────────────────────────────────────────────────

from .types import (
    RetrievedChunk,
    ContextBlock,
    CitationSource,
    ClaimedCitation,
    VerificationResult,
    VerificationStatus,
    ReasoningRequest,
    ReasoningResponse,
    StreamEventToken,
    StreamEventCitation,
    StreamEventVerification,
    StreamEventDone,
    StreamEventError,
    RERANKER_SCORE_THRESHOLD,
    DEFAULT_MAX_TOKENS,
)
from .context_injector import ContextInjector, create_context_injector
from .prompt_builder import PromptBuilder, create_prompt_builder
from .citation_verifier import CitationVerifier, create_citation_verifier
from .rejection_guard import RejectionGuard, RejectionResult, create_rejection_guard
from .context_governance import ContextGovernor, create_context_governor

logger = logging.getLogger(__name__)


# ============================================================
# 对齐 TS: LLMConfig interface
# ============================================================
@dataclass
class LLMConfig:
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = 'gpt-4-turbo'
    temperature: float = 0.1
    max_tokens: int = 2000


# ============================================================
# 对齐 TS: ReasoningPipelineConfig interface
# ============================================================
@dataclass
class ReasoningPipelineConfig:
    llm: Optional[LLMConfig] = None
    score_threshold: Optional[float] = None
    max_context_tokens: Optional[int] = None
    enable_async_verification: bool = True
    enable_governance: bool = True


class ReasoningPipeline:
    """
    推理管道 - 对齐 TS ReasoningPipeline class
    编排整个推理流程：检索 → 治理 → 注入 → LLM → 验证
    """

    def __init__(self, config: ReasoningPipelineConfig = None):
        cfg = config or ReasoningPipelineConfig()

        self.injector: ContextInjector = create_context_injector(
            None  # 使用默认 GovernanceConfig（maxContextTokens 在 inject() 时传入）
        )
        self.prompt_builder: PromptBuilder = create_prompt_builder()
        self.verifier: CitationVerifier = create_citation_verifier()
        self.rejection_guard: RejectionGuard = create_rejection_guard(
            cfg.score_threshold or RERANKER_SCORE_THRESHOLD
        )
        self.governor: ContextGovernor = create_context_governor()

        self.llm_config: LLMConfig = cfg.llm or LLMConfig()
        self.enable_async_verification: bool = cfg.enable_async_verification
        self.enable_governance: bool = cfg.enable_governance

        # retrieval.py 共享资源（通过 init_retrieval_system 初始化一次）
        self._retrieval_system: Optional[dict] = None

        # OpenAI 客户端
        self._openai = None
        if self.llm_config.api_key:
            self._init_openai()

    # ================================================================ #
    # 公开接口 - 对齐 TS ReasoningPipeline 公开方法                     #
    # ================================================================ #

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """
        执行推理（同步） - 对齐 TS reason()
        调用链：retrieval.py → 治理 → 注入 → LLM → 验证
        """
        query = request.query
        chunks = request.chunks  # 外部传入的 chunks（已由 retrieveChunks 填充）
        use_async = (
            request.enable_async_verification
            if request.enable_async_verification is not None
            else self.enable_async_verification
        )

        # ── 阶段 1: 拒答守卫 ──────────────────────────────────────────
        rejection_result = self.rejection_guard.evaluate(query, chunks)
        if rejection_result.should_reject:
            return self._build_rejection_response(rejection_result)

        # ── 阶段 2: 动态治理 ──────────────────────────────────────────
        processed_chunks = chunks
        if self.enable_governance:
            gov_result = self.governor.govern(chunks)
            processed_chunks = gov_result.chunks
            logger.info(
                f"📋 治理完成: {gov_result.stats['original_count']} → "
                f"{gov_result.stats['final_count']} chunks"
            )

        # ── 阶段 3: 上下文注入 ────────────────────────────────────────
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS
        blocks, truncated, _ = self.injector.inject(processed_chunks, max_tokens)

        # ── 阶段 4: LLM 推理 ──────────────────────────────────────────
        if self._openai:
            stream_msg = self.prompt_builder.build_stream_message(query, blocks, truncated)
            answer = self._generate_with_llm(stream_msg)
        else:
            answer = self._build_no_llm_response(blocks)

        # ── 阶段 5: 同步引用验证 ──────────────────────────────────────
        claimed_ids = self.prompt_builder.extract_citation_ids(answer)
        sync_result = self.verifier.sync_verify(claimed_ids, blocks)

        if sync_result.invalid_citations:
            answer = self.verifier.clean_answer(
                answer,
                sync_result.valid_citations,
                sync_result.invalid_citations,
            )
            logger.warning(f"⚠️ 移除无效引用: {sync_result.invalid_citations}")

        citations: List[CitationSource] = sync_result.verified_sources

        # ── 阶段 6: 异步引用验证（不阻塞响应）────────────────────────
        if use_async and sync_result.valid_citations:
            self._run_async_verification(answer, citations, processed_chunks)

        return ReasoningResponse(
            answer=answer,
            citations=citations,
            no_evidence=False,
            max_score=rejection_result.max_score or 0.0,
            confidence=self._calculate_confidence(
                len(sync_result.valid_citations), len(blocks)
            ),
            context_truncated=truncated,
        )

    async def stream_reason(
        self,
        request: ReasoningRequest,
    ) -> AsyncGenerator:
        """
        流式推理 - 对齐 TS streamReason()
        Yields: StreamEventToken | StreamEventCitation | StreamEventVerification |
                StreamEventDone | StreamEventError
        """
        query = request.query
        chunks = request.chunks
        use_async = (
            request.enable_async_verification
            if request.enable_async_verification is not None
            else self.enable_async_verification
        )

        # ── 阶段 1: 拒答守卫 ──────────────────────────────────────────
        rejection_result = self.rejection_guard.evaluate(query, chunks)
        if rejection_result.should_reject:
            msg = self.rejection_guard.generate_rejection_message(rejection_result)
            yield StreamEventError(message=msg)
            yield StreamEventDone(response=self._build_rejection_response(rejection_result))
            return

        # ── 阶段 2: 动态治理 ──────────────────────────────────────────
        processed_chunks = chunks
        if self.enable_governance:
            gov_result = self.governor.govern(chunks)
            processed_chunks = gov_result.chunks

        # ── 阶段 3: 上下文注入 ────────────────────────────────────────
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS
        blocks, truncated, _ = self.injector.inject(processed_chunks, max_tokens)

        # ── 阶段 4: 流式 LLM 推理 ────────────────────────────────────
        citations: List[CitationSource] = []
        full_answer = ''

        if self._openai:
            stream_msg = self.prompt_builder.build_stream_message(query, blocks, truncated)
            async for token in self._stream_generate(stream_msg):
                full_answer += token
                yield StreamEventToken(content=token)

                # 实时检查新引用 - 对齐 TS
                current_ids = self.prompt_builder.extract_citation_ids(full_answer)
                for cid in current_ids:
                    if not any(c.id == cid for c in citations):
                        block = next((b for b in blocks if b.id == cid), None)
                        if block:
                            citation = CitationSource(
                                id=block.id,
                                anchor_id=block.anchor_id,
                                title_path=block.title_path,
                                score=block.reranker_score,
                                verification_status=VerificationStatus.PENDING,
                                file_path=self._extract_file_path(block.anchor_id),
                                snippet=block.content[:100],
                            )
                            citations.append(citation)
                            yield StreamEventCitation(citation=citation)
        else:
            full_answer = self._build_no_llm_response(blocks)
            yield StreamEventToken(content=full_answer)

        # ── 阶段 5: 清理无效引用 ─────────────────────────────────────
        claimed_ids = self.prompt_builder.extract_citation_ids(full_answer)
        sync_result = self.verifier.sync_verify(claimed_ids, blocks)
        if sync_result.invalid_citations:
            full_answer = self.verifier.clean_answer(
                full_answer,
                sync_result.valid_citations,
                sync_result.invalid_citations,
            )

        # ── 阶段 6: 异步验证 ─────────────────────────────────────────
        if use_async and citations:
            self._run_async_verification(full_answer, citations, processed_chunks)

        # ── 完成 ──────────────────────────────────────────────────────
        yield StreamEventDone(
            response=ReasoningResponse(
                answer=full_answer,
                citations=citations,
                no_evidence=False,
                max_score=rejection_result.max_score or 0.0,
                confidence=self._calculate_confidence(
                    len(sync_result.valid_citations), len(blocks)
                ),
                context_truncated=truncated,
            )
        )

    def retrieve_chunks(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        """
        调用 retrieval.py 检索文档，并转换为 RetrievedChunk 格式。

        retrieval.py pipeline() 返回 (List[Document], List[float]) 元组：
          - docs: 排序后的文档列表
          - reranker_scores: 对应的 CrossEncoder 预测分数（越高越相关）

        Document 的字段：
          - page_content (str): 文档内容
          - metadata (dict): 可能含 source, file_path, title_path, heading 等

        以下字段 retrieval.py 未提供，Python 层自行填充（见 README 预留接口）：
          - chunk_id: sha256(file_path + str(index) + content[:100])
          - file_hash: 空字符串（⚠️ 预留接口：建库时未写入 hash）
          - anchor_id: file_path#estimated_offset（⚠️ 预留接口：精确偏移未存入）
          - title_path: 从 metadata['title_path'] 或 metadata['heading'] 读取
          - char_offset_start / char_offset_end: 估算值（⚠️ 预留接口）
          - reranker_score: ✅ 已补齐，来自 CrossEncoder 真实分数
        """
        if not _RETRIEVAL_AVAILABLE:
            logger.warning("retrieval.py 不可用，返回空 chunks")
            return []

        try:
            # 初始化检索系统（懒加载，复用资源）
            if self._retrieval_system is None:
                self._retrieval_system = init_retrieval_system()

            sys_res = self._retrieval_system
            docs, reranker_scores = retrieval_pipeline(
                query,
                vectorstore=sys_res['vectorstore'],
                all_documents=sys_res['documents'],
                ensemble_retriever=sys_res['ensemble_retriever'],
            )
        except Exception as e:
            logger.error(f"❌ retrieval.py 检索失败: {e}")
            return []

        # 将 LangChain Document 转换为 RetrievedChunk
        chunks: List[RetrievedChunk] = []
        for i, doc in enumerate(docs[:top_k]):
            content = doc.page_content
            metadata = doc.metadata or {}

            # ── 提取 file_path（metadata['source'] 为 retrieval.py 建库时写入的路径）
            file_path = (
                metadata.get('source')
                or metadata.get('file_path')
                or metadata.get('filename')
                or f'doc_{i}'
            )

            # ── 构造 chunk_id（sha256）
            raw_id = f"{file_path}{i}{content[:100]}"
            chunk_id = hashlib.sha256(raw_id.encode()).hexdigest()[:16]

            # ── 构造 anchor_id（⚠️ 预留接口：精确字符偏移未存入 metadata，
            #    retrieval.py 建库时未记录块在文件中的起始偏移，故用估算值）
            estimated_offset = i * 1000
            anchor_id = f"{file_path}#{estimated_offset}"

            # ── title_path（从 metadata 中读取，建库时若未写入则为 None）
            #    优先级：title_path > heading > None
            title_path = metadata.get('title_path') or metadata.get('heading') or None

            # ── reranker_score（来自 CrossEncoder 真实预测分数，
            #    reranker_scores 长度与 docs 一致，与 docs 顺序对应）
            score = reranker_scores[i] if i < len(reranker_scores) else (1.0 / (i + 1))

            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    file_hash='',            # ⚠️ 预留接口：建库时未写入 hash
                    content=content,
                    anchor_id=anchor_id,
                    title_path=title_path,
                    char_offset_start=estimated_offset,
                    char_offset_end=estimated_offset + len(content),
                    char_count=len(content),
                    is_truncated=False,
                    chunk_index=i,
                    content_type='document',
                    reranker_score=score,    # CrossEncoder 真实分数
                    raw_text=content,
                )
            )
        return chunks

    def update_llm_config(self, config: LLMConfig) -> None:
        """更新 LLM 配置 - 对齐 TS updateLLMConfig()"""
        self.llm_config = config
        if config.api_key:
            self._init_openai()

    def set_score_threshold(self, threshold: float) -> None:
        """设置拒答阈值 - 对齐 TS setScoreThreshold()"""
        self.rejection_guard.set_threshold(threshold)

    # ================================================================ #
    # 私有方法                                                           #
    # ================================================================ #

    def _init_openai(self):
        """初始化 OpenAI 客户端（兼容 openai >= 1.0）"""
        try:
            from openai import OpenAI  # type: ignore
            self._openai = OpenAI(
                api_key=self.llm_config.api_key,
                base_url=self.llm_config.base_url,
            )
        except ImportError:
            logger.warning("openai 包未安装，LLM 功能不可用")
            self._openai = None

    def _generate_with_llm(self, prompt: str) -> str:
        """使用 LLM 生成回答 - 对齐 TS generateWithLLM()"""
        if not self._openai:
            raise RuntimeError('LLM 未配置')
        response = self._openai.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {'role': 'system', 'content': '你是一个严格的技术文档问答助手。'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=self.llm_config.temperature,
            max_tokens=self.llm_config.max_tokens,
        )
        return response.choices[0].message.content or ''

    async def _stream_generate(self, prompt: str) -> AsyncGenerator[str, None]:
        """流式生成 - 对齐 TS streamGenerate()"""
        if not self._openai:
            raise RuntimeError('LLM 未配置')
        stream = self._openai.chat.completions.create(
            model=self.llm_config.model,
            messages=[
                {'role': 'system', 'content': '你是一个严格的技术文档问答助手。'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=self.llm_config.temperature,
            max_tokens=self.llm_config.max_tokens,
            stream=True,
        )
        for chunk in stream:
            content = (chunk.choices[0].delta.content or '') if chunk.choices else ''
            if content:
                yield content

    def _run_async_verification(
        self,
        answer: str,
        citations: List[CitationSource],
        chunks: List[RetrievedChunk],
        on_progress: Optional[Callable] = None,
    ) -> None:
        """后台执行异步验证 - 对齐 TS runAsyncVerification()"""
        claimed = self._extract_claimed_citations(answer, citations)

        async def _run():
            try:
                results = await self.verifier.async_verify(
                    answer, claimed, chunks, on_progress
                )
                logger.info(f"✅ 异步验证完成: {len(results)} 个引用")
                for result in results:
                    citation = next((c for c in citations if c.id == result.citation_id), None)
                    if citation:
                        citation.verification_status = result.status
            except Exception as e:
                logger.error(f"❌ 异步验证失败: {e}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_run())
            else:
                loop.run_until_complete(_run())
        except Exception:
            pass  # 异步验证失败不影响主流程

    def _extract_claimed_citations(
        self,
        answer: str,
        citations: List[CitationSource],
    ) -> List[ClaimedCitation]:
        """提取引用声明 - 对齐 TS extractClaimedCitations()"""
        claimed: List[ClaimedCitation] = []
        used_ids: set = set()

        for match in re.finditer(r'\[(\d+)\]', answer):
            cid = int(match.group(1))
            if cid not in used_ids and any(c.id == cid for c in citations):
                used_ids.add(cid)
                start = max(0, match.start() - 50)
                end = min(len(answer), match.end() + 50)
                claim_text = answer[start:end]
                claimed.append(
                    ClaimedCitation(
                        citation_id=cid,
                        claim_text=claim_text,
                        key_tokens=self.verifier.extract_key_tokens(claim_text),
                    )
                )
        return claimed

    def _build_rejection_response(self, result: RejectionResult) -> ReasoningResponse:
        """构建拒答响应 - 对齐 TS buildRejectionResponse()"""
        message = self.rejection_guard.generate_rejection_message(result)
        debug_info = self.rejection_guard.get_debug_info(result)
        return ReasoningResponse(
            answer=message + debug_info,
            citations=[],
            no_evidence=True,
            max_score=result.max_score or 0.0,
            confidence=0.0,
            context_truncated=False,
            rejected_reason=result.reason.value if result.reason else None,
        )

    def _build_no_llm_response(self, blocks: List[ContextBlock]) -> str:
        """构建无 LLM 响应 - 对齐 TS buildNoLLMResponse()"""
        if not blocks:
            return '未检索到相关文档。'
        summaries = []
        for i, block in enumerate(blocks):
            snippet = block.content[:200]
            suffix = '...' if len(block.content) > 200 else ''
            summaries.append(f"[{i + 1}] {snippet}{suffix}")
        return (
            '根据检索结果，以下是相关信息：\n\n'
            + '\n\n'.join(summaries)
            + '\n\n（请配置 LLM API 以启用智能问答功能）'
        )

    def _calculate_confidence(self, valid_count: int, total_count: int) -> float:
        """计算置信度 - 对齐 TS calculateConfidence()"""
        if total_count == 0:
            return 0.0
        coverage = valid_count / total_count
        base_score = min(coverage * 1.5, 1.0)
        return round(base_score, 2)

    def _extract_file_path(self, anchor_id: str) -> str:
        """从 anchorId 提取文件路径 - 对齐 TS extractFilePath()"""
        parts = anchor_id.split('#')
        return parts[0] if parts else anchor_id


def create_reasoning_pipeline(
    config: ReasoningPipelineConfig = None,
) -> ReasoningPipeline:
    """创建推理管道 - 对齐 TS createReasoningPipeline()"""
    return ReasoningPipeline(config)
