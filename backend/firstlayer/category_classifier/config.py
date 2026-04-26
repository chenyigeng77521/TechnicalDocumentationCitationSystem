"""
问题分类系统配置
"""
import os
from dotenv import load_dotenv

load_dotenv()

# 分类标签
QUESTION_CATEGORIES = {
    "FACT": "事实型 - 询问具体事实、数据、定义等",
    "PROC": "过程型 - 询问步骤、流程、操作方法等",
    "EXPL": "解释型 - 询问原因、原理、机制等",
    "COMP": "比较型 - 询问对比、差异、优劣等",
    "META": "元认知型 - 询问学习方法、策略、自我反思等"
}

# GLiClass 模型配置
GLIClass_MODEL_NAME = "google/flan-t5-base"  # 使用 FLAN-T5 作为 base 模型
GLIClass_MAX_LENGTH = 128

# 服务配置
HOST = os.getenv("HOST", "0.0.0.0")
PORT_STR = os.getenv("PORT", "")
PORT = int(PORT_STR) if PORT_STR.strip() else 3004

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 关键字配置（用于规则匹配）
FACT_KEYWORDS = ["什么", "哪个", "何时", "哪里", "谁", "多少", "几", "年", "月", "日"]
PROC_KEYWORDS = ["如何", "怎样", "怎么", "步骤", "流程", "方法", "操作", "步骤"]
EXPL_KEYWORDS = ["为什么", "为何", "原因", "原理", "机制", "因为"]
COMP_KEYWORDS = ["区别", "差异", "对比", "比较", "哪个更好", "优缺点", "不同"]
META_KEYWORDS = ["怎么提高", "如何提升", "学习方法", "技巧", "策略", "反思"]

# Config 类（兼容旧代码）
class Config:
    """配置类（兼容接口）"""
    MODEL_NAME = GLIClass_MODEL_NAME
    MAX_LENGTH = GLIClass_MAX_LENGTH
    HOST = HOST
    PORT = PORT
    LOG_LEVEL = LOG_LEVEL
    FACT_KEYWORDS = FACT_KEYWORDS
    PROC_KEYWORDS = PROC_KEYWORDS
    EXPL_KEYWORDS = EXPL_KEYWORDS
    COMP_KEYWORDS = COMP_KEYWORDS
    META_KEYWORDS = META_KEYWORDS
