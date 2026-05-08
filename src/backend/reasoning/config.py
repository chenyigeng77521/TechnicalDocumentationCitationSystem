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

# 上下文最大 token 数（粗估：1 token ≈ 1.5 字符）
MAX_CONTEXT_TOKENS: int = 16000
MAX_CONTEXT_CHARS: int = int(MAX_CONTEXT_TOKENS * 1.5)  # 9000 字符

# ==================== LLM 配置 ====================

LLM_API_KEY: str = os.getenv("LLM_API_KEY", "sk-")
LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://aigw.asiainfo.com/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "aliyun/deepseek-v3.2")

# 推理温度：0.0 严格模式，最大程度抑制幻觉
LLM_TEMPERATURE: float = 0.0

# LLM 超时（秒）
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))

# ==================== 批量处理配置 ====================

BATCH_MAX_WORKERS: int = int(os.getenv("BATCH_MAX_WORKERS", "8"))
# 默认指向项目内 eval，基于本文件位置动态计算
_BATCH_DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "eval"
)
BATCH_OUTPUT_DIR: str = os.getenv("BATCH_OUTPUT_DIR", _BATCH_DEFAULT_DIR)

# ==================== 拒答固定文本 ====================
# 赛题要求统一格式，不得随意更改
REFUSAL_TEXT: str = "抱歉，我无法从提供的文档中找到答案。"

# ==================== 拒答原因生成 Prompt ====================
# 用于 is_answerable 判定不可回答时，调用 LLM 生成自然语言拒答解释
# 约束：严禁使用外部知识，只能基于 chunks 和 question 本身推断原因
REFUSE_REASON_PROMPT: str = """你是一个严格的技术文档问答助手，仅能使用下方提供的 Context 作答。

任务：分析问题是否基于错误前提，并解释为什么无法从 Context 中回答。

规则：
1. 严禁使用任何外部知识，只能基于 Context 内容与问题本身进行分析。
2. 首先检验问题是否包含错误前提或不存在的前提假设（如"某 API 已被弃用"但实际不存在该 API）。如果前提本身错误，直接指出前提错误。
3. 如果前提正确但 Context 信息不足，说明 Context 缺少哪些具体信息。
4. 直接说明原因，禁止使用"根据文档"、"根据上下文"等冗余引言。
5. 输出一句简洁中文，80字以内，不加标点外的任何格式符号。
6. 只输出原因本身，不要有任何前缀或后缀。

Context（检索到的相关片段）：
{context_snippets}

问题：{question}

拒答原因："""

# ==================== Prompt 模板 ====================
# 注意：所有逻辑控制在代码中完成，prompt 只传递规则
PROMPT_TEMPLATE: str = """你是一个严格的技术文档问答助手。

规则：
1. 仅根据下方提供的 Context 回答问题，严禁使用任何外部知识。
2. 回答前必须首先检验问题前提是否真实：检查问题中提及的 API/参数/概念/版本是否在 Context 中真实存在。若前提本身错误（如引用了不存在的 API 或已被删除的参数），必须拒答。
3. 如果 Context 中不包含回答所需信息，必须输出拒答 JSON，格式如下：
   {{"refuse": true, "trap_type": "<类型>", "unanswerable_reason": "<简明原因>"}}
   trap_type 必须从以下类型中选一个：fake_api / future_version / overgeneralization / parameter_mismatch / cross_domain / concept_confusion / procedure_step / non_existent_attribute
   - fake_api：问题提及的 API/方法在 Context 中不存在
   - future_version：问题涉及 Context 中未涵盖的未来版本特性
   - overgeneralization：问题过度泛化，Context 中只有更具体的子集
   - parameter_mismatch：参数名称或类型不匹配
   - cross_domain：问题跨域，如用 React 术语问 Vue 问题
   - concept_confusion：概念混淆，如混淆组件与 Hook
   - procedure_step：缺少操作步骤的完整上下文
   - non_existent_attribute：问题提及的属性/字段/选项在 Context 中不存在
   unanswerable_reason 是对无法回答的简明解释，必须基于 Context 内容说明原因。
4. 如果能够回答，必须输出有答 JSON，格式如下：
   {{"answer": "你的回答", "citation_ids": [1, 2, ...]}}
   citation_ids 是你引用的 Chunk 编号列表（即 [ID: n] 中的 n）。
5. 每个事实性陈述必须有对应 Chunk 支撑，citation_ids 中只能包含下方 Context 中实际存在的 ID。
6. 不得合并多个 Chunk 的内容进行推断，每条引用必须有直接支撑。
7. 回答简洁明确，不要说"根据文档"之类的冗余引言，直接给出结论。

Context：
{context_blocks}

问题：{query}

请直接输出 JSON，不要有任何其他文字："""
