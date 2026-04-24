"""
推理与引用层 - 接口定义
严格对齐方案.md: 3.4.1 ~ 3.4.4

提供两个核心接口：
1. WEB接口 - ask / ask-stream（给前端调用）
2. 检索层接口 - search_test（调用检索层）
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Literal, Dict, Any
from enum import Enum
import json


# ============================================================
# 检索层接口（推理层 → 检索层）
# ============================================================

@dataclass
class SearchParams:
    """检索参数 - 对应方案.md 3.4.1"""
    top_k: Optional[int] = None          # 传 null 时自适应决定
    rerank: bool = True                  # 是否启用 Reranker 精排
    filters: Optional[Dict[str, Any]] = None  # 过滤条件


@dataclass
class RetrievalRequest:
    """
    推理层 → 检索层 请求
    对应方案.md 3.4.1
    """
    query_intent: str                              # 经 Query Expansion 改写后的检索意图
    search_params: SearchParams = field(default_factory=SearchParams)
    context_requirement: Literal['paragraph_anchor_required'] = 'paragraph_anchor_required'

    def to_dict(self) -> dict:
        """转换为字典格式（用于 HTTP 请求）"""
        d = asdict(self)
        return d


@dataclass
class ChunkMetadata:
    """Chunk 元数据 - 对应方案.md 3.4.2 metadata"""
    file_path: str
    anchor_id: str                                 # 程序定位锚点: file_path#char_offset_start
    title_path: Optional[str]                      # UI 展示锚点: Section > Subsection
    last_modified: Optional[str] = None             # ISO8601 时间戳


@dataclass
class RetrievedChunkResponse:
    """
    检索结果中的单个 Chunk - 对应方案.md 3.4.2
    """
    chunk_id: str
    content: str
    score: float                                   # Reranker 精排后的语义相关度评分 0~1
    content_type: Literal['document', 'code', 'structured_data'] = 'document'
    is_truncated: bool = False
    metadata: ChunkMetadata = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = ChunkMetadata(file_path='', anchor_id='', title_path=None)


@dataclass
class RetrievalResponse:
    """
    检索层 → 推理层 响应
    对应方案.md 3.4.2
    """
    retrieved_chunks: List[RetrievedChunkResponse]
    retrieval_status: Literal['success', 'empty', 'error']
    max_reranker_score: float                      # 最高精排分，用于判断是否拒答
    expanded_query: str                            # Query Expansion 后的扩展词串


# ============================================================
# WEB 接口（推理层 ← WEB 层）
# ============================================================

@dataclass
class WebConfig:
    """WEB 配置 - 对应方案.md 3.4.3 config"""
    temperature: float = 0.0                      # 固定为 0.0（严谨模式）
    language: str = 'zh-CN'                        # 响应语言


@dataclass
class WebRequest:
    """
    WEB 层 → 推理层 请求
    对应方案.md 3.4.3
    """
    user_query: str                                # 用户原始问题
    stream: bool = True                            # 是否 SSE 流式传输
    session_id: Optional[str] = None                # 会话 ID
    config: WebConfig = field(default_factory=WebConfig)

    def to_dict(self) -> dict:
        d = {
            'user_query': self.user_query,
            'stream': self.stream,
            'session_id': self.session_id,
            'config': asdict(self.config),
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'WebRequest':
        config = WebConfig(**data.get('config', {}))
        return cls(
            user_query=data.get('user_query', data.get('question', '')),
            stream=data.get('stream', True),
            session_id=data.get('session_id'),
            config=config,
        )


# ============================================================
# 验证状态枚举
# ============================================================

class HallucinationCheckStatus(str, Enum):
    PASSED = 'passed'
    FAILED = 'failed'
    SKIPPED = 'skipped'                            # 拒答时跳过


class CitationValidationStatus(str, Enum):
    SYNC_VERIFIED = 'sync_verified'                # 引用 ID 存在于 chunk 列表
    INVALID_ID_REMOVED = 'invalid_id_removed'      # 已剔除无效引用
    SKIPPED = 'skipped'


# ============================================================
# 推理层响应（推理层 → WEB 层）
# ============================================================

@dataclass
class CitationLocation:
    """引用位置 - 对应方案.md 3.4.4 citations[].location"""
    file_path: str
    anchor_id: str                                 # 程序级精确跳转: file_path#char_offset
    title_path: Optional[str]                      # 可读路径


@dataclass
class Citation:
    """
    单条引用 - 对应方案.md 3.4.4 citations[]
    """
    citation_handle: str                           # 对应正文中的 [n] 标记
    source_id: str                                 # 源文件 ID
    snippet: str                                   # 引用原文高亮片段
    location: CitationLocation = None

    def __post_init__(self):
        if self.location is None:
            self.location = CitationLocation(
                file_path='',
                anchor_id='',
                title_path=None
            )

    def to_dict(self) -> dict:
        return {
            'citation_handle': self.citation_handle,
            'source_id': self.source_id,
            'snippet': self.snippet,
            'location': {
                'file_path': self.location.file_path,
                'anchor_id': self.location.anchor_id,
                'title_path': self.location.title_path,
            }
        }


@dataclass
class SourceLibrary:
    """源文件库 - 对应方案.md 3.4.4 source_library"""
    src_idx_001: Dict[str, str] = field(default_factory=dict)


@dataclass
class VerificationReport:
    """
    验证报告 - 对应方案.md 3.4.4 verification_report
    """
    hallucination_check: HallucinationCheckStatus = HallucinationCheckStatus.SKIPPED
    citation_validation: CitationValidationStatus = CitationValidationStatus.SKIPPED
    is_truncated_context: bool = False

    def to_dict(self) -> dict:
        return {
            'hallucination_check': self.hallucination_check.value,
            'citation_validation': self.citation_validation.value,
            'is_truncated_context': self.is_truncated_context,
        }


@dataclass
class DebugInfo:
    """
    调试信息 - 对应方案.md 3.4.4 debug_info
    """
    expanded_query: str = ''                        # Query Expansion 后的扩展词串
    max_reranker_score: float = 0.0                 # 检索阶段最高精排分
    refuse_reason: Optional[str] = None             # 拒答原因

    def to_dict(self) -> dict:
        return {
            'expanded_query': self.expanded_query,
            'max_reranker_score': self.max_reranker_score,
            'refuse_reason': self.refuse_reason,
        }


@dataclass
class WebResponse:
    """
    推理层 → WEB 层 响应
    对应方案.md 3.4.4
    """
    answer: str                                     # 包含 [n] 引用标记的生成文本
    answer_status: Literal['resolved', 'refused']  # 有解 / 拒答
    citations: List[Citation] = field(default_factory=list)
    source_library: Dict[str, Dict[str, str]] = field(default_factory=dict)
    verification_report: VerificationReport = None
    debug_info: DebugInfo = None

    def __post_init__(self):
        if self.verification_report is None:
            self.verification_report = VerificationReport()
        if self.debug_info is None:
            self.debug_info = DebugInfo()

    def to_dict(self) -> dict:
        """转换为 JSON 响应格式"""
        return {
            'answer': self.answer,
            'answer_status': self.answer_status,
            'citations': [c.to_dict() if isinstance(c, Citation) else c for c in self.citations],
            'source_library': self.source_library,
            'verification_report': self.verification_report.to_dict(),
            'debug_info': self.debug_info.to_dict(),
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def refused(cls, answer: str, debug_info: DebugInfo) -> 'WebResponse':
        """创建拒答响应 - 工厂方法"""
        return cls(
            answer=answer,
            answer_status='refused',
            citations=[],
            source_library={},
            verification_report=VerificationReport(
                hallucination_check=HallucinationCheckStatus.SKIPPED,
                citation_validation=CitationValidationStatus.SKIPPED,
            ),
            debug_info=debug_info,
        )

    @classmethod
    def resolved(
        cls,
        answer: str,
        citations: List[Citation],
        verification_report: VerificationReport,
        debug_info: DebugInfo,
    ) -> 'WebResponse':
        """创建正常响应 - 工厂方法"""
        # 构建 source_library（去重）
        source_lib: Dict[str, Dict[str, str]] = {}
        for c in citations:
            if isinstance(c, dict):
                loc = c.get('location', {})
                fp = loc.get('file_path', '')
            else:
                fp = c.location.file_path
            if fp and fp not in source_lib:
                source_lib[fp] = {
                    'title': fp.split('/')[-1],
                    'url': fp,
                }

        return cls(
            answer=answer,
            answer_status='resolved',
            citations=citations,
            source_library=source_lib,
            verification_report=verification_report,
            debug_info=debug_info,
        )


# ============================================================
# 流式事件类型
# ============================================================

class StreamEventType(str, Enum):
    TOKEN = 'token'
    CITATION = 'citation'
    VERIFICATION = 'verification'
    DONE = 'done'
    ERROR = 'error'


@dataclass
class StreamTokenEvent:
    """流式 Token 事件"""
    type: Literal['token'] = 'token'
    content: str = ''


@dataclass
class StreamCitationEvent:
    """流式引用事件"""
    type: Literal['citation'] = 'citation'
    citation: Optional[Dict] = None


@dataclass
class StreamDoneEvent:
    """流式完成事件"""
    type: Literal['done'] = 'done'
    response: Optional[WebResponse] = None

    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': 'done', **self.response.to_dict()}, ensure_ascii=False)}\n\n"


@dataclass
class StreamErrorEvent:
    """流式错误事件"""
    type: Literal['error'] = 'error'
    message: str = ''


# ============================================================
# 接口说明文档（供开发者参考）
# ============================================================

INTERFACE_DOC = """
================================================================================
接口说明 - 推理与引用层
================================================================================

