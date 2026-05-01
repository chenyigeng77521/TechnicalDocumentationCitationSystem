"""
Layer 3 配置模块
集中管理所有阈值、模型参数、Prompt 模板
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== 检索质量阈值 ====================

# Reranker 最高分低于此值 → 直接拒答，不进 LLM
SCORE_THRESHOLD: float = 0.4

# 语义相似度验证阈值：answer 与 cited chunk 余弦相似度必须超过此值
SIMILARITY_THRESHOLD: float = 0.75

# 上下文最大 token 数（粗估：1 token ≈ 1.5 字符）
MAX_CONTEXT_TOKENS: int = 6000
MAX_CONTEXT_CHARS: int = int(MAX_CONTEXT_TOKENS * 1.5)  # 9000 字符

# ==================== LLM 配置 ====================

LLM_API_KEY: str = os.getenv("LLM_API_KEY", "sk-")
LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-v4-pro")

# 推理温度：0.0 严格模式，最大程度抑制幻觉
LLM_TEMPERATURE: float = 0.0

# LLM 超时（秒）
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))

# ==================== 批量处理配置 ====================

BATCH_MAX_WORKERS: int = 8
BATCH_OUTPUT_DIR: str = os.getenv("BATCH_OUTPUT_DIR", "./eval")

# ==================== 拒答固定文本 ====================
# 赛题要求统一格式，不得随意更改
REFUSAL_TEXT: str = "抱歉，我无法从提供的文档中找到答案。"

# ==================== Prompt 模板 ====================
# 注意：所有逻辑控制在代码中完成，prompt 只传递规则
PROMPT_TEMPLATE: str = """你是一个严格的技术文档问答助手。

规则：
1. 仅根据下方提供的 Context 回答问题，严禁使用任何外部知识。
2. 如果 Context 中不包含回答所需信息，你必须输出：REFUSE
3. 如果能够回答，必须输出结构化 JSON，格式如下：
   {{"answer": "你的回答", "citation_ids": [1, 2, ...]}}
   citation_ids 是你引用的 Chunk 编号列表（即 [ID: n] 中的 n）。
4. 每个事实性陈述必须有对应 Chunk 支撑，citation_ids 中只能包含下方 Context 中实际存在的 ID。
5. 不得合并多个 Chunk 的内容进行推断，每条引用必须有直接支撑。
6. 回答简洁明确，不要说"根据文档"之类的冗余引言，直接给出结论。

Context：
{context_blocks}

问题：{query}

请直接输出 JSON 或 REFUSE，不要有任何其他文字："""
