"""
问题分类 API 路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from classifier import get_classifier


router = APIRouter(prefix="/api/classify", tags=["问题分类"])


class ClassifyRequest(BaseModel):
    """分类请求"""
    question: str


class ClassifyResponse(BaseModel):
    """分类响应"""
    success: bool
    question: str
    category: Optional[str] = None
    confidence: Optional[float] = None
    description: Optional[str] = None
    error: Optional[str] = None


@router.post("", response_model=ClassifyResponse, summary="问题分类")
async def classify_question(request: ClassifyRequest):
    """
    对问题进行分类
    
    支持五大类：
    - FACT: 事实型问题
    - PROC: 过程型问题
    - EXPL: 解释型问题
    - COMP: 比较型问题
    - META: 元认知型问题
    - UNKNOWN: 未知类型
    
    **示例**：
    ```json
    {
        "question": "如何申请年假？"
    }
    ```
    """
    try:
        classifier = get_classifier()
        result = classifier.classify(request.question)
        
        return ClassifyResponse(
            success=result.get("success", False),
            question=request.question,
            category=result.get("category"),
            confidence=result.get("confidence"),
            description=result.get("description"),
            error=result.get("error") if not result.get("success") else None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分类失败：{str(e)}")


@router.get("/types", summary="获取所有分类类型")
async def get_question_types():
    """
    获取所有支持的问题分类类型及其描述
    """
    classifier = get_classifier()
    return {
        "success": True,
        "types": classifier.label_descriptions
    }


@router.post("/batch", response_model=List[ClassifyResponse], summary="批量分类")
async def batch_classify(requests: List[ClassifyRequest]):
    """
    批量分类多个问题
    
    **示例**：
    ```json
    [
        {"question": "什么是人工智能？"},
        {"question": "如何安装 Python？"},
        {"question": "为什么天空是蓝色的？"}
    ]
    ```
    """
    results = []
    classifier = get_classifier()
    
    for req in requests:
        result = classifier.classify(req.question)
        results.append(ClassifyResponse(
            success=result["success"],
            question=result["question"],
            category=result.get("category"),
            confidence=result.get("confidence"),
            description=result.get("description"),
            error=result.get("error")
        ))
    
    return results
