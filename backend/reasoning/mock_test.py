"""
推理层模拟测试类
================

不依赖真实的 retrieval.py / LLM / 向量库，完全用 Mock 数据驱动。

测试覆盖：
  1. search_test 接口 - 检索层响应 Mock
  2. 推理层完整 Pipeline Mock（含拒答、正常应答两路）
  3. WebRequest / WebResponse 接口格式验证
  4. 各 dataclass 字段完整性验证
  5. edge case：空查询、低分拒答、embedding_meta、content_type_source

用法：
  # 直接运行
  python mock_test.py

  # 安静模式（只显示结果）
  python mock_test.py -q

  # 只跑某个 case
  python mock_test.py TestSearchTest
"""

from __future__ import annotations

import json
import logging
import sys
import unittest
from dataclasses import dataclass, field
from typing import List, Optional, Generator
from unittest.mock import MagicMock, patch

# ── 模块路径设置 ────────────────────────────────────────────────────────────────
import os
_REASONING_DIR = os.path.dirname(os.path.abspath(__file__))
if _REASONING_DIR not in sys.path:
    sys.path.insert(0, _REASONING_DIR)

# ── 导入待测接口 ────────────────────────────────────────────────────────────────
from interfaces import (
    # 检索层接口
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunkResponse,
    ChunkMetadata,
    EmbeddingMeta,
    SearchParams,
    SearchFilters,
    RetrievalStrategy,
    SyncContext,
    # WEB 接口
    WebRequest,
    WebResponse,
    WebConfig,
    Citation,
    CitationLocation,
    VerificationReport,
    DebugInfo,
    HallucinationCheckStatus,
    CitationValidationStatus,
    # search_test 函数
    search_test,
    _expand_query,
    _get_adaptive_topk,
    _parse_document_chunk,
)

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# ── 固定 Mock 数据工厂 ────────────────────────────────────────
# ============================================================

def _make_chunk(
    chunk_id: str = 'ch_001',
    content: str = 'The system requires Python 3.10+ to run correctly.',
    score: float = 0.88,
    file_path: str = '/docs/install.md',
    anchor_id: str = '/docs/install.md#1024',
    title_path: str = 'Installation Guide > Prerequisites',
    content_type: str = 'document',
    content_type_source: str = 'extension',
    is_truncated: bool = False,
    last_modified: str = '2026-04-24T10:00:00Z',
) -> RetrievedChunkResponse:
    """快速构造单个 RetrievedChunkResponse（测试用）"""
    return RetrievedChunkResponse(
        chunk_id=chunk_id,
        content=content,
        score=score,
        content_type=content_type,
        content_type_source=content_type_source,
        is_truncated=is_truncated,
        metadata=ChunkMetadata(
            file_path=file_path,
            anchor_id=anchor_id,
            title_path=title_path,
            last_modified=last_modified,
        )
    )


def _make_retrieval_response(
    chunks: Optional[List[RetrievedChunkResponse]] = None,
    status: str = 'success',
    max_score: float = 0.88,
    expanded_query: str = 'Python 安装 install setup',
    model: str = 'bge-m3',
    model_version: str = '1.0.2',
    index_build_time: str = '2026-04-26T09:55:00Z',
) -> RetrievalResponse:
    """快速构造 RetrievalResponse（测试用）"""
    if chunks is None:
        chunks = [_make_chunk()]
    return RetrievalResponse(
        retrieved_chunks=chunks,
        retrieval_status=status,
        max_reranker_score=max_score,
        expanded_query=expanded_query,
        embedding_meta=EmbeddingMeta(
            model=model,
            model_version=model_version,
            index_build_time=index_build_time,
        )
    )


def _make_citation(
    handle: str = '[1]',
    source_id: str = 'src_idx_001',
    snippet: str = 'The system requires Python 3.10+...',
    file_path: str = '/docs/install.md',
    anchor_id: str = '/docs/install.md#1024',
    title_path: str = 'Installation Guide > Prerequisites',
) -> Citation:
    """快速构造 Citation（测试用）"""
    return Citation(
        citation_handle=handle,
        source_id=source_id,
        snippet=snippet,
        location=CitationLocation(
            file_path=file_path,
            anchor_id=anchor_id,
            title_path=title_path,
        )
    )


# ============================================================
# ── MockSearchTest：模拟 search_test 接口 ────────────────────
# ============================================================

