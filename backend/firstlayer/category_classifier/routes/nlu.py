# -*- coding: utf-8 -*-
"""
NLU 处理 API 路由 - 集成完整 NLU 流程
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import sys
import os
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nlu.pipeline import get_nlu_pipeline
from classifier import get_classifier


router = APIRouter(prefix="/api/nlu", tags=["NLU 处理"])


class NLURequest(BaseModel):
    """NLU 处理请求"""
    question: str
    session_id: Optional[str] = None


class NLUResponse(BaseModel):
    """NLU 处理响应"""
    success: bool
    question: str
    answer: Optional[str] = None
    sources: Optional[List[str]] = None
    error: Optional[str] = None
    processing_steps: Optional[Dict] = None
    category: Optional[str] = None
    confidence: Optional[float] = None


@router.post("/process", response_model=NLUResponse, summary="完整 NLU 处理")
async def process_nlu(request: NLURequest):
    """
    完整 NLU 处理流程
    
    处理流程：
    1. 指代判断 - 使用 RexUniNLU 模型检测指代词
    2. 上下文加载 - 如果有指代词，从上下文记忆服务加载历史会话
    3. 指代替换 - 使用 RexUniNLU 模型替换指代词
    4. 查询改写 - 使用 SlimPLM-Query-Rewriting 模型改写查询
    5. 完整性检查 - 两层判断：规则过滤 + TurnSense 模型
    6. 检索 - 调用检索层接口
    7. 记录上下文 - 将问答记录到上下文记忆服务
    
    **示例**：
    ```json
    {
        "question": "如何申请年假？",
        "session_id": "session_abc123"
    }
    ```
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [process_nlu] 收到请求 - question: {request.question[:50]}..., session_id: {request.session_id}")
    
    try:
        # 1. 先进行问题分类（保留原有功能）
        classifier = get_classifier()
        classify_result = classifier.classify(request.question)
        
        # 2. 调用 NLU 流水线
        pipeline = get_nlu_pipeline()
        nlu_result = await pipeline.process(
            question=request.question,
            session_id=request.session_id
        )
        
        logger.info(f"✅ [process_nlu] 处理完成 - success: {nlu_result.get('success')}")
        
        return NLUResponse(
            success=nlu_result.get("success", False),
            question=request.question,
            answer=nlu_result.get("answer"),
            sources=nlu_result.get("sources", []),
            error=nlu_result.get("error"),
            processing_steps=nlu_result.get("processing_steps", {}),
            category=classify_result.get("category"),
            confidence=classify_result.get("confidence")
        )
        
    except Exception as e:
        logger.error(f"❌ [process_nlu] 处理失败 - error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"NLU 处理失败：{str(e)}")


@router.post("/classify-only", response_model=NLUResponse, summary="仅分类（不检索）")
async def classify_only(request: NLURequest):
    """
    仅进行问题分类，不调用检索层
    
    用于测试分类效果或作为独立分类服务使用
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [classify_only] 收到请求 - question: {request.question[:50]}...")
    
    try:
        classifier = get_classifier()
        result = classifier.classify(request.question)
        
        logger.info(f"✅ [classify_only] 分类完成 - category: {result.get('category')}")
        
        return NLUResponse(
            success=result.get("success", False),
            question=request.question,
            category=result.get("category"),
            confidence=result.get("confidence"),
            description=result.get("description")
        )
        
    except Exception as e:
        logger.error(f"❌ [classify_only] 分类失败 - error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"分类失败：{str(e)}")


@router.get("/check-completeness", summary="检查问题完整性")
async def check_completeness(question: str):
    """
    检查问题的完整性
    
    返回：
    {
        "is_complete": bool,
        "message": str,
        "rule_check": bool,
        "model_check": bool
    }
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [check_completeness] 收到请求 - question: {question[:50]}...")
    
    try:
        pipeline = get_nlu_pipeline()
        is_complete, message = await pipeline.check_completeness(question)
        
        return {
            "success": True,
            "is_complete": is_complete,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"❌ [check_completeness] 检查失败 - error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"完整性检查失败：{str(e)}")


@router.post("/rewrite-query", summary="查询改写")
async def rewrite_query(question: str):
    """
    查询改写
    
    使用 SlimPLM-Query-Rewriting 模型对问题进行改写
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [rewrite_query] 收到请求 - question: {question[:50]}...")
    
    try:
        pipeline = get_nlu_pipeline()
        rewritten = await pipeline.rewrite_query(question)
        
        return {
            "success": True,
            "original": question,
            "rewritten": rewritten
        }
        
    except Exception as e:
        logger.error(f"❌ [rewrite_query] 改写失败 - error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询改写失败：{str(e)}")


@router.post("/resolve-pronoun", summary="指代消解")
async def resolve_pronoun(request: NLURequest):
    """
    指代消解
    
    使用 RexUniNLU 模型检测并替换指代词
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [resolve_pronoun] 收到请求 - question: {request.question[:50]}..., session_id: {request.session_id}")
    
    try:
        pipeline = get_nlu_pipeline()
        
        # 检查是否有指代词
        has_pron = pipeline.has_pronoun(request.question)
        
        if not has_pron:
            return {
                "success": True,
                "has_pronoun": False,
                "original": request.question,
                "resolved": request.question,
                "message": "未检测到指代词"
            }
        
        # 如果有指代词且提供了 session_id，加载历史上下文
        if request.session_id:
            history = await pipeline.get_context_history(request.session_id, turns=2)
            if history:
                resolved, replaced = pipeline.resolve_pronoun(request.question, history)
                return {
                    "success": True,
                    "has_pronoun": True,
                    "original": request.question,
                    "resolved": resolved,
                    "replaced": replaced,
                    "history_count": len(history)
                }
        
        return {
            "success": True,
            "has_pronoun": True,
            "original": request.question,
            "resolved": request.question,
            "message": "未找到可替换的指代对象"
        }
        
    except Exception as e:
        logger.error(f"❌ [resolve_pronoun] 消解失败 - error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"指代消解失败：{str(e)}")


@router.get("/test-retrieval", summary="测试检索层连接")
async def test_retrieval(question: str = "测试"):
    """
    测试检索层连接
    
    用于验证检索服务是否可用
    """
    logger = logging.getLogger("nlu_api")
    logger.info(f"📥 [test_retrieval] 测试检索层")
    
    try:
        pipeline = get_nlu_pipeline()
        result = await pipeline.query_retrieval(question)
        
        return {
            "success": True,
            "retrieval_success": result.get("success"),
            "answer": result.get("answer"),
            "error": result.get("error")
        }
        
    except Exception as e:
        logger.error(f"❌ [test_retrieval] 测试失败 - error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }
