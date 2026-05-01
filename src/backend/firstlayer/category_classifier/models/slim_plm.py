# -*- coding: utf-8 -*-
"""
SlimPLM 查询改写模型客户端
将含指代/上下文依赖的问题改写为完整独立的查询
"""
import torch
from typing import List, Dict, Optional
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from .base_model import BaseModelClient


class SlimPLMClient(BaseModelClient):
    """
    SlimPLM-Query-Rewriting 模型客户端
    
    功能：将依赖上下文的查询改写为独立完整的查询
    例如：
    - 输入: "它怎么开通？", 上下文: "用户: 彩铃服务是什么？"
    - 输出: "彩铃服务怎么开通？"
    """

    SYSTEM_PROMPT = """你是一个查询改写助手。你的任务是将依赖上下文的查询改写为独立、完整的查询。
规则：
1. 如果查询中包含指代词（它、这个、那个等），根据上下文替换为具体实体
2. 确保改写后的查询是完整、独立的句子
3. 保持原意不变
4. 只输出改写后的查询，不要有任何其他输出"""

    def __init__(self, model_name: str = None, device: str = None):
        from config import Config
        model_name = model_name or Config.SLIM_PLM_MODEL
        device = device or Config.SLIM_PLM_DEVICE
        super().__init__(model_name, device)
        self.system_prompt = self.SYSTEM_PROMPT

    def load_model(self):
        """加载 SlimPLM 模型"""
        if self._is_loaded:
            return

        try:
            print(f"🔄 正在加载 SlimPLM 模型: {self.model_name}")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                device_map=self.device if self.device == "cuda" else None
            )
            if self.device == "cpu":
                self._model.to(self.device)
            self._model.eval()
            self._is_loaded = True
            print(f"✅ SlimPLM 模型加载完成！设备: {self.device}")
        except Exception as e:
            print(f"⚠️ SlimPLM 模型加载失败: {str(e)}，将使用规则模式")
            self._is_loaded = False

    def rewrite_query(self, question: str, context: str = "") -> str:
        """
        改写查询为独立完整的查询
        
        Args:
            question: 用户问题
            context: 上下文（历史对话）
            
        Returns:
            改写后的查询
        """
        self.ensure_loaded()

        if not self._is_loaded or self._model is None:
            # 模型未加载，使用规则改写
            return self._rule_based_rewrite(question, context)

        try:
            # 构建输入
            if context:
                user_input = f"上下文：{context}\n\n查询：{question}\n\n改写后的查询："
            else:
                user_input = f"查询：{question}\n\n改写后的查询："

            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_input}
            ]

            # 使用 chat template
            input_text = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self._tokenizer(input_text, return_tensors="pt").to(self.device)

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=128,
                    temperature=0.1,
                    do_sample=False,
                    pad_token_id=self._tokenizer.eos_token_id
                )

            # 只取新生成的部分
            new_tokens = outputs[0][inputs['input_ids'].shape[1]:]
            rewritten = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

            # 如果改写结果太短或和原问题一样，返回原问题
            if len(rewritten) < 2 or rewritten == question:
                return question

            return rewritten

        except Exception as e:
            print(f"⚠️ 模型改写失败: {str(e)}")
            return self._rule_based_rewrite(question, context)

    def _rule_based_rewrite(self, question: str, context: str) -> str:
        """
        基于规则的查询改写（模型不可用时的降级方案）
        
        简单策略：
        1. 如果问题很短（<10字符）且上下文不为空，尝试拼接
        2. 去除指代词，从上下文中补充信息
        """
        if not context or len(question) > 20:
            return question

        # 简单拼接：取上下文最后一句作为前缀
        context_lines = [line.strip() for line in context.split('\n') if line.strip()]
        if context_lines:
            last_line = context_lines[-1]
            # 如果最后一行是用户问题，用它作为上下文
            if '用户' in last_line or 'user' in last_line.lower():
                # 提取问题部分
                match = re.search(r'[:：]\s*(.+)', last_line)
                if match:
                    prefix = match.group(1)
                    return f"{prefix} {question}"
            return f"{last_line} {question}"

        return question


# 全局单例
_slim_plm_instance = None


def get_slim_plm() -> SlimPLMClient:
    """获取 SlimPLM 客户端单例"""
    global _slim_plm_instance
    if _slim_plm_instance is None:
        _slim_plm_instance = SlimPLMClient()
    return _slim_plm_instance