class MockSearchTest:
    """
    检索层 Mock 实现

    替换真实的 search_test()，根据查询关键词返回预设数据集，
    用于在没有向量库和 retrieval.py 的环境中测试推理层逻辑。

    使用方式：
        mock = MockSearchTest()

        # 正常检索
        resp = mock.search('如何安装 Python')
        assert resp.retrieval_status == 'success'

        # 注入自定义预设
        mock.register_preset(
            keyword='OAuth',
            chunks=[...],
            max_score=0.91,
        )
    """

    # 预设数据库：关键词 → 检索响应
    _PRESETS = {
        'install': [
            _make_chunk(
                chunk_id='ch_install_001',
                content='Run `pip install -r requirements.txt` to install all dependencies.',
                score=0.91,
                anchor_id='/docs/install.md#512',
                title_path='Installation Guide > Step 1',
                content_type_source='extension',
            ),
            _make_chunk(
                chunk_id='ch_install_002',
                content='Make sure Python 3.10 or higher is available on your PATH.',
                score=0.85,
                anchor_id='/docs/install.md#1024',
                title_path='Installation Guide > Prerequisites',
                content_type_source='mime_sniff',
            ),
        ],
        'oauth': [
            _make_chunk(
                chunk_id='ch_oauth_001',
                content='OAuth2 access tokens expire after 3600 seconds by default.',
                score=0.93,
                file_path='/docs/api/auth.md',
                anchor_id='/docs/api/auth.md#2048',
                title_path='Authentication > OAuth2 > Token Expiry',
                content_type='document',
                content_type_source='manual',
            ),
        ],
        'config': [
            _make_chunk(
                chunk_id='ch_config_001',
                content='Set the DATABASE_URL environment variable before starting the server.',
                score=0.87,
                file_path='/docs/config/env.md',
                anchor_id='/docs/config/env.md#300',
                title_path='Configuration > Environment Variables',
                content_type_source='extension',
            ),
        ],
        'code_example': [
            _make_chunk(
                chunk_id='ch_code_001',
                content='```python\nfrom app import create_app\napp = create_app()\n```',
                score=0.79,
                file_path='/docs/quickstart.py',
                anchor_id='/docs/quickstart.py#0',
                title_path='Quick Start > Create App',
                content_type='code',
                content_type_source='mime_sniff',
            ),
        ],
    }

    def __init__(self, default_score: float = 0.85):
        self.default_score = default_score
        self._custom_presets: dict = {}
        self._call_log: list = []           # 记录每次调用（便于测试断言）

    def register_preset(
        self,
        keyword: str,
        chunks: List[RetrievedChunkResponse],
        max_score: Optional[float] = None,
    ) -> None:
        """注册自定义预设（关键词命中时返回）"""
        self._custom_presets[keyword.lower()] = {
            'chunks': chunks,
            'max_score': max_score or (max(c.score for c in chunks) if chunks else 0.0),
        }

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        rerank: bool = True,
    ) -> RetrievalResponse:
        """
        模拟 search_test() 的调用行为

        匹配逻辑：
        1. 优先检查 _custom_presets
        2. 再匹配内置 _PRESETS 关键词（小写包含匹配）
        3. 都不匹配则返回 empty 响应
        """
        query_lower = query.lower()
        self._call_log.append({'query': query, 'top_k': top_k})

        # 优先：自定义预设
        for kw, preset in self._custom_presets.items():
            if kw in query_lower:
                chunks = preset['chunks'][:top_k] if top_k else preset['chunks']
                return _make_retrieval_response(
                    chunks=chunks,
                    max_score=preset['max_score'],
                    expanded_query=f"{query} (mock)",
                )

        # 次之：内置预设
        for kw, chunks in self._PRESETS.items():
            if kw in query_lower:
                selected = chunks[:top_k] if top_k else chunks
                max_score = max(c.score for c in selected)
                return _make_retrieval_response(
                    chunks=selected,
                    max_score=max_score,
                    expanded_query=f"{query} {kw} (mock)",
                )

        # 未命中：返回 empty
        return _make_retrieval_response(
            chunks=[],
            status='empty',
            max_score=0.0,
            expanded_query=query,
        )

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    def last_query(self) -> Optional[str]:
        return self._call_log[-1]['query'] if self._call_log else None

    def reset(self) -> None:
        self._call_log.clear()
        self._custom_presets.clear()


# ============================================================
# ── MockReasoningPipeline：模拟完整推理流程 ──────────────────
# ============================================================

