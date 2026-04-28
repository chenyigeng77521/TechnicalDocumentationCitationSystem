"""
推理与引用层 - WebUI 接口
为 WebUI 提供 REST API 和 WebSocket 接口

注意：webui.ts 依赖 DatabaseManager（TS 数据处理层），
检索直接通过 reasoning_pipeline.retrieve_chunks() 调用 retrieval.py。
"""

from __future__ import annotations
import json
import logging
import asyncio
import uuid
from typing import Optional, Dict, Any

from flask import Flask, Blueprint, request, jsonify, Response  # type: ignore

try:
    from flask_sock import Sock  # type: ignore
    _FLASK_SOCK_AVAILABLE = True
except ImportError:
    Sock = None  # type: ignore
    _FLASK_SOCK_AVAILABLE = False

from ._types import (
    ReasoningRequest,
    CitationSource,
    VerificationResult,
    RERANKER_SCORE_THRESHOLD,
)
from .reasoning_pipeline import (
    ReasoningPipeline,
    ReasoningPipelineConfig,
    LLMConfig,
    create_reasoning_pipeline,
)
from ._types import (
    StreamEventToken,
    StreamEventCitation,
    StreamEventDone,
    StreamEventError,
)
from .rejection_guard import safety_check_refusal_rate

logger = logging.getLogger(__name__)