┌─────────────────────────────────────────────────────────────────────────────┐
│ 接口 1: WEB 接口（给前端调用）                                               │
└─────────────────────────────────────────────────────────────────────────────┘

路由: POST /api/reasoning/ask
路由: POST /api/reasoning/ask-stream

【请求格式 - WebRequest】
{
  "user_query": "安装时环境变量怎么配？",    // [必填] 用户原始问题
  "stream": true,                          // [可选] 是否流式，默认 true
  "session_id": "sess_001",                // [可选] 会话 ID
  "config": {
    "temperature": 0.0,                   // [固定] 0.0 严谨模式
    "language": "zh-CN"                     // [可选] 响应语言
  }
}

【响应格式 - WebResponse】
{
  "answer": "根据安装手册，您需要编辑 .bashrc 文件来配置路径 [1]。",
  "answer_status": "resolved",            // resolved | refused
  "citations": [
    {
      "citation_handle": "[1]",
      "source_id": "src_001",
      "snippet": "To set up the path, edit your .bashrc file...",
      "location": {
        "file_path": "/docs/v2/install.md",
        "anchor_id": "/docs/v2/install.md#4821",
        "title_path": "Install Guide > Step 2"
      }
    }
  ],
  "source_library": {
    "/docs/v2/install.md": {
      "title": "install.md",
      "url": "/docs/v2/install.md"
    }
  },
  "verification_report": {
    "hallucination_check": "passed",
    "citation_validation": "sync_verified",
    "is_truncated_context": false
  },
  "debug_info": {
    "expanded_query": "环境变量配置 environment variable...",
    "max_reranker_score": 0.92,
    "refuse_reason": null
  }
}

