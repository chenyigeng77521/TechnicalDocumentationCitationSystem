"""
问题过滤 API 路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from classifier import get_classifier
from config import Config


router = APIRouter(prefix="/api/filter", tags=["问题过滤"])


class FilterRequest(BaseModel):
    """过滤请求"""
    question: str
    conversation_history: Optional[List[Dict]] = None  # 对话历史，用于上下文记忆层


class FilterResponse(BaseModel):
    """过滤响应"""
    success: bool
    question: str
    category: Optional[str] = None
    confidence: Optional[float] = None
    description: Optional[str] = None
    reason: Optional[str] = None
    need_context_check: Optional[bool] = None  # 是否需要上下文记忆层二次过滤
    final_category: Optional[str] = None  # 上下文记忆层过滤后的最终分类
    filter_message: Optional[str] = None


@router.post("", response_model=FilterResponse, summary="问题过滤")
async def filter_question(request: FilterRequest):
    """
    过滤用户问题，识别无效问题和实时类问题
    
    支持分类：
    - VALID: 有效问题 - 可以继续处理
    - INVALID: 无效问题 - 无法回答的问题
    - REALTIME: 实时类问题 - 需要实时数据的问题
    - OFFTOPIC: 偏离主题 - 恶意/敏感/广告等问题
    - CHAT: 友好闲聊 - 日常问候，可适度回应
    - SELF_INRO: 自我介绍 - 询问 AI 助手身份的问题
    
    多级过滤策略：
    1. 规则检查（快速过滤）
    2. 关键词匹配（闲聊、实时类等）
    3. ML 模型分类（RoBERTa）
    4. 上下文记忆层二次过滤（边界情况）
    
    **示例**：
    ```json
    {
        "question": "今天的天气怎么样？",
        "conversation_history": [
            {"role": "user", "text": "你好"},
            {"role": "assistant", "text": "您好！有什么可以帮助您的吗？"}
        ]
    }
    ```
    """
    try:
        classifier = get_classifier()
        result = classifier.classify(
            request.question,
            conversation_history=request.conversation_history
        )
        
        # 如果不是有效问题，生成过滤提示
        filter_message = None
        category = result.get("category")
        final_category = result.get("final_category")
        
        # 优先使用上下文记忆层的最终分类
        if final_category and final_category != "VALID":
            filter_message = classifier.get_filter_response(final_category)
        elif category != "VALID":
            filter_message = classifier.get_filter_response(category)
        
        return FilterResponse(
            success=result.get("success", False),
            question=request.question,
            category=category,
            confidence=result.get("confidence"),
            description=result.get("description"),
            reason=result.get("reason"),
            need_context_check=result.get("need_context_check", False),
            final_category=final_category,
            filter_message=filter_message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"过滤失败：{str(e)}")


@router.post("/with-context", response_model=FilterResponse, summary="上下文记忆层过滤")
async def filter_with_context(request: FilterRequest):
    """
    使用上下文记忆层进行二次过滤
    
    当 ML 模型置信度较低时，调用此接口进行上下文感知的二次判断。
    上下文记忆层会分析对话历史，判断当前问题是否需要结合上下文理解。
    
    **注意**：此接口目前为预留接口，待上下文记忆层服务开发完成后启用。
    
    **示例**：
    ```json
    {
        "question": "它多少钱？",
        "conversation_history": [
            {"role": "user", "text": "我想了解一下 iPhone 15"},
            {"role": "assistant", "text": "iPhone 15 是我们的最新款手机..."}
        ]
    }
    ```
    """
    try:
        if not getattr(Config, 'CONTEXT_MEMORY_ENABLED', False):
            raise HTTPException(
                status_code=503,
                detail="上下文记忆层服务尚未启用，请先配置 CONTEXT_MEMORY_URL 和 CONTEXT_MEMORY_ENABLED"
            )
        
        classifier = get_classifier()
        result = classifier.classify(
            request.question,
            conversation_history=request.conversation_history
        )
        
        # 生成响应
        filter_message = None
        final_category = result.get("final_category")
        if final_category and final_category != "VALID":
            filter_message = classifier.get_filter_response(final_category)
        
        return FilterResponse(
            success=result.get("success", False),
            question=request.question,
            category=result.get("category"),
            confidence=result.get("confidence"),
            description=result.get("description"),
            reason="上下文记忆层二次过滤",
            need_context_check=False,
            final_category=final_category,
            filter_message=filter_message
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上下文过滤失败：{str(e)}")


@router.get("/types", summary="获取所有过滤类型")
async def get_filter_types():
    """
    获取所有支持的问题过滤类型及其描述
    """
    classifier = get_classifier()
    return {
        "success": True,
        "types": classifier.label_descriptions
    }


@router.post("/batch", response_model=List[FilterResponse], summary="批量过滤")
async def batch_filter(requests: List[FilterRequest]):
    """
    批量过滤多个问题
    
    **示例**：
    ```json
    [
        {"question": "今天的天气怎么样？"},
        {"question": "如何申请年假？"},
        {"question": ""}
    ]
    ```
    """
    results = []
    classifier = get_classifier()
    
    for req in requests:
        result = classifier.classify(
            req.question,
            conversation_history=req.conversation_history
        )
        filter_message = None
        category = result.get("category")
        if category != "VALID":
            filter_message = classifier.get_filter_response(category)
        
        results.append(FilterResponse(
            success=result["success"],
            question=result["question"],
            category=category,
            confidence=result.get("confidence"),
            description=result.get("description"),
            reason=result.get("reason"),
            need_context_check=result.get("need_context_check", False),
            final_category=result.get("final_category"),
            filter_message=filter_message
        ))
    
    return results


@router.get("/keywords", summary="获取实时类关键词列表")
async def get_realtime_keywords():
    """
    获取用于识别实时类问题的关键词列表
    """
    return {
        "success": True,
        "keywords": Config.REALTIME_KEYWORDS,
        "count": len(Config.REALTIME_KEYWORDS)
    }
