# -*- coding: utf-8 -*-
"""
问答 API 路由
提供完整的问答管道接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.qa_pipeline import get_qa_pipeline, QAResult


router = APIRouter(prefix="/api/qa", tags=["问答管道"])


class QARequest(BaseModel):
    """问答请求"""
    question: str = Field(..., description="用户问题", min_length=1)
    session_id: str = Field(..., description="会话 ID", min_length=1)
    timeout: int = Field(60, description="检索超时时间（秒）", ge=10, le=120)


class QAResponse(BaseModel):
    """问答响应"""
    success: bool = Field(..., description="是否成功")
    question: str = Field(..., description="原始问题")
    answer: str = Field("", description="回答内容")
    sources: List[str] = Field(default_factory=list, description="信息来源")
    error: Optional[str] = Field(None, description="错误信息")
    
    # 处理过程信息
    has_anaphora: bool = Field(False, description="是否包含指代")
    anaphora_list: List[str] = Field(default_factory=list, description="检测到的指代词")
    context_loaded: bool = Field(False, description="是否加载上下文")
    question_rewritten: bool = Field(False, description="是否改写问题")
    rewritten_question: str = Field("", description="改写后的问题")
    completeness_passed: bool = Field(False, description="完整性检查是否通过")
    retrieval_success: bool = Field(False, description="检索是否成功")
    execution_time: float = Field(0.0, description="执行时间（秒）")


class QAStreamEvent(BaseModel):
    """流式问答事件"""
    event: str = Field(..., description="事件类型: start/anaphora/context/rewrite/completeness/answer/sources/error/end")
    data: Dict[str, Any] = Field(default_factory=dict, description="事件数据")


def _convert_result_to_response(result: QAResult) -> QAResponse:
    """将 QAResult 转换为 QAResponse"""
    return QAResponse(
        success=result.success,
        question=result.question,
        answer=result.answer,
        sources=result.sources,
        error=result.error,
        has_anaphora=result.has_anaphora,
        anaphora_list=result.anaphora_list,
        context_loaded=result.context_loaded,
        question_rewritten=result.question_rewritten,
        rewritten_question=result.rewritten_question,
        completeness_passed=result.completeness_passed,
        retrieval_success=result.retrieval_success,
        execution_time=result.execution_time
    )


@router.post("", response_model=QAResponse, summary="问答接口")
async def qa_endpoint(request: QARequest):
    """
    问答接口 - 完整问答管道
    
    流程：
    1. 指代检测 (RexUniNLU)
    2. 上下文加载 (Context Memory)
    3. 指代替换 (RexUniNLU)
    4. 查询改写 (SlimPLM)
    5. 完整性检查 (TurnSense)
    6. 检索调用 (Retrieval Layer)
    
    **示例请求**：
    ```json
    {
        "question": "它怎么开通？",
        "session_id": "session_abc123",
        "timeout": 60
    }
    ```
    
    **示例响应**：
    ```json
    {
        "success": true,
        "question": "它怎么开通？",
        "answer": "根据知识库内容...",
        "sources": ["第三方系统.md"],
        "has_anaphora": true,
        "context_loaded": true,
        "question_rewritten": true,
        "rewritten_question": "彩铃服务怎么开通？",
        "completeness_passed": true,
        "retrieval_success": true,
        "execution_time": 3.5
    }
    ```
    """
    try:
        pipeline = get_qa_pipeline()
        result = await pipeline.process(request.question, request.session_id)
        return _convert_result_to_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"问答处理失败: {str(e)}")


@router.post("/ask", response_model=QAResponse, summary="问答接口（别名）")
async def qa_ask_endpoint(request: QARequest):
    """问答接口别名 /api/qa/ask"""
    return await qa_endpoint(request)


@router.get("/health", summary="问答管道健康检查")
async def qa_health_check():
    """
    检查问答管道各组件状态
    """
    try:
        pipeline = get_qa_pipeline()
        
        # 检查各组件状态
        components = {
            "rex_uninlu": pipeline.rex_uninlu.is_loaded,
            "slim_plm": pipeline.slim_plm.is_loaded,
            "turn_sense": pipeline.turn_sense.is_loaded,
        }
        
        all_ready = all(components.values())
        
        return {
            "status": "ready" if all_ready else "partial",
            "components": components,
            "message": "所有模型已加载" if all_ready else "部分模型未加载（将使用规则模式）"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