【拒答响应 - answer_status = "refused"】
{
  "answer": "根据现有文档无法回答此问题。",
  "answer_status": "refused",
  "citations": [],
  "source_library": {},
  "verification_report": {
    "hallucination_check": "skipped",
    "citation_validation": "skipped",
    "is_truncated_context": false
  },
  "debug_info": {
    "expanded_query": "GPU 驱动版本 driver compatibility",
    "max_reranker_score": 0.31,
    "refuse_reason": "score_below_threshold"
  }
}


┌─────────────────────────────────────────────────────────────────────────────┐
│ 接口 2: 检索层接口（调用检索层 search_test）                                  │
└─────────────────────────────────────────────────────────────────────────────┘

方法名: search_test(query: str, top_k: Optional[int] = None) -> RetrievalResponse

【调用示例】
```python
from interfaces import RetrievalRequest, search_test

# 简单调用
response = search_test("如何配置环境变量")

# 指定 top_k
response = search_test("OAuth2 刷新 Token", top_k=8)
```

【检索请求 - RetrievalRequest】
{
  "query_intent": "环境变量配置 environment variable setup",  // Query Expansion 后
  "search_params": {
    "top_k": null,                       // null=自适应，综合型=8，事实型=3
    "rerank": true,                      // 是否启用精排
    "filters": {
      "min_timestamp": "2026-04-20T10:00:00Z",
      "doc_types": ["installation_guide", "api_ref"]
    }
  },
  "context_requirement": "paragraph_anchor_required"
}

