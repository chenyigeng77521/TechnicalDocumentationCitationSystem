"""Judge prompt templating + response parsing."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass

PROMPT_VERSION = "v1.0"  # 改 prompt 必须 bump 这个，老缓存自动失效


_PROMPT_TEMPLATE = """你是一个严谨的技术问答评分裁判。

【评分依据的优先级】
- 第 1 优先：【标准答案】是最终判分的"对错"标准
- 第 2 参考:【原文出处】帮你理解标准答案的覆盖范围
- 不允许：用你自己的世界知识自由发挥（即使模型答案在你看来"事实正确"，
  但偏离标准答案 + 原文出处的范围，仍判 wrong）

【判分规则——中等严格度】
- 模型答案核心意思跟标准答案一致 → correct
- 措辞不同、多说了不冲突的细节 → correct
- 漏掉标准答案/原文中的关键事实 → wrong
- 跟标准答案/原文冲突 → wrong（即使模型答案"听起来对"）
- 答非所问 → wrong

【参考例子】

例子 1（correct）:
问题：React Compiler 的增量采用是什么意思？
标准答案：React Compiler 可以增量采用，允许先在代码库的特定部分试用编译器。
原文出处：React Compiler can be adopted incrementally, allowing you to try
         it on specific parts of your codebase first.
模型答案：React Compiler 的增量采用是指允许你先在代码库的特定部分尝试
         编译器，在现有项目中逐步推出，让你控制推出节奏。
判定：correct
原因：覆盖标准答案两个核心点——"增量采用" + "代码库特定部分"。
     "逐步推出 + 控制节奏"是对原文的合理延伸，没有冲突。

例子 2（wrong）:
问题：Spring 中 prototype 作用域的 Bean 行为是？
标准答案：prototype Bean 每次被请求时都会创建新实例。
原文出处：A prototype-scoped bean creates a new instance every time it is requested.
模型答案：prototype Bean 是单例的，全局共享同一个实例。
判定：wrong
原因：跟标准答案完全相反——标准答案明确"每次新建"，模型答的"单例"
     是 singleton 的行为，属于事实冲突。

---

现在请判分以下样本：

【问题】{question}
【标准答案】{gold_answer}
【原文出处】
{evidences_block}
【模型答案】{model_answer}

只返回 JSON，不要其他文字：
{{
  "verdict": "correct" 或 "wrong",
  "reason": "一句话说明，引用标准答案或原文的具体点"
}}
"""


@dataclass
class JudgeVerdict:
    verdict: str  # "correct" | "wrong"
    reason: str


class JudgeParseError(ValueError):
    pass


def render_prompt(question: str, gold_answer: str, evidences: list[str], model_answer: str) -> str:
    if evidences:
        ev_block = "\n".join(f"{i+1}. {e}" for i, e in enumerate(evidences))
    else:
        ev_block = "（无原文出处）"
    return _PROMPT_TEMPLATE.format(
        question=question.strip(),
        gold_answer=gold_answer.strip(),
        evidences_block=ev_block,
        model_answer=model_answer.strip(),
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(raw: str) -> JudgeVerdict:
    """容忍 LLM 在 JSON 前后加 markdown fence / 空白。"""
    m = _JSON_RE.search(raw)
    if not m:
        raise JudgeParseError(f"no JSON found in response: {raw[:200]!r}")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"invalid JSON: {e}; raw={raw[:200]!r}") from e
    if "verdict" not in data or "reason" not in data:
        raise JudgeParseError(f"missing fields: {data}")
    if data["verdict"] not in ("correct", "wrong"):
        raise JudgeParseError(f"invalid verdict {data['verdict']!r}, expected correct|wrong")
    return JudgeVerdict(verdict=data["verdict"], reason=str(data["reason"]))
