# -*- coding: utf-8 -*-
"""
QA Pipeline - 问答流程编排器
整合指代检测、上下文加载、查询改写、完整性检查、检索调用
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from models.rex_uninlu import get_rex_uninlu
from models.slim_plm import get_slim_plm
from models.turn_sense import get_turn_sense
from services.context_client import get_context_client
from services.retrieval_client import get_retrieval_client


@dataclass
class QAResult:
    """问答结果数据类"""
    success: bool
    question: str
    answer: str = ""
    sources: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    # 处理过程信息（用于调试）
    has_anaphora: bool = False
    anaphora_list: List[str] = field(default_factory=list)
    context_loaded: bool = False
    context_formatted: str = ""
    question_rewritten: bool = False
    rewritten_question: str = ""
    completeness_checked: bool = False
    completeness_passed: bool = False
    retrieval_success: bool = False
    execution_time: float = 0.0


class QAPipeline:
    """问答流程编排器"""

    def __init__(self):
        self.rex_uninlu = get_rex_uninlu()
        self.slim_plm = get_slim_plm()
        self.turn_sense = get_turn_sense()
        self.context_client = get_context_client()
        self.retrieval_client = get_retrieval_client()

    async def process(self, question: str, session_id: str) -> QAResult:
        """
        处理用户问题，执行完整问答流程
        
        流程：
        1. 指代检测 (RexUniNLU)
        2. 上下文加载 (Context Memory)
        3. 指代替换 (RexUniNLU)
        4. 查询改写 (SlimPLM)
        5. 完整性检查 (TurnSense)
        6. 检索调用 (Retrieval Layer)
        
        Args:
            question: 用户问题
            session_id: session ID
            
        Returns:
            QAResult: 问答结果
        """
        result = QAResult(success=False, question=question)
        
        # ========== Step 1: 指代检测 ==========
        has_anaphora, anaphora_list = self.rex_uninlu.detect_anaphora(question)
        result.has_anaphora = has_anaphora
        result.anaphora_list = anaphora_list
        
        print(f"🔍 指代检测: {'有指代' if has_anaphora else '无指代'}")
        if has_anaphora:
            print(f"   检测到的指代词: {anaphora_list}")
        
        # ========== Step 2: 上下文加载 ==========
        context = ""
        if has_anaphora:
            conversations = await self.context_client.get_latest_conversations(session_id, count=2)
            if conversations:
                context = self.context_client.format_context(conversations)
                result.context_loaded = True
                result.context_formatted = context
                print(f"📚 上下文加载: 成功加载 {len(conversations)} 条消息")
            else:
                print(f"⚠️ 上下文加载: 无历史对话或 session 不存在")
        
        # ========== Step 3: 指代替换 ==========
        if has_anaphora and context:
            replaced_question = self.rex_uninlu.replace_anaphora(question, context)
            if replaced_question != question:
                question = replaced_question
                result.question_rewritten = True
                result.rewritten_question = question
                print(f"🔄 指代替换: {result.question} -> {question}")
        
        # ========== Step 4: 查询改写 ==========
        if context:
            rewritten = self.slim_plm.rewrite_query(question, context)
            if rewritten != question:
                question = rewritten
                result.question_rewritten = True
                result.rewritten_question = question
                print(f"✏️ 查询改写: {result.question} -> {question}")
        
        # ========== Step 5: 完整性检查 ==========
        result.completeness_checked = True
        is_complete, reason = self.turn_sense.check_completeness(question)
        result.completeness_passed = is_complete
        
        if not is_complete:
            print(f"❌ 完整性检查未通过: {reason}")
            result.error = f"问题不完整: {reason}"
            return result
        
        print(f"✅ 完整性检查通过")
        
        # ========== Step 6: 检索调用 ==========
        retrieval_result = await self.retrieval_client.query(question)
        result.retrieval_success = retrieval_result.get("success", False)
        
        if retrieval_result.get("success"):
            result.success = True
            result.answer = retrieval_result.get("answer", "")
            result.sources = retrieval_result.get("sources", [])
            result.execution_time = retrieval_result.get("execution_time", 0)
            print(f"✅ 检索成功，耗时: {result.execution_time:.2f}s")
        else:
            result.error = retrieval_result.get("error", "检索失败")
            print(f"❌ 检索失败: {result.error}")
        
        return result


# 全局单例
_qa_pipeline_instance = None


def get_qa_pipeline() -> QAPipeline:
    """获取 QA Pipeline 单例"""
    global _qa_pipeline_instance
    if _qa_pipeline_instance is None:
        _qa_pipeline_instance = QAPipeline()
    return _qa_pipeline_instance