【检索响应 - RetrievalResponse】
{
  "retrieved_chunks": [
    {
      "chunk_id": "ch_9823",
      "content": "To set up the path, edit your .bashrc file...",
      "score": 0.92,
      "content_type": "document",
      "is_truncated": false,
      "metadata": {
        "file_path": "/docs/v2/install.md",
        "anchor_id": "/docs/v2/install.md#4821",
        "title_path": "Install Guide > Step 2 > Environment Variables",
        "last_modified": "2026-04-24T14:50:00Z"
      }
    }
  ],
  "retrieval_status": "success",         // success | empty | error
  "max_reranker_score": 0.92,
  "expanded_query": "环境变量配置 environment variable setup install..."
}


┌─────────────────────────────────────────────────────────────────────────────┐
│ 内部调用链路                                                                │
└─────────────────────────────────────────────────────────────────────────────┘

Frontend (Next.js)
  └─ POST /api/reasoning/ask-stream
       └─ ReasoningWebUI.ask_stream()
            ├─ pipeline.retrieve_chunks()  ← 调用 RetrievalRequest / search_test
            │    └─ retrieval.py pipeline()
            └─ pipeline.stream_reason()
                 ├─ rejection_guard.evaluate()
                 ├─ governor.govern()
                 ├─ injector.inject()
                 ├─ _stream_generate()
                 └─ verifier.sync_verify()

