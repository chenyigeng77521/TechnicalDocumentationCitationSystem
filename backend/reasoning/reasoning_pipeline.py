"""
推理管道
核心：retrieval.py → 上下文注入 → LLM 推理 → 引用验证 Pipeline

集成说明：
- 直接调用 backend/LLM/retrieval.py 的 pipeline() 和 init_retrieval_system()
- retrieval.py 返回 List[langchain_core.documents.Document]
- 本层将 Document 转换为 RetrievedChunk，补充 retrieval.py 未提供的字段
  （详见 README.md 中的"预留接口"部分）

v2 变更：
- LLM 配置改由 .env 统一维护，通过 config_loader 加载
- 支持 provider 切换：glm5 / kimi / minimax / qwen / openai
- 构造时若未显式传入 LLMConfig，自动从配置文件读取 active_provider
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

from .interfaces import (
    search_test as interfaces_search_test,
    RetrievalResponse,
    RetrievedChunkResponse,
)
from ._types import (
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
# ============================================================
@dataclass
class LLMConfig:
    """
    LLM 运行时配置。

    可由以下来源填充（优先级从高到低）：
      1. 显式传入构造函数
      2. 环境变量（LLM_API_KEY / LLM_MODEL / LLM_BASE_URL / LLM_PROVIDER）
      3. .env 中 LLM_ACTIVE_PROVIDER 对应的配置块

    建议通过 LLMConfig.from_file() 工厂方法创建（从 .env 读取），而不是直接设置字段。
    """
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = 'gpt-4-turbo'
    temperature: float = 0.1
    max_tokens: int = 2000
    provider: str = 'openai'          # 记录来源 provider，仅用于日志

    @classmethod
    def from_file(
        cls,
        provider: Optional[str] = None,
        llm_config_file: Optional[str] = None,
    ) -> 'LLMConfig':
        """
        从 .env / 环境变量创建 LLMConfig 实例。

        参数：
            provider: 强制指定 provider（覆盖 yaml active_provider 和环境变量）
            llm_config_file: 自定义 llm_config.yaml 路径
        """
        try:
            from .config_loader import get_active_llm_config
            pcfg = get_active_llm_config(provider, llm_config_file)
            if pcfg is None:
                logger.warning("⚠️ 未找到有效 LLM provider 配置，将使用默认值（无 API 调用）")
                return cls()
            logger.info(
                f"🤖 已从 .env 加载 provider={pcfg.provider!r}  "
                f"model={pcfg.model!r}"
            )
            return cls(
                api_key=pcfg.api_key or None,
                base_url=pcfg.base_url or None,
                model=pcfg.model,
                temperature=pcfg.temperature,
                max_tokens=pcfg.max_tokens,
                provider=pcfg.provider,
            )
        except Exception as e:
            logger.error(f"❌ 从配置文件加载 LLMConfig 失败: {e}")
            return cls()


# ============================================================
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
    推理管道
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

        # ── LLM 配置：显式传入 > .env ───────────────────────
        if cfg.llm is not None:
            self.llm_config: LLMConfig = cfg.llm
        else:
            self.llm_config: LLMConfig = LLMConfig.from_file()

        self.enable_async_verification: bool = cfg.enable_async_verification
        self.enable_governance: bool = cfg.enable_governance

        # retrieval.py 共享资源（通过 init_retrieval_system 初始化一次）
        self._retrieval_system: Optional[dict] = None

        # OpenAI 兼容客户端（glm5/kimi/minimax/qwen 均通过此客户端调用）
        self._openai = None
        if self.llm_config.api_key:
            self._init_openai()

        # 推理层静态参数（来自 reasoning_config.yaml）
        from .config_loader import load_reasoning_config
        self._rcfg = load_reasoning_config()

    # ================================================================ #
    # ================================================================ #

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """
        执行推理（同步）
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
        流式推理
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
            # 维护已发现引用 ID 的集合，增量检测新引用，避免每个 token 全文扫描
            seen_ids: set[int] = set()
            block_index: dict[int, ContextBlock] = {b.id: b for b in blocks}
            async for token in self._stream_generate(stream_msg):
                full_answer += token
                yield StreamEventToken(content=token)

                # 仅对新 token 做增量匹配
                for cid in self.prompt_builder.extract_citation_ids(token):
                    if cid not in seen_ids and cid in block_index:
                        seen_ids.add(cid)
                        block = block_index[cid]
                        citation = CitationSource(
                            id=block.id,
                            anchor_id=block.anchor_id,
                            title_path=block.title_path,
                            score=block.reranker_score,
                            verification_status=VerificationStatus.PENDING,
                            file_path=self._extract_file_path(block.anchor_id),
                            snippet=block.content[:self._rcfg.snippet_length],
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

    def retrieve_chunks(self, query: str, top_k: int = None) -> List[RetrievedChunk]:
        """
        调用 retrieval.py 检索文档，并转换为 RetrievedChunk 格式。
        top_k 默认值来自 reasoning_config.yaml [retrieval.default_top_k]。

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
        resolved_top_k = top_k if top_k is not None else self._rcfg.default_top_k
        chunks: List[RetrievedChunk] = []
        for i, doc in enumerate(docs[:resolved_top_k]):
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

            # ── 构造 anchor_id（⚠️ 预留接口：步长来自 reasoning_config.yaml [retrieval.anchor_offset_step]）
            estimated_offset = i * self._rcfg.anchor_offset_step
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

    def search_test_chunks(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> tuple[List[RetrievedChunk], RetrievalResponse]:
        """
        使用 interfaces.search_test 检索文档（新版本）
        对应方案.md 3.4.1 ~ 3.4.2

        参数：
            query: 用户查询
            top_k: 期望召回数量，None 时自适应决定

        返回：
            Tuple[List[RetrievedChunk], RetrievalResponse]
            - RetrievedChunk 列表（用于推理层）
            - RetrievalResponse 原始响应（用于调试信息）
        """
        # 调用 interfaces.search_test
        resp = interfaces_search_test(query, top_k=top_k)

        # 转换为 RetrievedChunk 列表
        chunks: List[RetrievedChunk] = []
        for i, chunk_resp in enumerate(resp.retrieved_chunks):
            metadata = chunk_resp.metadata
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_resp.chunk_id,
                    file_path=metadata.file_path,
                    file_hash='',                    # 预留接口
                    content=chunk_resp.content,
                    anchor_id=metadata.anchor_id,
                    title_path=metadata.title_path,
                    char_offset_start=int(metadata.anchor_id.split('#')[-1]) if '#' in metadata.anchor_id else 0,
                    char_offset_end=0,               # 预留接口
                    char_count=len(chunk_resp.content),
                    is_truncated=chunk_resp.is_truncated,
                    chunk_index=i,
                    content_type=chunk_resp.content_type,
                    reranker_score=chunk_resp.score,
                    raw_text=chunk_resp.content,
                )
            )

        return chunks, resp

    def update_llm_config(self, config: LLMConfig) -> None:
        """更新 LLM 配置"""
        self.llm_config = config
        if config.api_key:
            self._init_openai()

    def switch_provider(self, provider: str) -> None:
        """
        切换 LLM provider（从 .env 加载指定 provider 配置）。

        示例：
            pipeline.switch_provider('kimi')
            pipeline.switch_provider('qwen')
        """
        from .config_loader import reload_configs
        reload_configs()   # 清除缓存，支持热重载
        new_cfg = LLMConfig.from_file(provider=provider)
        self.update_llm_config(new_cfg)
        logger.info(f"🔄 已切换 provider: {provider!r}  model={new_cfg.model!r}")

    def set_score_threshold(self, threshold: float) -> None:
        """设置拒答阈值"""
        self.rejection_guard.set_threshold(threshold)

    # ================================================================ #
    # 私有方法                                                           #
    # ================================================================ #

    def _init_openai(self):
        """
        初始化 OpenAI 兼容客户端（openai >= 1.0）。
        glm5 / kimi / minimax / qwen 均通过 base_url 切换接入，
        使用完全相同的 openai.OpenAI 调用方式。
        """
        try:
            from openai import OpenAI  # type: ignore
            init_kwargs: dict = dict(api_key=self.llm_config.api_key)
            if self.llm_config.base_url:
                init_kwargs['base_url'] = self.llm_config.base_url
            self._openai = OpenAI(**init_kwargs)
            logger.info(
                f"✅ LLM 客户端初始化成功: provider={self.llm_config.provider!r}  "
                f"model={self.llm_config.model!r}  base_url={self.llm_config.base_url!r}"
            )
        except ImportError:
            logger.warning("openai 包未安装，LLM 功能不可用。请执行: pip install openai")
            self._openai = None

    def _generate_with_llm(self, prompt: str) -> str:
        """使用 LLM 生成回答"""
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
        """流式生成"""
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
        """后台执行异步验证"""
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
            # 优化：使用 get_running_loop 替代已废弃的 get_event_loop
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            # 没有运行中的事件循环时，新建并运行
            try:
                asyncio.run(_run())
            except Exception:
                pass  # 异步验证失败不影响主流程

    def _extract_claimed_citations(
        self,
        answer: str,
        citations: List[CitationSource],
    ) -> List[ClaimedCitation]:
        """提取引用声明"""
        claimed: List[ClaimedCitation] = []
        used_ids: set[int] = set()
        # 预建引用 ID 集合，避免内层循环 O(n) 扫描
        citation_ids: set[int] = {c.id for c in citations}

        for match in re.finditer(r'\[(\d+)\]', answer):
            cid = int(match.group(1))
            if cid not in used_ids and cid in citation_ids:
                used_ids.add(cid)
                start = max(0, match.start() - self._rcfg.context_window_chars)
                end   = min(len(answer), match.end() + self._rcfg.context_window_chars)
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
        """构建拒答响应"""
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
        """构建无 LLM 响应"""
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
        """计算置信度"""
        if total_count == 0:
            return 0.0
        coverage = valid_count / total_count
        base_score = min(coverage * 1.5, 1.0)
        return round(base_score, 2)

    def _extract_file_path(self, anchor_id: str) -> str:
        """从 anchorId 提取文件路径"""
        parts = anchor_id.split('#')
        return parts[0] if parts else anchor_id


def create_reasoning_pipeline(
    config: ReasoningPipelineConfig = None,
) -> ReasoningPipeline:
    """创建推理管道"""
    return ReasoningPipeline(config)
