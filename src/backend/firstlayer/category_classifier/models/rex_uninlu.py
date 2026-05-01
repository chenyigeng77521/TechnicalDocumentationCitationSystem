# -*- coding: utf-8 -*-
"""
RexUniNLU 模型客户端 - 指代检测和指代替换
"""
import re
import torch
from typing import Optional, List, Dict, Tuple
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
from .base_model import BaseModelClient


class RexUniNLUClient(BaseModelClient):
    """
    RexUniNLU 模型客户端
    
    功能：
    1. 指代检测：判断问题是否包含指代词（这个、那个、它、他们等）
    2. 指代替换：将指代词替换为上下文中的具体实体
    """

    # 常见指代词模式
    ANAPHORA_PATTERNS = [
        r'\b这[个定件件事]\b',
        r'\b那[个件件事]\b',
        r'\b它\b',
        r'\b他\b',
        r'\b她\b',
        r'\b它们\b',
        r'\b他们\b',
        r'\b她们\b',
        r'\b前者\b',
        r'\b后者\b',
        r'\b以上\b',
        r'\b下述\b',
    ]

    def __init__(self, model_name: str = None, device: str = None):
        from config import Config
        model_name = model_name or Config.REX_UNINLU_MODEL
        device = device or Config.REX_UNINLU_DEVICE
        super().__init__(model_name, device)
        self.anaphora_patterns = [re.compile(p) for p in self.ANAPHORA_PATTERNS]

    def load_model(self):
        """加载 RexUniNLU 模型"""
        if self._is_loaded:
            return

        try:
            print(f"🔄 正在加载 RexUniNLU 模型: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            self._model.to(self.device)
            self._model.eval()
            self._is_loaded = True
            print(f"✅ RexUniNLU 模型加载完成！设备: {self.device}")
        except Exception as e:
            print(f"⚠️ RexUniNLU 模型加载失败: {str(e)}，将使用规则模式")
            self._is_loaded = False

    def detect_anaphora(self, question: str) -> Tuple[bool, List[str]]:
        """
        检测问题中的指代词
        
        Args:
            question: 用户问题
            
        Returns:
            (has_anaphora, anaphora_list): 是否有指代、指代词列表
        """
        # 先用规则快速检测
        anaphora_found = []
        for pattern in self.anaphora_patterns:
            matches = pattern.findall(question)
            if matches:
                anaphora_found.extend(matches)

        # 如果规则检测到，直接返回
        if anaphora_found:
            return True, list(set(anaphora_found))

        # 规则未检测到，尝试用模型检测
        self.ensure_loaded()
        if self._is_loaded and self._model is not None:
            try:
                return self._model_detect(question)
            except Exception as e:
                print(f"⚠️ 模型检测失败: {str(e)}")
                return False, []

        return False, []

    def _model_detect(self, question: str) -> Tuple[bool, List[str]]:
        """使用模型检测指代词"""
        try:
            prompt = f"Detect anaphora in: {question}"
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model.generate(**inputs, max_length=64)

            result = self._tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
            # 如果模型输出包含 "yes" 或具体指代词，认为有指代
            has_anaphora = "yes" in result.lower() or any(p.search(result) for p in self.anaphora_patterns)
            return has_anaphora, [result] if has_anaphora else []
        except Exception as e:
            print(f"⚠️ 模型检测异常: {str(e)}")
            return False, []

    def replace_anaphora(self, question: str, context: str) -> str:
        """
        将指代词替换为上下文中的实体
        
        Args:
            question: 用户问题
            context: 上下文（历史对话）
            
        Returns:
            替换后的问题
        """
        # 从上下文中提取可能的实体（简单策略：提取名词性短语）
        entities = self._extract_entities_from_context(context)

        if not entities:
            return question

        # 用第一个（最可能相关的）实体替换指代词
        result = question
        for pattern in self.anaphora_patterns:
            match = pattern.search(result)
            if match:
                # 用最可能的实体替换
                entity = self._find_most_relevant_entity(match.group(), entities, context)
                if entity:
                    result = pattern.sub(entity, result, count=1)
                    break  # 一次只替换一个指代词

        return result

    def _extract_entities_from_context(self, context: str) -> List[str]:
        """
        从上下文中提取可能的实体
        
        简单策略：
        1. 提取引号中的内容
        2. 提取常见实体模式（人名、地名、产品名等）
        """
        entities = []

        # 提取引号中的内容
        quoted = re.findall(r'["""\'](.*?)[""\'']', context)
        entities.extend(quoted)

        # 提取可能的实体（大写字母开头的连续词、数字+字母组合等）
        # 简化版：提取上下文中最近的用户问题中的关键词
        lines = context.split('\n')
        for line in lines:
            if '用户' in line or 'user' in line.lower():
                # 提取问题中的关键词（简单策略）
                words = re.findall(r'[\w\u4e00-\u9fff]+', line)
                # 过滤掉常见停用词
                stop_words = {'的', '是', '了', '在', '有', '和', '对', '这', '那', '什么', '怎么', '如何', '为什么'}
                entities.extend([w for w in words if len(w) > 1 and w not in stop_words])

        return list(set(entities))

    def _find_most_relevant_entity(self, anaphora: str, entities: List[str], context: str) -> Optional[str]:
        """
        找到最相关的实体来替换指代词
        
        简单策略：选择上下文中最近出现的实体
        """
        # 按在上下文中出现的顺序，选择最后一个
        for entity in reversed(entities):
            if entity in context:
                return entity
        return entities[0] if entities else None


# 全局单例
_rex_uninlu_instance = None


def get_rex_uninlu() -> RexUniNLUClient:
    """获取 RexUniNLU 客户端单例"""
    global _rex_uninlu_instance
    if _rex_uninlu_instance is None:
        _rex_uninlu_instance = RexUniNLUClient()
    return _rex_uninlu_instance
