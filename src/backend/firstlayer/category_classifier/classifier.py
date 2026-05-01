# -*- coding: utf-8 -*-
"""
问题分类器 - 规则匹配 + ML 模型混合方案
支持中文语言检测
"""

import re
import torch
import sys
import os
from typing import Dict, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from config import Config


class QuestionClassifier:
    """问题分类器 - 规则为主，ML 为辅"""
    
    def __init__(self):
        self.is_loaded = False
        self.use_ml = False  # 默认不使用 ML 模型
        self.tokenizer = None
        self.model = None
        
        # 分类标签
        self.labels = ["FACT", "PROC", "EXPL", "COMP", "META", "UNKNOWN"]
        self.label_descriptions = {
            "FACT": "事实型问题 - 询问具体事实、数据、定义、名称等",
            "PROC": "过程型问题 - 询问步骤、流程、操作方法、怎么做等",
            "EXPL": "解释型问题 - 询问原因、原理、机制、为什么等",
            "COMP": "比较型问题 - 询问对比、差异、区别、哪个更好等",
            "META": "元认知型问题 - 询问学习方法、思考过程、自我反思等",
            "UNKNOWN": "未知类型 - 无法归类到上述任何一类"
        }
        
        # 关键词规则（优化版 - 长关键词优先，含 sample_questions.json 提取关键词）
        self.rules = {
            "FACT": [
                # 原有
                r'多少', r'几年', r'多久', r'几分', r'几元', r'几人', r'哪个', r'何时', r'哪里', r'谁', r'什么', r'哪些',
                # 从 sample_questions 补充：具体事实查询场景
                r'几楼', r'几点', r'几天', r'缴纳比例', r'缴纳', r'比例', r'联系电话', r'工号', r'工资',
                r'体检', r'邮箱后缀', r'打卡机', r'工牌', r'办公用品', r'餐厅', r'会议室', r'公积金',
                r'试用期', r'员工手册', r'总部', r'在哪里查', r'在哪查', r'是多少', r'是什么时候',
            ],
            "PROC": [
                # 原有
                r'怎么申请', r'如何办理', r'怎么做', r'怎么弄', r'如何', r'怎样', r'怎么', r'步骤', r'流程', r'方法', r'操作',
                # 从 sample_questions 补充：申请/办理/开通等动作
                r'怎样申请', r'如何提交', r'如何开通', r'如何申请', r'怎样办理', r'怎么办理',
                r'办理.*手续', r'手续', r'开通', r'提交', r'申请.*假', r'申请.*工', r'申请.*证',
                r'办理.*证', r'预订', r'申请.*位', r'申请.*餐', r'申请.*活动', r'申请.*制',
            ],
            "EXPL": [
                # 原有
                r'是什么原因', r'为什么', r'为何', r'原因', r'原理', r'机制', r'因为', r'是由于',
                # 从 sample_questions 补充：原因/目的/存在意义
                r'为什么要', r'为什么需要', r'为什么会有', r'为什么是', r'目的是', r'有什么意义',
                r'扣钱', r'扣税', r'规定.*时间', r'为何要', r'有效期.*为什么',
            ],
            "COMP": [
                # 原有
                r'哪个更好', r'优缺点', r'有什么', r'区别', r'差异', r'对比', r'比较', r'不同', r'一样', r'相同',
                # 从 sample_questions 补充：比较/选择/差异场景
                r'有什么区别', r'有什么不同', r'哪个更', r'哪个划算', r'哪个重要', r'哪个优先',
                r'怎么选', r'能.*一起用', r'和.*一样吗', r'和.*区别', r'和.*不同', r'是否一样',
                r'更好用', r'更划算', r'更重要', r'哪种更', r'正式.*实习', r'合同工.*派遣',
            ],
            "META": [
                # 原有
                r'怎么提高', r'如何提升', r'学习方法', r'怎么学', r'如何提高', r'怎样提高', r'技巧', r'策略', r'反思',
                # 从 sample_questions 补充：能力提升/职业发展/人际关系/自我管理
                r'怎么做好', r'如何做好', r'如何规划', r'怎样建立', r'如何平衡', r'怎么应对',
                r'时间管理', r'职业发展', r'职业规划', r'职场.*压力', r'工作.*生活', r'团队协作',
                r'沟通能力', r'领导力', r'情商', r'演讲', r'项目管理', r'学习能力', r'人脉',
                r'适应.*环境', r'同事.*关系', r'向上管理', r'工作效率',
            ]
        }
        
        # 中文 Unicode 范围
        self.chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
        
    def load_model(self):
        """加载分类器（规则匹配 + ML 模型）"""
        if self.is_loaded:
            return
            
        print("✅ 规则分类器已初始化")
        print(f"🤖 模型：{Config.MODEL_NAME}")
        
        self.is_loaded = True
        
        # 加载 ML 模型（GLiClass - FLAN-T5 Base）
        self._load_ml_model()
        
    def _load_ml_model(self):
        """加载 FLAN-T5 模型（GLiClass）"""
        if self.tokenizer is not None:
            return
            
        try:
            print("🔄 正在加载 GLiClass 模型 (FLAN-T5 Base)...")
            model_name = Config.MODEL_NAME  # 使用 Config.MODEL_NAME
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model.to(self.device)
            self.model.eval()
            self.use_ml = True
            print(f"✅ GLiClass 模型加载完成！设备：{self.device}")
        except Exception as e:
            print(f"⚠️  ML 模型加载失败：{str(e)}，将使用规则匹配")
            self.use_ml = False
        
    def is_chinese(self, text: str) -> bool:
        """
        检测文本是否为中文
        
        Args:
            text: 待检测的文本
            
        Returns:
            bool: 是否主要为中文
        """
        # 统计中文字符数量
        chinese_chars = self.chinese_pattern.findall(text)
        chinese_count = len(chinese_chars)
        total_chars = len([c for c in text if c.strip()])  # 非空格字符总数
        
        if total_chars == 0:
            return False
            
        # 中文占比超过 30% 就认为是中文
        return chinese_count / total_chars >= 0.3
        
    def classify(self, question: str) -> Dict:
        """
        对问题进行分类 - 优先使用 ML 模型，规则作为辅助
        
        Args:
            question: 用户问题
            
        Returns:
            {"success": bool, "category": str, "confidence": float, "description": str, "error": str}
        """
        if not self.is_loaded:
            self.load_model()
            
        # 第一步：语言检测
        if not self.is_chinese(question):
            return {
                "success": False,
                "question": question,
                "category": None,
                "confidence": 0.0,
                "description": None,
                "error": "请用中文提问，系统暂不支持其他语言",
                "language_detected": "non-chinese"
            }
            
        # 优先使用 ML 模型分类（如果已加载）
        if self.use_ml and self.tokenizer is not None:
            ml_result = self._ml_classify(question)
            if ml_result["success"] and ml_result["category"] != "UNKNOWN":
                return ml_result
            
        # ML 模型未加载或失败，使用规则匹配
        question_lower = question.lower()
        scores = {}
        for category, patterns in self.rules.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, question_lower):
                    score += 1
            scores[category] = score
            
        # 找到最高分的类别
        max_score = max(scores.values())
        
        if max_score > 0:
            top_categories = [cat for cat, score in scores.items() if score == max_score]
            category = top_categories[0]
            confidence = min(0.6 + max_score * 0.1, 0.95)
            
            return {
                "success": True,
                "question": question,
                "category": category,
                "confidence": confidence,
                "description": self.label_descriptions[category]
            }
            
        # 都未匹配，返回 UNKNOWN
        return {
            "success": True,
            "question": question,
            "category": "UNKNOWN",
            "confidence": 0.5,
            "description": self.label_descriptions["UNKNOWN"]
        }
    
    def _ml_classify(self, question: str) -> Dict:
        """使用 ML 模型分类（备用方案）"""
        try:
            prompt = f"Classify question: {question} into FACT, PROC, EXPL, COMP, or META"
            inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model.generate(**inputs, max_length=10, num_beams=5)
            
            predicted_label = self.tokenizer.decode(outputs[0], skip_special_tokens=True).strip().upper()
            
            if predicted_label in self.labels:
                return {
                    "success": True,
                    "question": question,
                    "category": predicted_label,
                    "confidence": 0.7,
                    "description": self.label_descriptions[predicted_label]
                }
        except Exception as e:
            print(f"ML 分类失败：{str(e)}")
            
        return {
            "success": True,
            "question": question,
            "category": "UNKNOWN",
            "confidence": 0.5,
            "description": self.label_descriptions["UNKNOWN"]
        }


# 单例模式
_classifier_instance = None

def get_classifier():
    """获取分类器单例"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = QuestionClassifier()
    return _classifier_instance