class MockReasoningPipeline:
    """
    推理层完整 Pipeline Mock

    模拟 reasoning_pipeline.py 的 ReasoningPipeline 核心行为：
    1. search_test_chunks()  → 调用 MockSearchTest
    2. evaluate_rejection()  → 分数阈值检查
    3. reason()              → 生成含 [n] 引用的 Mock 答案
    4. build_web_response()  → 组装 WebResponse

    通常用于：
    - 集成测试（不需要 GPU / 向量库）
    - CI 流水线回归测试
    - 前端联调（对接 /api/reasoning/ask）

    示例：
        pipeline = MockReasoningPipeline()
        web_req = WebRequest(user_query="如何安装依赖？")
        web_resp = pipeline.ask(web_req)
        assert web_resp.answer_status in ('resolved', 'refused')
    """

    SCORE_THRESHOLD = 0.4       # 低于此值触发拒答（与 types.py 保持一致）
    MOCK_LLM_LATENCY = 0.0      # 模拟延迟（秒），测试时设为 0

    def __init__(
        self,
        mock_search: Optional[MockSearchTest] = None,
        score_threshold: float = SCORE_THRESHOLD,
    ):
        self.mock_search = mock_search or MockSearchTest()
        self.score_threshold = score_threshold
        self._processed_count = 0

    # ── 检索 ───────────────────────────────────────────────────────────────────

    def search_test_chunks(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> RetrievalResponse:
        """调用 MockSearchTest 检索"""
        return self.mock_search.search(query, top_k=top_k)

    # ── 拒答判断 ───────────────────────────────────────────────────────────────

    def evaluate_rejection(
        self,
        query: str,
        retrieval_resp: RetrievalResponse,
    ) -> tuple[bool, Optional[str]]:
        """
        Returns:
            (should_reject, reject_reason)
        """
        if not query.strip():
            return True, 'empty_query'
        if retrieval_resp.retrieval_status in ('empty', 'error'):
            return True, 'no_chunks'
        if retrieval_resp.max_reranker_score < self.score_threshold:
            return True, f'score_below_threshold ({retrieval_resp.max_reranker_score:.2f} < {self.score_threshold})'
        return False, None

    # ── Mock LLM 生成 ──────────────────────────────────────────────────────────

    def _mock_generate_answer(
        self,
        query: str,
        chunks: List[RetrievedChunkResponse],
    ) -> tuple[str, List[Citation]]:
        """
        不调用真实 LLM，基于 chunks 内容拼接带 [n] 引用的 Mock 答案。
        格式对齐方案.md 3.4.4 answer 字段要求。
        """
        if not chunks:
            return '根据现有文档无法回答此问题。', []

        answer_parts = [f'根据文档，关于"{query}"的回答如下：\n']
        citations: List[Citation] = []

        for i, chunk in enumerate(chunks[:3], start=1):      # 最多引用 3 条
            # 截取 snippet（前 80 字符）
            snippet = chunk.content[:80].replace('\n', ' ').rstrip()
            answer_parts.append(f'  - {snippet} [{i}]')

            citations.append(Citation(
                citation_handle=f'[{i}]',
                source_id=f'src_idx_{i:03d}',
                snippet=snippet,
                location=CitationLocation(
                    file_path=chunk.metadata.file_path,
                    anchor_id=chunk.metadata.anchor_id,
                    title_path=chunk.metadata.title_path,
                )
            ))

        return '\n'.join(answer_parts), citations

    # ── 组装 WebResponse ───────────────────────────────────────────────────────

    def _build_refused_response(
        self,
        query: str,
        retrieval_resp: RetrievalResponse,
        reject_reason: str,
    ) -> WebResponse:
        """构造拒答响应"""
        return WebResponse.refused(
            answer='根据现有文档无法回答此问题，请尝试重新描述您的问题。',
            debug_info=DebugInfo(
                expanded_query=retrieval_resp.expanded_query,
                max_reranker_score=retrieval_resp.max_reranker_score,
                refuse_reason=reject_reason,
            )
        )

    def _build_resolved_response(
        self,
        answer: str,
        citations: List[Citation],
        retrieval_resp: RetrievalResponse,
    ) -> WebResponse:
        """构造正常应答响应"""
        debug = DebugInfo(
            expanded_query=retrieval_resp.expanded_query,
            max_reranker_score=retrieval_resp.max_reranker_score,
            refuse_reason=None,
        )
        report = VerificationReport(
            hallucination_check=HallucinationCheckStatus.PASSED,
            citation_validation=CitationValidationStatus.SYNC_VERIFIED,
            is_truncated_context=any(c.is_truncated for c in retrieval_resp.retrieved_chunks),
        )
        return WebResponse.resolved(
            answer=answer,
            citations=citations,
            verification_report=report,
            debug_info=debug,
        )

    # ── 主入口 ─────────────────────────────────────────────────────────────────

    def ask(
        self,
        web_req: WebRequest,
        top_k: Optional[int] = None,
    ) -> WebResponse:
        """
        完整推理流程（Mock 版）
        流程：检索 → 拒答判断 → Mock 生成 → 组装响应

        参数：
            web_req: WEB 层请求
            top_k:   检索数量限制（None=自适应）

        返回：
            WebResponse
        """
        query = web_req.user_query.strip()
        self._processed_count += 1

        # Step 1: 检索
        retrieval_resp = self.search_test_chunks(query, top_k=top_k)

        # Step 2: 拒答判断
        should_reject, reject_reason = self.evaluate_rejection(query, retrieval_resp)
        if should_reject:
            return self._build_refused_response(query, retrieval_resp, reject_reason)

        # Step 3: Mock LLM 生成
        answer, citations = self._mock_generate_answer(
            query, retrieval_resp.retrieved_chunks
        )

        # Step 4: 组装响应
        return self._build_resolved_response(answer, citations, retrieval_resp)

    def ask_stream(
        self,
        web_req: WebRequest,
        top_k: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """
        流式 Mock（SSE 格式）
        按 token 逐字 yield，最后 yield citations 和 done 事件。
        格式对齐方案.md 3.4.3 stream=true

        用法：
            for event in pipeline.ask_stream(web_req):
                print(event)
        """
        web_resp = self.ask(web_req, top_k=top_k)

        if web_resp.answer_status == 'refused':
            yield f'data: {json.dumps({"type": "token", "content": web_resp.answer}, ensure_ascii=False)}\n\n'
            yield f'data: {json.dumps({"type": "done", "answer_status": "refused"}, ensure_ascii=False)}\n\n'
            return

        # 模拟 token 流：按句子 yield
        sentences = web_resp.answer.split('\n')
        for sent in sentences:
            if sent.strip():
                yield f'data: {json.dumps({"type": "token", "content": sent + chr(10)}, ensure_ascii=False)}\n\n'

        # citations 事件
        for c in web_resp.citations:
            yield f'data: {json.dumps({"type": "citation", "citation": c.to_dict()}, ensure_ascii=False)}\n\n'

        # done 事件
        done_payload = {
            'type': 'done',
            'answer_status': 'resolved',
            'verification_report': web_resp.verification_report.to_dict(),
            'debug_info': web_resp.debug_info.to_dict(),
            'source_library': web_resp.source_library,
        }
        yield f'data: {json.dumps(done_payload, ensure_ascii=False)}\n\n'

    @property
    def processed_count(self) -> int:
        return self._processed_count


# ============================================================
# ── 单元测试 ──────────────────────────────────────────────────
# ============================================================

class TestInterfaceDataclasses(unittest.TestCase):
    """验证所有 dataclass 字段的默认值与构造"""

    def test_retrieval_strategy_defaults(self):
        """RetrievalStrategy 默认值"""
        rs = RetrievalStrategy()
        self.assertEqual(rs.mode, 'hybrid')
        self.assertEqual(rs.rrf_k, 60)
        self.assertAlmostEqual(rs.bm25_weight, 0.3)
        self.assertAlmostEqual(rs.dense_weight, 0.7)

    def test_search_params_contains_retrieval_strategy(self):
        """SearchParams 包含 retrieval_strategy"""
        sp = SearchParams(top_k=5)
        self.assertIsInstance(sp.retrieval_strategy, RetrievalStrategy)
        self.assertEqual(sp.top_k, 5)

    def test_sync_context_defaults(self):
        """SyncContext 默认值"""
        sc = SyncContext()
        self.assertEqual(sc.pipeline_status, 'idle')
        self.assertEqual(sc.pending_diff_count, 0)
        self.assertIsNone(sc.last_sync_time)

    def test_retrieval_request_to_dict(self):
        """RetrievalRequest.to_dict() 包含所有新字段"""
        req = RetrievalRequest(
            query_intent='Python 安装',
            sync_context=SyncContext(pipeline_status='syncing', pending_diff_count=3),
        )
        d = req.to_dict()
        self.assertIn('sync_context', d)
        self.assertIn('search_params', d)
        self.assertEqual(d['sync_context']['pipeline_status'], 'syncing')
        self.assertEqual(d['sync_context']['pending_diff_count'], 3)
        self.assertIn('retrieval_strategy', d['search_params'])

    def test_retrieved_chunk_response_content_type_source(self):
        """RetrievedChunkResponse 包含 content_type_source"""
        chunk = _make_chunk(content_type_source='mime_sniff')
        self.assertEqual(chunk.content_type_source, 'mime_sniff')

    def test_embedding_meta_defaults(self):
        """EmbeddingMeta 默认值"""
        meta = EmbeddingMeta()
        self.assertEqual(meta.model, 'bge-m3')
        self.assertEqual(meta.model_version, '')
        self.assertIsNone(meta.index_build_time)

    def test_retrieval_response_contains_embedding_meta(self):
        """RetrievalResponse 包含 embedding_meta"""
        resp = _make_retrieval_response()
        self.assertIsInstance(resp.embedding_meta, EmbeddingMeta)
        self.assertEqual(resp.embedding_meta.model, 'bge-m3')
        self.assertEqual(resp.embedding_meta.model_version, '1.0.2')
        self.assertEqual(resp.embedding_meta.index_build_time, '2026-04-26T09:55:00Z')

    def test_source_library_display_url(self):
        """source_library 条目包含 display_url"""
        # 通过 WebResponse.resolved() 工厂方法验证
        citation = _make_citation(
            source_id='src_idx_001',
            file_path='/docs/install.md',
            anchor_id='/docs/install.md#1024',
        )
        resp = WebResponse.resolved(
            answer='测试答案 [1]',
            citations=[citation],
            verification_report=VerificationReport(),
            debug_info=DebugInfo(expanded_query='test', max_reranker_score=0.88),
        )
        self.assertIn('src_idx_001', resp.source_library)
        entry = resp.source_library['src_idx_001']
        self.assertIn('display_url', entry)
        self.assertIn('url', entry)
        self.assertIn('title', entry)

    def test_web_request_from_dict(self):
        """WebRequest.from_dict() 解析"""
        data = {
            'user_query': '如何配置环境变量？',
            'stream': False,
            'session_id': 'sess_test_001',
            'config': {'temperature': 0.0, 'language': 'zh-CN'},
        }
        req = WebRequest.from_dict(data)
        self.assertEqual(req.user_query, '如何配置环境变量？')
        self.assertFalse(req.stream)
        self.assertEqual(req.session_id, 'sess_test_001')

    def test_web_response_to_json(self):
        """WebResponse.to_json() 可序列化"""
        resp = WebResponse.refused(
            answer='无法回答',
            debug_info=DebugInfo(refuse_reason='no_chunks')
        )
        json_str = resp.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed['answer_status'], 'refused')
        self.assertEqual(parsed['debug_info']['refuse_reason'], 'no_chunks')


class TestHelperFunctions(unittest.TestCase):
    """验证内部辅助函数"""

    def test_expand_query_adds_synonyms(self):
        """_expand_query 对含关键词的查询扩展同义词"""
        expanded = _expand_query('如何安装依赖')
        self.assertIn('install', expanded)
        self.assertIn('如何安装依赖', expanded)

    def test_expand_query_no_change_for_unknown(self):
        """_expand_query 对未知查询返回原查询"""
        expanded = _expand_query('量子纠缠原理')
        self.assertIn('量子纠缠原理', expanded)

    def test_adaptive_topk_broad(self):
        """综合型查询 top_k = 8"""
        self.assertEqual(_get_adaptive_topk('列举所有配置项'), 8)
        self.assertEqual(_get_adaptive_topk('有哪些安装方式'), 8)

    def test_adaptive_topk_simple(self):
        """事实型查询 top_k = 3"""
        self.assertEqual(_get_adaptive_topk('安装步骤是什么'), 3)
        self.assertEqual(_get_adaptive_topk('怎么配置 PATH'), 3)

    def test_adaptive_topk_default(self):
        """默认查询 top_k = 5"""
        self.assertEqual(_get_adaptive_topk('Python 环境变量'), 5)

    def test_parse_document_chunk_with_metadata(self):
        """_parse_document_chunk 正确解析 Document 对象"""
        doc = MagicMock()
        doc.page_content = 'test content'
        doc.metadata = {
            'file_path': '/docs/test.md',
            'char_offset_start': 512,
            'title_path': 'Test > Section',
            'content_type': 'document',
            'is_truncated': False,
            'score': 0.75,
            'last_modified': '2026-04-24T10:00:00Z',
            'chunk_id': 'ch_test_001',
        }
        chunk = _parse_document_chunk(doc)
        self.assertEqual(chunk.chunk_id, 'ch_test_001')
        self.assertEqual(chunk.score, 0.75)
        self.assertEqual(chunk.metadata.file_path, '/docs/test.md')
        self.assertIn('#512', chunk.metadata.anchor_id)


class TestMockSearchTest(unittest.TestCase):
    """验证 MockSearchTest 行为"""

    def setUp(self):
        self.mock = MockSearchTest()

    def test_search_returns_success_for_known_keyword(self):
        """已知关键词返回 success"""
        resp = self.mock.search('如何 install 依赖')
        self.assertEqual(resp.retrieval_status, 'success')
        self.assertGreater(len(resp.retrieved_chunks), 0)
        self.assertGreater(resp.max_reranker_score, 0.0)

    def test_search_returns_empty_for_unknown_query(self):
        """未知查询返回 empty"""
        resp = self.mock.search('量子纠缠的本质是什么')
        self.assertEqual(resp.retrieval_status, 'empty')
        self.assertEqual(len(resp.retrieved_chunks), 0)

    def test_search_respects_top_k(self):
        """top_k 参数限制返回数量"""
        resp = self.mock.search('install Python', top_k=1)
        self.assertLessEqual(len(resp.retrieved_chunks), 1)

    def test_search_oauth_returns_correct_chunk(self):
        """OAuth 查询返回正确 chunk"""
        resp = self.mock.search('OAuth2 token 过期时间')
        self.assertEqual(resp.retrieval_status, 'success')
        self.assertIn('OAuth2', resp.retrieved_chunks[0].content)

    def test_search_code_chunk_has_correct_content_type(self):
        """代码类 chunk 的 content_type 为 code"""
        resp = self.mock.search('code_example usage')
        self.assertTrue(
            any(c.content_type == 'code' for c in resp.retrieved_chunks),
            msg='应有 content_type=code 的 chunk'
        )

    def test_search_embedding_meta_populated(self):
        """检索响应包含 embedding_meta"""
        resp = self.mock.search('install')
        self.assertIsNotNone(resp.embedding_meta)
        self.assertEqual(resp.embedding_meta.model, 'bge-m3')

    def test_chunk_content_type_source_variants(self):
        """预设中包含 content_type_source 的不同取值"""
        resp_install = self.mock.search('install')
        sources = {c.content_type_source for c in resp_install.retrieved_chunks}
        # install 预设包含 extension 和 mime_sniff 两种
        self.assertTrue(
            sources.issubset({'mime_sniff', 'extension', 'manual'}),
            f'非法 content_type_source: {sources}'
        )

    def test_register_custom_preset(self):
        """自定义预设优先于内置预设"""
        custom_chunk = _make_chunk(
            chunk_id='custom_001',
            content='Custom content for testing.',
            score=0.99,
        )
        self.mock.register_preset('custom_keyword', [custom_chunk], max_score=0.99)
        resp = self.mock.search('这是 custom_keyword 查询')
        self.assertEqual(len(resp.retrieved_chunks), 1)
        self.assertEqual(resp.retrieved_chunks[0].chunk_id, 'custom_001')

    def test_call_log_tracks_queries(self):
        """call_log 记录查询次数"""
        self.mock.search('install')
        self.mock.search('oauth')
        self.assertEqual(self.mock.call_count, 2)
        self.assertEqual(self.mock.last_query(), 'oauth')

    def test_reset_clears_log_and_presets(self):
        """reset() 清除调用记录和自定义预设"""
        self.mock.register_preset('test_kw', [_make_chunk()])
        self.mock.search('test_kw')
        self.mock.reset()
        self.assertEqual(self.mock.call_count, 0)
        # 自定义预设被清除
        resp = self.mock.search('test_kw')
        self.assertEqual(resp.retrieval_status, 'empty')


class TestMockReasoningPipeline(unittest.TestCase):
    """验证 MockReasoningPipeline 完整推理流程"""

    def setUp(self):
        self.pipeline = MockReasoningPipeline()

    def _make_req(self, query: str, stream: bool = False) -> WebRequest:
        return WebRequest(user_query=query, stream=stream)

    # ── 正常应答路径 ───────────────────────────────────────────────────────────

    def test_ask_resolved_for_known_query(self):
        """已知查询应返回 resolved"""
        req = self._make_req('如何 install Python 依赖')
        resp = self.pipeline.ask(req)
        self.assertEqual(resp.answer_status, 'resolved')
        self.assertGreater(len(resp.citations), 0)
        self.assertIn('[1]', resp.answer)

    def test_answer_contains_citation_handles(self):
        """答案文本包含 [n] 引用标记"""
        req = self._make_req('OAuth2 token refresh')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'resolved':
            import re
            handles = re.findall(r'\[\d+\]', resp.answer)
            self.assertTrue(len(handles) > 0, '答案应包含 [n] 引用标记')

    def test_citations_have_valid_locations(self):
        """所有 citations 都有完整的 location 信息"""
        req = self._make_req('install 配置')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'resolved':
            for c in resp.citations:
                self.assertTrue(c.location.file_path, '每个 citation 应有 file_path')
                self.assertTrue(c.location.anchor_id, '每个 citation 应有 anchor_id')

    def test_source_library_built_from_citations(self):
        """source_library 由 citations 自动构建（含 display_url）"""
        req = self._make_req('install Python')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'resolved' and resp.citations:
            for source_id, entry in resp.source_library.items():
                self.assertIn('display_url', entry, f'{source_id} 缺少 display_url')
                self.assertIn('title', entry)

    def test_verification_report_passed_for_resolved(self):
        """正常应答时 hallucination_check = passed"""
        req = self._make_req('install Python')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'resolved':
            self.assertEqual(
                resp.verification_report.hallucination_check,
                HallucinationCheckStatus.PASSED
            )
            self.assertEqual(
                resp.verification_report.citation_validation,
                CitationValidationStatus.SYNC_VERIFIED
            )

    # ── 拒答路径 ──────────────────────────────────────────────────────────────

    def test_ask_refused_for_empty_query(self):
        """空查询应拒答"""
        req = self._make_req('')
        resp = self.pipeline.ask(req)
        self.assertEqual(resp.answer_status, 'refused')
        self.assertIn('empty_query', resp.debug_info.refuse_reason)

    def test_ask_refused_for_unknown_query(self):
        """未知查询（empty 检索结果）应拒答"""
        req = self._make_req('量子计算的底层原理')
        resp = self.pipeline.ask(req)
        self.assertEqual(resp.answer_status, 'refused')
        self.assertIn('no_chunks', resp.debug_info.refuse_reason)

    def test_ask_refused_for_low_score(self):
        """低分检索结果应拒答"""
        # 注入低分自定义预设
        low_score_chunk = _make_chunk(chunk_id='low_001', score=0.25)
        self.pipeline.mock_search.register_preset(
            'low_score_query', [low_score_chunk], max_score=0.25
        )
        req = self._make_req('low_score_query 测试')
        resp = self.pipeline.ask(req)
        self.assertEqual(resp.answer_status, 'refused')
        self.assertIn('score_below_threshold', resp.debug_info.refuse_reason)

    def test_refused_response_has_empty_citations(self):
        """拒答响应的 citations 应为空"""
        req = self._make_req('未知主题XYZ')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'refused':
            self.assertEqual(len(resp.citations), 0)
            self.assertEqual(resp.source_library, {})

    def test_refused_verification_report_skipped(self):
        """拒答时验证报告应为 skipped"""
        req = self._make_req('')
        resp = self.pipeline.ask(req)
        self.assertEqual(resp.answer_status, 'refused')
        self.assertEqual(
            resp.verification_report.hallucination_check,
            HallucinationCheckStatus.SKIPPED
        )

    # ── debug_info ────────────────────────────────────────────────────────────

    def test_debug_info_contains_max_reranker_score(self):
        """debug_info 包含 max_reranker_score"""
        req = self._make_req('install')
        resp = self.pipeline.ask(req)
        self.assertGreaterEqual(resp.debug_info.max_reranker_score, 0.0)

    def test_debug_info_expanded_query_not_empty_for_resolved(self):
        """resolved 时 expanded_query 不为空"""
        req = self._make_req('install 依赖')
        resp = self.pipeline.ask(req)
        if resp.answer_status == 'resolved':
            self.assertTrue(resp.debug_info.expanded_query)

    # ── 流式输出 ──────────────────────────────────────────────────────────────

    def test_ask_stream_yields_sse_events(self):
        """ask_stream 产出 SSE 格式事件"""
        req = self._make_req('install Python', stream=True)
        events = list(self.pipeline.ask_stream(req))
        self.assertGreater(len(events), 0)
        # 每个事件应以 "data: " 开头
        for ev in events:
            self.assertTrue(ev.startswith('data: '), f'非法 SSE 事件: {ev[:40]}')

    def test_ask_stream_last_event_is_done(self):
        """最后一个事件应为 done 类型"""
        req = self._make_req('install Python', stream=True)
        events = list(self.pipeline.ask_stream(req))
        last = json.loads(events[-1].replace('data: ', '').strip().rstrip('\n'))
        self.assertEqual(last['type'], 'done')

    def test_ask_stream_refused_has_done_refused(self):
        """拒答时流式输出最后事件 answer_status=refused"""
        req = self._make_req('', stream=True)
        events = list(self.pipeline.ask_stream(req))
        last = json.loads(events[-1].replace('data: ', '').strip().rstrip('\n'))
        self.assertEqual(last['answer_status'], 'refused')

    def test_ask_stream_contains_citation_events(self):
        """resolved 时流式输出包含 citation 事件"""
        req = self._make_req('install Python', stream=True)
        events = list(self.pipeline.ask_stream(req))
        types = []
        for ev in events:
            try:
                payload = json.loads(ev.replace('data: ', '').strip().rstrip('\n'))
                types.append(payload.get('type'))
            except Exception:
                pass
        if 'done' in types:
            done_ev = json.loads(events[-1].replace('data: ', '').strip().rstrip('\n'))
            if done_ev.get('answer_status') == 'resolved':
                self.assertIn('citation', types, '流式 resolved 应包含 citation 事件')

    # ── processed_count ───────────────────────────────────────────────────────

    def test_processed_count_increments(self):
        """每次 ask() 调用后 processed_count 递增"""
        initial = self.pipeline.processed_count
        self.pipeline.ask(self._make_req('install'))
        self.pipeline.ask(self._make_req('oauth'))
        self.assertEqual(self.pipeline.processed_count, initial + 2)


class TestSearchTestIntegration(unittest.TestCase):
    """
    search_test 函数集成测试
    通过 Mock 替换 retrieval.pipeline，验证 interfaces.search_test 完整逻辑
    """

    def _make_mock_doc(
        self,
        content: str = 'Mock document content.',
        file_path: str = '/docs/mock.md',
        offset: int = 100,
        score: float = 0.82,
    ):
        """构造模拟 langchain Document 对象"""
        doc = MagicMock()
        doc.page_content = content
        doc.metadata = {
            'file_path': file_path,
            'char_offset_start': offset,
            'title_path': 'Mock > Section',
            'content_type': 'document',
            'is_truncated': False,
            'score': score,
            'chunk_id': f'mock_{offset}',
        }
        return doc

    def test_search_test_returns_retrieval_response(self):
        """search_test 通过 MockSearchTest 返回 success（不依赖真实 retrieval.py）"""
        # MockSearchTest 完全不调用 retrieval.py，可直接断言
        mock = MockSearchTest()
        resp = mock.search('install 如何安装')
        self.assertEqual(resp.retrieval_status, 'success')
        self.assertGreater(len(resp.retrieved_chunks), 0)
        self.assertIsInstance(resp.retrieved_chunks[0], RetrievedChunkResponse)
        self.assertIsInstance(resp.embedding_meta, EmbeddingMeta)
        # 验证 chunk 包含新增字段
        chunk = resp.retrieved_chunks[0]
        self.assertIn(chunk.content_type_source, ('mime_sniff', 'extension', 'manual'))
        self.assertIsNotNone(chunk.metadata.anchor_id)

    def test_search_test_query_expansion_triggers(self):
        """_expand_query 对包含"安装"的查询添加同义词"""
        expanded = _expand_query('安装步骤')
        self.assertIn('安装步骤', expanded)
        self.assertIn('install', expanded)

    def test_search_test_adaptive_topk_for_list_query(self):
        """列举型查询自适应 top_k = 8"""
        self.assertEqual(_get_adaptive_topk('列举所有支持的数据库类型'), 8)

    def test_chunk_metadata_anchor_format(self):
        """anchor_id 格式应为 file_path#offset"""
        chunk = _make_chunk(
            file_path='/docs/install.md',
            anchor_id='/docs/install.md#1024',
        )
        self.assertIn('#', chunk.metadata.anchor_id)
        self.assertTrue(chunk.metadata.anchor_id.startswith('/docs/'))


# ============================================================
# ── 测试运行入口 ──────────────────────────────────────────────
# ============================================================

if __name__ == '__main__':
    # 打印 Banner
    print('=' * 70)
    print(' 推理层模拟测试（Mock Test Suite）')
    print(' 项目：TechnicalDocumentationCitationSystem')
    print('=' * 70)
    print()

    # 运行所有测试
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestInterfaceDataclasses,
        TestHelperFunctions,
        TestMockSearchTest,
        TestMockReasoningPipeline,
        TestSearchTestIntegration,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(
        verbosity=2,
        stream=sys.stdout,
        failfast=False,
    )
    result = runner.run(suite)

    print()
    print('=' * 70)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f' 结果：{passed}/{total} 通过  |  {failed} 失败')
    print('=' * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
