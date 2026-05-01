# -*- coding: utf-8 -*-
"""
TurnSense 完整性检查模型客户端
检查问题是否语义完整、可回答
"""
import re
import torch
from typing import Tuple, List, Dict, Optional
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from .base_model import BaseModelClient


class TurnSenseClient(BaseModelClient):
    """
    TurnSense 模型客户端
    
    功能：检查问题的语义完整性
    - 问题是否完整（不是碎片化的词语）
    - 问题是否有意义（不是乱码、重复字符等）
    - 问题是否可回答（包含必要的上下文信息）
    """

    # 规则过滤：拦截明显无效的问题
    INVALID_PATTERNS = [
        (r'^[a-zA-Z]$', '单个字母'),
        (r'^\d+$', '纯数字'),
        (r'^(.)\1{4,}$', '重复字符'),  # 同一字符重复5次以上
        (r'^[\s\W]+$', '无有效字符'),
        (r'^.{0,1}$', '问题太短'),
    ]

    def __init__(self, model_name: str = None, device: str = None):
        from config import Config
        model_name = model_name or Config.TURN_SENSE_MODEL
        device = device or Config.TURN_SENSE_DEVICE
        super().__init__(model_name, device)
        self.threshold = Config.COMPLETENESS_THRESHOLD
        self.invalid_patterns = [(re.compile(p), desc) for p, desc in self.INVALID_PATTERNS]

    def load_model(self):
        """加载 TurnSense 模型"""
        if self._is_loaded:
            return

        try:
            print(f"🔄 正在加载 TurnSense 模型: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self._model.to(self.device)
            self._model.eval()
            self._is_loaded = True
            print(f"✅ TurnSense 模型加载完成！设备: {self.device}")
        except Exception as e:
            print(f"⚠️ TurnSense 模型加载失败: {str(e)}，将使用规则模式")
            self._is_loaded = False

    def check_completeness(self, question: str) -> Tuple[bool, str]:
        """
        检查问题的完整性
        
        Args:
            question: 用户问题
            
        Returns:
            (is_complete, reason): 是否完整、原因
        """
        # 第一层：规则快速过滤
        is_valid, reason = self._rule_check(question)
        if not is_valid:
            return False, reason

        # 第二层：模型语义完整性判断
        self.ensure_loaded()
        if self._is_loaded and self._model is not None:
            try:
                is_complete, score = self._model_check(question)
                if not is_complete:
                    return False, f"问题语义不完整（模型判断得分: {score:.2f}）"
            except Exception as e:
                print(f"⚠️ 模型检查失败: {str(e)}")

        return True, ""

    def _rule_check(self, question: str) -> Tuple[bool, str]:
        """
        规则检查：拦截无效问题
        
        Returns:
            (is_valid, reason): 是否有效、原因
        """
        if not question or not question.strip():
            return False, "问题为空"

        question = question.strip()

        # 检查无效模式
        for pattern, desc in self.invalid_patterns:
            if pattern.search(question):
                return False, f"问题格式无效：{desc}"

        # 检查是否只包含标点符号
        if re.match(r'^[\s\W]+$', question):
            return False, "问题不包含有效字符"

        # 检查长度（太短的问题可能不完整）
        if len(question) < 2:
            return False, "问题太短，请提供更多信息"

        return True, ""

    def _model_check(self, question: str) -> Tuple[bool, float]:
        """
        使用模型检查问题的语义完整性
        
        Returns:
            (is_complete, score): 是否完整、完整度得分
        """
        try:
            inputs = self._tokenizer(question, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits
                probs = torch.softmax(logits, dim=-1)
                # 假设 label 1 表示完整，0 表示不完整
                completeness_score = probs[0][1].item() if probs.shape[1] > 1 else probs[0][0].item()
                is_complete = completeness_score >= self.threshold
                return is_complete, completeness_score
        except Exception as e:
            print(f"⚠️ 模型检查异常: {str(e)}")
            return True, 1.0  # 默认认为完整


# 全局单例
_turn_sense_instance = None


def get_turn_sense() -> TurnSenseClient:
    """获取 TurnSense 客户端单例"""
    global _turn_sense_instance
    if _turn_sense_instance is None:
        _turn_sense_instance = TurnSenseClient()
    return _turn_sense_instance