# ============================================================
# ============================================================
class ReasoningWebUI:
    """
    推理与引用层 WebUI 服务

    差异说明（相对于 TS 版）：
    - TS 版通过 setDatabase(DatabaseManager) 获取 chunks
    - Python 版直接通过 pipeline.search_test_chunks() 调用 retrieval.py
    - WebSocket 使用 flask-sock 而非 ws 库（⚠️ 预留接口）
    """

    def __init__(self, config: ReasoningPipelineConfig = None):
        self.pipeline = create_reasoning_pipeline(config)
        self._ws_clients: Dict[str, Any] = {}
        # 会话级统计，用于防全拒答保护（safety_check_refusal_rate）
        self._session_stats: Dict[str, int] = {'total': 0, 'refused': 0}

    # ------------------------------------------------------------------ #
    # ⚠️ 预留接口：如果后续需要接入 TS DatabaseManager，在此添加适配器      #
    # ------------------------------------------------------------------ #

    def create_blueprint(self, url_prefix: str = '/api/reasoning') -> Blueprint:
        """
        创建 Flask Blueprint
        """
        bp = Blueprint('reasoning', __name__, url_prefix=url_prefix)

        @bp.route('/ask', methods=['POST'])
        def ask():
            data = request.get_json(force=True) or {}
            question = data.get('question', '').strip()
            if not question:
                return jsonify({'success': False, 'error': '问题不能为空'}), 400

            try:
                top_k = int(data.get('topK')) if data.get('topK') is not None else None
                strict_mode = data.get('strictMode', None)
                enable_async = data.get('enableAsyncVerification', None)

                resp = self._ask_internal(question, top_k, strict_mode, enable_async)
                return jsonify({'success': True, **resp})
            except Exception as e:
                logger.error(f"❌ 问答请求失败: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @bp.route('/ask-stream', methods=['POST'])
        def ask_stream():
            data = request.get_json(force=True) or {}
            question = data.get('question', '').strip()
            if not question:
                return jsonify({'success': False, 'error': '问题不能为空'}), 400

            top_k = int(data.get('topK')) if data.get('topK') is not None else None
            strict_mode = data.get('strictMode', None)
            enable_async = data.get('enableAsyncVerification', None)

            def generate():
                # 优先使用 search_test_chunks（含 expanded_query / embedding_meta）
                try:
                    chunks, retrieval_resp = self.pipeline.search_test_chunks(question, top_k)
                    expanded_query = retrieval_resp.expanded_query
                except Exception:
                    chunks = self.pipeline.retrieve_chunks(question, top_k)
                    expanded_query = ''

                req = ReasoningRequest(
                    query=question,
                    chunks=chunks,
                    strict_mode=strict_mode,
                    enable_async_verification=enable_async,
                )

                loop = asyncio.new_event_loop()
                try:
                    async def _iter():
                        async for event in self.pipeline.stream_reason(req):
                            if isinstance(event, StreamEventToken):
                                yield f"data: {json.dumps({'answer': event.content})}\n\n"
                            elif isinstance(event, StreamEventCitation):
                                c = event.citation
                                yield f"data: {json.dumps({'citation': _citation_to_dict(c)})}\n\n"
                            elif isinstance(event, StreamEventDone):
                                resp = event.response
                                srcs = [_citation_to_dict(c) for c in (resp.citations or [])]
                                # README §5.1 提交格式 citations
                                citations_submit = [
                                    {'doc_path': c.doc_path, 'anchor': c.anchor}
                                    for c in (resp.citations or [])
                                ]
                                yield f"data: {json.dumps({'sources': srcs, 'citations': citations_submit, 'is_refusal': resp.no_evidence, 'expanded_query': expanded_query})}\n\n"
                            elif isinstance(event, StreamEventError):
                                yield f"data: {json.dumps({'error': event.message})}\n\n"

                    async def _collect():
                        parts = []
                        async for chunk in _iter():
                            parts.append(chunk)
                        return parts

                    parts = loop.run_until_complete(_collect())
                    for part in parts:
                        yield part
                finally:
                    loop.close()

                yield 'data: [DONE]\n\n'

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                },
            )

        @bp.route('/health', methods=['GET'])
        def health():
            return jsonify({
                'status': 'ok',
                'service': 'reasoning-layer',
                'version': '1.0.0',
                'language': 'python',
            })

        # GET /stats - 统计信息
        @bp.route('/stats', methods=['GET'])
        def stats():
            total   = self._session_stats.get('total', 0)
            refused = self._session_stats.get('refused', 0)
            refusal_rate = refused / max(total, 1)
            return jsonify({
                'score_threshold':              self.pipeline.rejection_guard.get_threshold(),
                'governance_enabled':           self.pipeline.enable_governance,
                'async_verification_enabled':   self.pipeline.enable_async_verification,
                'llm_configured':               self.pipeline._openai is not None,
                # ── 防全拒答保护统计（README §7.1 雷2）──────────────────
                'session_stats': {
                    'total':        total,
                    'refused':      refused,
                    'refusal_rate': round(refusal_rate, 4),
                    'warning':      refusal_rate > 0.6,
                },
            })

        return bp

    def register_websocket(self, app: Flask) -> None:
        """
        注册 WebSocket 端点
        路由：/ws/reasoning
        依赖：flask-sock（pip install flask-sock）

        ⚠️ 预留接口：若 flask-sock 未安装，WS 端点不可用
        """
        if not _FLASK_SOCK_AVAILABLE:
            logger.warning("⚠️ flask-sock 未安装，WebSocket 端点不可用。pip install flask-sock")
            return

        sock = Sock(app)

        @sock.route('/ws/reasoning')
        def ws_reasoning(ws):
            client_id = str(uuid.uuid4())[:8]
            self._ws_clients[client_id] = ws
            logger.info(f"🔌 WebSocket 客户端连接: {client_id}")

            ws.send(json.dumps({'type': 'connected', 'clientId': client_id}))

            try:
                while True:
                    raw = ws.receive()
                    if raw is None:
                        break
                    try:
                        data = json.loads(raw)
                        self._handle_ws_message(client_id, ws, data)
                    except Exception as e:
                        logger.error(f"❌ WebSocket 消息解析失败: {e}")
            finally:
                self._ws_clients.pop(client_id, None)
                logger.info(f"🔌 WebSocket 客户端断开: {client_id}")

    def _handle_ws_message(self, client_id: str, ws: Any, data: dict) -> None:
        """处理 WebSocket 消息"""
        if data.get('type') == 'ask':
            try:
                question = data.get('question', '')
                options = data.get('options', {})
                resp = self._ask_internal(
                    question,
                    options.get('topK', None),
                    options.get('strictMode', None),
                    options.get('enableAsyncVerification', None),
                )
                ws.send(json.dumps({
                    'type': 'response',
                    'requestId': data.get('requestId'),
                    **resp,
                }))
            except Exception as e:
                ws.send(json.dumps({
                    'type': 'error',
                    'requestId': data.get('requestId'),
                    'message': str(e),
                }))

    def _ask_internal(
        self,
        question: str,
        top_k: int = None,
        strict_mode: Optional[bool] = None,
        enable_async_verification: Optional[bool] = None,
    ) -> dict:
        """
        内部问答处理。

        返回对齐 README §5.1 的提交格式：
          answer / citations（doc_path + anchor）/ is_refusal / confidence
        """
        # 优先使用 search_test_chunks（含 expanded_query / embedding_meta）
        try:
            chunks, retrieval_resp = self.pipeline.search_test_chunks(question, top_k)
            expanded_query   = retrieval_resp.expanded_query
            max_reranker_score = retrieval_resp.max_reranker_score
        except Exception:
            # 降级到旧接口（retrieval.py 直接调用）
            chunks = self.pipeline.retrieve_chunks(question, top_k)
            expanded_query   = ''
            max_reranker_score = max((c.reranker_score or 0.0 for c in chunks), default=0.0)

        response = self.pipeline.reason(
            ReasoningRequest(
                query=question,
                chunks=chunks,
                strict_mode=strict_mode,
                enable_async_verification=enable_async_verification,
            )
        )

        # ── 构建 README §5.1 格式的 citations（doc_path + anchor）──────────
        citations_submit = [
            {
                'doc_path': c.doc_path,
                'anchor':   c.anchor,
            }
            for c in response.citations
        ]

        # ── 防全拒答保护（safety_check_refusal_rate）─────────────────────
        self._session_stats['total'] += 1
        if response.no_evidence:
            self._session_stats['refused'] += 1
        safety_check_refusal_rate(self._session_stats)  # 超过 60% 时输出告警日志

        return {
            # ── README §5.1 提交格式 ─────────────────────────────────────
            'answer':      response.answer,
            'citations':   citations_submit,          # doc_path + anchor
            'is_refusal':  response.no_evidence,      # 是否拒答（布尔）
            'confidence':  response.confidence,        # 置信度 0~1
            # ── 内部扩展字段（WebUI 调试用）──────────────────────────────
            'noEvidence':  response.no_evidence,
            'maxScore':    response.max_score,
            'contextTruncated': response.context_truncated,
            'rejectedReason':   response.rejected_reason,
            'query':       question,
            'debug_info': {
                'expanded_query':     expanded_query,
                'max_reranker_score': max_reranker_score,
                'refuse_reason':      response.rejected_reason,
            },
        }

    def push_update(self, client_id: str, data: dict) -> None:
        """推送更新到 WebSocket 客户端"""
        ws = self._ws_clients.get(client_id)
        if ws:
            try:
                ws.send(json.dumps(data))
            except Exception:
                pass

    def broadcast(self, event_type: str, data: dict) -> None:
        """广播消息到所有客户端"""
        message = json.dumps({'type': event_type, **data})
        dead = []
        for cid, ws in self._ws_clients.items():
            try:
                ws.send(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._ws_clients.pop(cid, None)

    def update_llm_config(self, config: LLMConfig) -> None:
        """更新 LLM 配置"""
        self.pipeline.update_llm_config(config)

    def set_score_threshold(self, threshold: float) -> None:
        """设置拒答阈值"""
        self.pipeline.set_score_threshold(threshold)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _citation_to_dict(c: CitationSource) -> dict:
    """
    将 CitationSource 转换为字典。

    同时输出：
    - README §5.1 提交字段：doc_path / anchor
    - WebUI 内部调试字段：anchorId / titlePath / score / filePath / snippet
    """
    return {
        # ── README §5.1 提交字段 ─────────────────────────────────────
        'doc_path':          c.doc_path,
        'anchor':            c.anchor,
        # ── WebUI 内部调试字段 ────────────────────────────────────────
        'id':                c.id,
        'anchorId':          c.anchor_id,
        'titlePath':         c.title_path,
        'score':             c.score,
        'verificationStatus': c.verification_status.value,
        'filePath':          c.file_path,
        'snippet':           c.snippet,
    }


def create_reasoning_web_ui(
    config: ReasoningPipelineConfig = None,
) -> ReasoningWebUI:
    """创建推理 WebUI 服务"""
    return ReasoningWebUI(config)