================================================================================
"""


# ============================================================
# search_test 实现 - 调用检索层
# ============================================================

def _get_adaptive_topk(query: str) -> int:
    """
    根据查询类型自适应决定 top_k
    对应方案.md 2.3 自适应 TopK 策略

    规则：
    - 综合型问题（列举、比较、所有...）→ 8
    - 事实型问题（是什么、多少、什么时候...）→ 3
    - 默认 → 5
    """
    BROAD_KEYWORDS = ["所有", "列举", "比较", "对比", "区别", "有哪些", "分别", "列表"]
    SIMPLE_KEYWORDS = ["是什么", "是多少", "什么时候", "谁是", "版本号", "如何", "怎么", "怎样"]

    if any(kw in query for kw in BROAD_KEYWORDS):
        return 8
    if any(kw in query for kw in SIMPLE_KEYWORDS):
        return 3
    return 5


def _expand_query(query: str) -> str:
    """
    Query Expansion - 轻量级查询扩展
    对应方案.md 2.1 查询扩展

    实现策略：基于规则的同义词扩展
    后续可升级为 LLM 生成同义表达
    """
    # 常见技术术语映射
    TERM_MAPPINGS = {
        '安装': ['install', '部署', 'setup'],
        '配置': ['config', '配置', 'setting', '设置'],
        '环境变量': ['env', 'environment variable', '环境变量配置'],
        'API': ['api', '接口', 'REST', 'endpoint'],
        '认证': ['auth', 'authentication', '授权', 'OAuth', 'JWT'],
        '错误': ['error', '异常', 'exception', '失败'],
        '优化': ['optimize', '性能', '优化', 'performance'],
        '调试': ['debug', '调试', '排查', 'troubleshoot'],
    }

    expanded = [query]
    for term, synonyms in TERM_MAPPINGS.items():
        if term in query:
            expanded.extend(synonyms)

    return ' '.join(expanded)


def _parse_document_chunk(doc) -> RetrievedChunkResponse:
    """
    将 retrieval.py 返回的 Document 对象转换为 RetrievedChunkResponse
    对应方案.md 3.4.2
    """
    metadata = doc.metadata or {}

    # 解析 anchor_id（格式：file_path#char_offset_start）
    file_path = metadata.get('file_path', metadata.get('source', ''))
    char_offset = metadata.get('char_offset_start', metadata.get('offset', 0))
    anchor_id = f"{file_path}#{char_offset}" if file_path else ''

    # 解析 title_path
    title_path = metadata.get('title_path', None)

    # 解析 content_type
    content_type = metadata.get('content_type', 'document')
    if content_type not in ('document', 'code', 'structured_data'):
        content_type = 'document'

    # 解析 is_truncated
    is_truncated = metadata.get('is_truncated', False)

    # 解析 score
    score = metadata.get('score', metadata.get('reranker_score', 0.0))

    # 解析 last_modified
    last_modified = metadata.get('last_modified', metadata.get('updated_at', None))

    # 解析 chunk_id
    chunk_id = metadata.get('chunk_id', metadata.get('id', hash(doc.page_content)))

    return RetrievedChunkResponse(
        chunk_id=str(chunk_id),
        content=doc.page_content,
        score=float(score),
        content_type=content_type,
        is_truncated=bool(is_truncated),
        metadata=ChunkMetadata(
            file_path=file_path,
            anchor_id=anchor_id,
            title_path=title_path,
            last_modified=last_modified,
        )
    )


def search_test(
    query: str,
    top_k: Optional[int] = None,
    rerank: bool = True,
    filters: Optional[Dict[str, Any]] = None,
) -> RetrievalResponse:
    """
    检索层接口 - search_test

    对应方案.md 3.4.1 和 3.4.2

    功能：
    1. Query Expansion - 查询扩展
    2. 调用 retrieval.py 的 pipeline 进行混合检索
    3. 返回规范化后的检索结果

    参数：
        query: 用户查询（原始问题）
        top_k: 期望召回数量，传 None 时自适应决定
        rerank: 是否启用 Reranker 精排（默认 True）
        filters: 过滤条件（预留，暂不支持）

    返回：
        RetrievalResponse - 检索响应

    调用示例：
        from interfaces import search_test

        # 简单调用
        response = search_test("如何配置环境变量")

        # 指定 top_k
        response = search_test("OAuth2 刷新 Token", top_k=8)

        # 遍历结果
        for chunk in response.retrieved_chunks:
            print(f"[{chunk.chunk_id}] {chunk.content[:100]}... (score={chunk.score})")
    """
    # 1. Query Expansion
    expanded_query = _expand_query(query)
    logger.info(f"[search_test] 原始查询: {query}")
    logger.info(f"[search_test] 扩展查询: {expanded_query}")

    # 2. 自适应 TopK
    if top_k is None:
        top_k = _get_adaptive_topk(query)
        logger.info(f"[search_test] 自适应 top_k: {top_k}")

    # 3. 调用 retrieval.py pipeline
    try:
        # 动态导入 retrieval.py（延迟加载，避免循环依赖）
        import sys
        import os
        _RETRIEVAL_DIR = os.path.join(os.path.dirname(__file__), '..', 'LLM')
        if _RETRIEVAL_DIR not in sys.path:
            sys.path.insert(0, os.path.abspath(_RETRIEVAL_DIR))

        from retrieval import pipeline as retrieval_pipeline, adaptive_topk_simple

        # 调用检索管道
        docs = retrieval_pipeline(expanded_query)
        logger.info(f"[search_test] 检索召回数量: {len(docs)}")

    except ImportError as e:
        logger.error(f"[search_test] retrieval.py 导入失败: {e}")
        return RetrievalResponse(
            retrieved_chunks=[],
            retrieval_status='error',
            max_reranker_score=0.0,
            expanded_query=expanded_query,
        )
    except Exception as e:
        logger.error(f"[search_test] 检索失败: {e}")
        return RetrievalResponse(
            retrieved_chunks=[],
            retrieval_status='error',
            max_reranker_score=0.0,
            expanded_query=expanded_query,
        )

    # 4. 转换结果
    if not docs:
        logger.warning(f"[search_test] 无检索结果")
        return RetrievalResponse(
            retrieved_chunks=[],
            retrieval_status='empty',
            max_reranker_score=0.0,
            expanded_query=expanded_query,
        )

    # 转换 Document 为 RetrievedChunkResponse
    chunks = []
    max_score = 0.0

    for doc in docs:
        chunk = _parse_document_chunk(doc)
        chunks.append(chunk)
        if chunk.score > max_score:
            max_score = chunk.score

    # 限制返回数量
    chunks = chunks[:top_k]

    logger.info(f"[search_test] 返回 {len(chunks)} 个结果, max_score={max_score:.4f}")

    return RetrievalResponse(
        retrieved_chunks=chunks,
        retrieval_status='success',
        max_reranker_score=max_score,
        expanded_query=expanded_query,
    )


def search_test_async(
    query: str,
    top_k: Optional[int] = None,
    rerank: bool = True,
    filters: Optional[Dict[str, Any]] = None,
):
    """
    异步版本的 search_test（预留接口）

    对应方案.md 3.4.1（异步变体）
    适用于需要异步处理的场景
    """
    import asyncio
    return asyncio.coroutine(lambda: search_test(query, top_k, rerank, filters))()

