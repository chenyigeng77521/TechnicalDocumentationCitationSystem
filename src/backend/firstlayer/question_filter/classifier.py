# -*- coding: utf-8 -*-
"""
问题过滤器 - 使用 hfl/chinese-roberta-wwm-ext 进行问题分类和过滤
支持多级过滤策略：规则 -> 关键词 -> ML 模型 -> 上下文记忆层
"""

import re
import torch
import sys
import os
from typing import Dict, List, Optional
import json
import httpx

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transformers import AutoTokenizer, AutoModelForSequenceClassification
from config import Config


class QuestionFilter:
    """问题过滤器 - 多级过滤策略"""
    
    def __init__(self):
        self.is_loaded = False
        self.tokenizer = None
        self.model = None
        
        # 分类标签（6 分类）
        self.labels = ["VALID", "INVALID", "REALTIME", "CHAT", "OFFTOPIC", "SELF_INRO"]
        self.label_descriptions = {
            "VALID": "有效问题 - 属于知识库范围内的可回答問題，可以继续处理",
            "INVALID": "无效问题 - 无法回答的问题（空问题、乱码、无关内容等）",
            "REALTIME": "实时类问题 - 需要实时数据的问题（天气、新闻、股价等），系统无法回答",
            "CHAT": "友好闲聊 - 日常问候和友好交流，可适度回应并引导回知识库",
            "OFFTOPIC": "偏离主题 - 与知识库完全无关的问题（恶意/敏感/广告等）",
            "SELF_INRO": "自我介绍 - 询问 AI 助手身份/能力/介绍的问题，需要引导回知识库"
        }
        
        # 中文 Unicode 范围
        self.chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
        
        # 无效问题正则模式
        self.invalid_patterns = [
            (re.compile(r'^\s*$'), "空问题"),
            (re.compile(r'^[^\u4e00-\u9fff\s]+$/'), "无中文字符"),
            (re.compile(r'^[!@#$%^&*()_+\-=\[\]\{\};:\'",.<>/?\\|`~~]+$/'), "只有标点符号"),
        ]
        
        # 实时类关键词
        self.realtime_keywords = Config.REALTIME_KEYWORDS
        
        # 闲聊类关键词
        self.chat_keywords = Config.CHAT_KEYWORDS
        
        # 自我介绍类关键词
        self.self_intro_keywords = Config.SELF_INTRO_KEYWORDS
        
        # 上下文记忆层配置（预留）
        self.context_memory_url = getattr(Config, 'CONTEXT_MEMORY_URL', 'http://localhost:3006')
        self.context_memory_enabled = getattr(Config, 'CONTEXT_MEMORY_ENABLED', False)
        
    def load_model(self):
        """加载中文文本分类模型"""
        if self.is_loaded:
            return
            
        print("🔄 问题过滤器初始化中...")
        print(f"🤖 模型：{Config.MODEL_NAME}")
        
        # 加载 tokenizer 和模型
        self._load_model()
        
        self.is_loaded = True
        print("✅ 问题过滤器已初始化完成")
        
    def _load_model(self):
        """加载中文 RoBERTa 分类模型"""
        if self.tokenizer is not None:
            return
            
        try:
            print("🔄 正在加载中文 RoBERTa 模型...")
            model_name = Config.MODEL_NAME
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # 加载分类模型
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_name,
                num_labels=len(self.labels),
                trust_remote_code=False
            )
            
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model.to(self.device)
            self.model.eval()
            
            print(f"✅ 模型加载完成！设备：{self.device}")
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️  模型加载失败：{error_msg[:200]}")
            print("   将使用规则匹配作为备用方案")
            self.model = None
        
    def is_chinese(self, text: str) -> bool:
        """检测文本是否包含中文"""
        chinese_chars = self.chinese_pattern.findall(text)
        return len(chinese_chars) > 0
        
    def check_invalid_by_rules(self, question: str) -> Optional[Dict]:
        """通过规则检查无效问题"""
        question_stripped = question.strip()
        
        # 空问题检查
        if not question_stripped:
            return {
                "success": True,
                "question": question,
                "category": "INVALID",
                "confidence": 1.0,
                "description": self.label_descriptions["INVALID"],
                "reason": "问题为空",
                "need_context_check": False
            }
        
        # 正则模式匹配
        for pattern, reason in self.invalid_patterns:
            if pattern.match(question):
                return {
                    "success": True,
                    "question": question,
                    "category": "INVALID",
                    "confidence": 0.9,
                    "description": self.label_descriptions["INVALID"],
                    "reason": reason,
                    "need_context_check": False
                }
        
        # 无中文字符检查（至少需要 2 个中文字符）
        chinese_count = len(self.chinese_pattern.findall(question))
        if chinese_count < 2:
            return {
                "success": True,
                "question": question,
                "category": "INVALID",
                "confidence": 0.8,
                "description": self.label_descriptions["INVALID"],
                "reason": "问题过短或无有效中文字符",
                "need_context_check": False
            }
        
        return None  # 规则未匹配，继续 ML 分类
        
    def check_realtime_by_keywords(self, question: str) -> Optional[Dict]:
        """通过关键词检查实时类问题"""
        question_lower = question.lower()
        
        for keyword in self.realtime_keywords:
            if keyword in question_lower:
                return {
                    "success": True,
                    "question": question,
                    "category": "REALTIME",
                    "confidence": 0.85,
                    "description": self.label_descriptions["REALTIME"],
                    "reason": f"包含实时关键词：{keyword}",
                    "need_context_check": False
                }
        
        return None
        
    def check_chat_by_keywords(self, question: str) -> Optional[Dict]:
        """通过关键词检查闲聊类问题"""
        question_lower = question.lower()
        
        high_confidence_keywords = [
            "你好", "您好", "再见", "拜拜", "晚安", "嗨", "哈喽", "hello", "hi",
            "谢谢", "谢谢你", "感谢", "多谢", "辛苦了", "对不起", "抱歉",
        ]
        
        single_match_keywords = [
            "吃了吗", "吃饭", "吃饭了吗", "吃啥", "干嘛", "干啥", "在干嘛", "在忙什么",
            "干什么呢", "在干什么", "在忙啥", "忙什么呢",
            "大爷", "大爷的", "出去", "都出去", "出去吧", "都出去吧",
            "滚", "滚蛋", "滚开", "走开", "别烦我", "烦死了",
            "去你的", "去死", "去他妈", "他妈的", "妈的",
            "在吗", "有空吗", "在不在", "有人吗",
        ]
        
        matched_keywords = []
        matched_high_conf = False
        matched_single = False
        
        for keyword in self.chat_keywords:
            if keyword in question_lower:
                matched_keywords.append(keyword)
                if keyword in high_confidence_keywords:
                    matched_high_conf = True
                if keyword in single_match_keywords:
                    matched_single = True
        
        if matched_high_conf or matched_single or len(matched_keywords) >= 2:
            return {
                "success": True,
                "question": question,
                "category": "CHAT",
                "confidence": 0.9 if (matched_high_conf or matched_single) else min(0.6 + len(matched_keywords) * 0.1, 0.95),
                "description": self.label_descriptions["CHAT"],
                "reason": f"包含闲聊关键词：{', '.join(matched_keywords[:3])}",
                "need_context_check": False
            }
        
        return None
        
    def check_self_intro_by_keywords(self, question: str) -> Optional[Dict]:
        """通过关键词检查自我介绍类问题"""
        question_lower = question.lower()
        
        matched_keywords = []
        
        for keyword in self.self_intro_keywords:
            if keyword in question_lower:
                matched_keywords.append(keyword)
        
        if len(matched_keywords) >= 1:
            return {
                "success": True,
                "question": question,
                "category": "SELF_INRO",
                "confidence": min(0.7 + len(matched_keywords) * 0.1, 0.95),
                "description": self.label_descriptions["SELF_INRO"],
                "reason": f"包含自我介绍关键词：{', '.join(matched_keywords[:3])}",
                "need_context_check": False
            }
        
        return None
        
    def classify(self, question: str, conversation_history: Optional[List[Dict]] = None) -> Dict:
        """
        对问题进行多级过滤分类
        
        过滤流程：
        1. 规则检查（快速过滤无效问题）
        2. 关键词检查（闲聊、自我介绍、实时类）
        3. ML 模型分类（RoBERTa）
        4. 上下文记忆层二次过滤（可选，用于边界情况）
        
        Args:
            question: 用户问题
            conversation_history: 对话历史（可选，用于上下文记忆层）
            
        Returns:
            {
                "success": bool,
                "category": str,
                "confidence": float,
                "description": str,
                "reason": str,
                "need_context_check": bool,  # 是否需要上下文记忆层二次过滤
                "final_category": str | None  # 上下文记忆层过滤后的最终分类
            }
        """
        if not self.is_loaded:
            self.load_model()
            
        # ========== 第一级：规则检查 ==========
        rule_result = self.check_invalid_by_rules(question)
        if rule_result:
            return rule_result
            
        # ========== 第二级：关键词检查 ==========
        # 闲聊类问题（优先）
        chat_result = self.check_chat_by_keywords(question)
        if chat_result:
            return chat_result
            
        # 自我介绍类问题
        self_intro_result = self.check_self_intro_by_keywords(question)
        if self_intro_result:
            return self_intro_result
            
        # 实时类问题
        keyword_result = self.check_realtime_by_keywords(question)
        if keyword_result:
            return keyword_result
        
        # ========== 第三级：ML 模型分类 ==========
        ml_result = None
        if self.model is not None:
            ml_result = self._ml_classify(question)
        
        # 如果没有 ML 模型或 ML 分类置信度较低，标记需要上下文记忆层检查
        need_context_check = False
        if self.model is None:
            # 没有 ML 模型，所有问题都交给上下文记忆层（如果启用）
            need_context_check = self.context_memory_enabled
        elif ml_result and ml_result["confidence"] < 0.6:
            # ML 置信度低，需要二次确认
            need_context_check = self.context_memory_enabled
        
        # ========== 第四级：上下文记忆层二次过滤（预留） ==========
        final_category = None
        if need_context_check and conversation_history is not None:
            # 注意：这里需要异步调用，暂时同步处理
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except:
                loop = asyncio.new_event_loop()
            context_result = loop.run_until_complete(
                self._check_with_context_memory(question, conversation_history)
            )
            if context_result:
                final_category = context_result["category"]
        
        # 返回 ML 结果或默认 VALID
        if ml_result:
            ml_result["need_context_check"] = need_context_check
            ml_result["final_category"] = final_category
            return ml_result
        
        # 默认返回 VALID
        return {
            "success": True,
            "question": question,
            "category": "VALID",
            "confidence": 0.5,
            "description": self.label_descriptions["VALID"],
            "reason": "规则未匹配，默认视为有效问题",
            "need_context_check": need_context_check,
            "final_category": final_category
        }
    
    def _ml_classify(self, question: str) -> Dict:
        """使用 RoBERTa 模型分类"""
        try:
            # 编码输入
            inputs = self.tokenizer(
                question,
                return_tensors="pt",
                truncation=True,
                max_length=Config.MAX_LENGTH,
                padding=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # 推理
            with torch.no_grad():
                outputs = self.model(**inputs)
                probabilities = torch.softmax(outputs.logits, dim=-1)
                confidence = probabilities[0].max().item()
                predicted_id = probabilities[0].argmax().item()
            
            # 获取预测标签
            if 0 <= predicted_id < len(self.labels):
                category = self.labels[predicted_id]
                return {
                    "success": True,
                    "question": question,
                    "category": category,
                    "confidence": confidence,
                    "description": self.label_descriptions[category],
                    "reason": "ML 模型分类结果"
                }
        except Exception as e:
            print(f"RoBERTa 分类失败：{str(e)}")
            
        return {
            "success": True,
            "question": question,
            "category": "VALID",
            "confidence": 0.5,
            "description": self.label_descriptions["VALID"],
            "reason": "模型推理失败，默认视为有效问题"
        }
    
    async def _check_with_context_memory(self, question: str, conversation_history: List[Dict]) -> Optional[Dict]:
        """
        上下文记忆层二次过滤（预留接口）
        
        当 ML 模型置信度较低时，调用上下文记忆层进行二次判断
        上下文记忆层会分析对话历史，判断当前问题是否需要结合上下文理解
        
        Args:
            question: 用户问题
            conversation_history: 对话历史
            
        Returns:
            {"category": str, "confidence": float} 或 None
        """
        if not self.context_memory_enabled:
            return None
            
        try:
            print(f"🔄 调用上下文记忆层进行二次过滤...")
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.context_memory_url}/api/filter-with-context",
                    json={
                        "question": question,
                        "conversation_history": conversation_history
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ 上下文记忆层过滤结果：{data.get('category')}")
                    return {
                        "category": data.get("category", "VALID"),
                        "confidence": data.get("confidence", 0.8)
                    }
                else:
                    print(f"⚠️  上下文记忆层返回错误：{response.status_code}")
                    
        except Exception as e:
            print(f"⚠️  上下文记忆层调用失败：{str(e)}")
        
        return None
        
    def get_filter_response(self, category: str) -> str:
        """根据分类返回友好的提示语"""
        responses = {
            "VALID": None,
            "INVALID": "抱歉，您的问题不够清晰或无法识别。请重新表述您的问题。",
            "REALTIME": "抱歉，这是一个需要实时数据的问题（如天气、新闻、股价等），本系统无法提供实时信息。请问一个与知识库相关的问题。",
            "CHAT": "您好！😊 我是知识库助手，主要帮您解答公司制度、产品使用、技术文档等方面的问题。如果您有相关问题，欢迎随时提问！",
            "SELF_INRO": "您好！😊 我是知识库助手，主要帮您解答公司制度、产品使用、技术文档等方面的问题。如果您有相关问题，欢迎随时提问！",
            "OFFTOPIC": "抱歉，这个问题似乎与我们的知识库无关。请询问关于公司制度、产品使用、技术文档等相关问题。"
        }
        return responses.get(category, "抱歉，无法处理您的问题。")


# 单例模式
_classifier_instance = None

def get_classifier():
    """获取分类器单例"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = QuestionFilter()
    return _classifier_instance
