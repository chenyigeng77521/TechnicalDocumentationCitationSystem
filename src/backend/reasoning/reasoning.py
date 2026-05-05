"""
Layer 3 核心推理逻辑
Pipeline: 可回答性判定 → Context构建 → LLM推理 → 引用校验 → 后处理
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

import openai

from config import (
    LLM_API_KEY,
    LLM_API_BASE,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    MAX_CONTEXT_CHARS,
    PROMPT_TEMPLATE,
    REFUSAL_TEXT,
    SCORE_THRESHOLD,
    SIMILARITY_THRESHOLD,
)
from interfaces import Citation, GoldSource, ReasoningResult, RetrievedChunk

logger = logging.getLogger(__name__)


# ==================== LLM 客户端（单例）====================

_llm_client: Optional[openai.OpenAI] = None


def get_llm_client() -> openai.OpenAI:
    """获取 OpenAI 兼容客户端（单例）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = openai.OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_API_BASE,
            timeout=LLM_TIMEOUT,
        )
    return _llm_client


# ==================== Step 1：可回答性判定 ====================

def is_answerable(chunks: list[RetrievedChunk]) -> tuple[bool, str, float]:
    """
    可回答性双阈值判定（不进 LLM，纯规则，< 1ms）

    Returns:
        (answerable, refuse_reason, max_score)
    """
    if not chunks:
        return False, "empty_retrieval", 0.0

    max_score = max(c.score for c in chunks)

    # 硬阈值：最高分低于 0.4 → 拒答
    if max_score < SCORE_THRESHOLD:
        return False, "score_below_threshold", max_score

    # 覆盖度检查：必须至少有一个 chunk 分数 > 0.5
    # 防止"边缘分数"导致的误召
    if not any(c.score > 0.5 for c in chunks):
        return False, "score_below_threshold", max_score

    return True, "", max_score


# ==================== Step 2：Context 构建 ====================

def build_context_blocks(chunks: list[RetrievedChunk]) -> tuple[str, list[RetrievedChunk]]:
    """
    将 chunks 格式化为 prompt 中的 Context 块，严格原文注入，不摘要、不改写。
    超出 MAX_CONTEXT_CHARS 时从低分 chunk 开始截断（chunks 应已按 score 降序排列）。

    Returns:
        (context_blocks_text, used_chunks)  # used_chunks 是实际注入的 chunk 列表
    """
    blocks: list[str] = []
    used_chunks: list[RetrievedChunk] = []
    total_chars = 0

    for idx, chunk in enumerate(chunks, start=1):
        # 格式化单个 chunk 块
        truncation_note = "\n[此段内容已截断，建议查阅原文]" if chunk.is_truncated else ""
        block = (
            f"[ID: {idx}, Source: {chunk.doc_path} | anchor: {chunk.anchor}]\n"
            f"{chunk.content}{truncation_note}"
        )
        block_chars = len(block)

        # 超出上下文限制时停止追加
        if total_chars + block_chars > MAX_CONTEXT_CHARS:
            logger.warning("Context 超出限制，已截断至 %d 个 chunk", idx - 1)
            break

        blocks.append(block)
        used_chunks.append(chunk)
        total_chars += block_chars

    return "\n\n".join(blocks), used_chunks


# ==================== Step 3：LLM 推理（含 retry）====================

def call_llm(prompt: str) -> str:
    """
    调用 LLM，失败时 retry 1 次。
    返回原始字符串输出，调用方负责解析。

    Raises:
        RuntimeError: 两次尝试均失败
    """
    client = get_llm_client()
    last_err: Optional[Exception] = None

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=LLM_TEMPERATURE,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_err = e
            if attempt == 0:
                logger.warning("LLM 调用第 1 次失败，1s 后重试: %s", e)
                time.sleep(1)

    raise RuntimeError(f"LLM 调用失败（已重试 1 次）: {last_err}") from last_err


def parse_llm_output(raw: str) -> tuple[Optional[dict], bool]:
    """
    解析 LLM 输出：
    - 输出 REFUSE（纯文本）→ 返回 (None, is_refuse=True)
    - 输出 {"refuse": true, "trap_type": "...", "unanswerable_reason": "..."} → (dict, is_refuse=True)
    - 输出合法有答 JSON → 返回 (dict, False)
    - 解析失败 → 返回 (None, False)（调用方按拒答处理）

    Returns:
        (parsed_dict_or_None, is_llm_refuse)
    """
    # 去除可能的 markdown 代码块包裹
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # 纯文本 REFUSE
    if text.upper() == "REFUSE":
        return None, True

    # 尝试 JSON 解析
    data: Optional[dict] = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON 对象（LLM 可能加了多余文字）
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if data is None:
        logger.warning("LLM 输出无法解析为 JSON: %s", raw[:200])
        return None, False

    # 拒答型 JSON：{"refuse": true, ...}
    if data.get("refuse") is True:
        return data, True

    # 有答型 JSON：{"answer": "...", "citation_ids": [...]}
    return data, False


# ==================== Step 4：引用校验（硬一致性验证）====================

def validate_citations(
    citation_ids: list[int],
    used_chunks: list[RetrievedChunk],
) -> list[int]:
    """
    校验 LLM 输出的 citation_ids 是否全部在合法范围内（1-based）。
    非法 ID 直接剔除（不拒答，但不允许无效引用进入响应）。

    Returns:
        valid_ids（过滤后的合法 ID 列表）
    """
    valid_range = set(range(1, len(used_chunks) + 1))
    valid_ids = [cid for cid in citation_ids if cid in valid_range]

    removed = [cid for cid in citation_ids if cid not in valid_range]
    if removed:
        logger.warning("检测到非法引用 ID，已剔除: %s", removed)

    # 如果所有引用都被剔除 → 引用全部非法 → 触发拒答
    if citation_ids and not valid_ids:
        return []  # 空列表表示引用全部非法

    return valid_ids

# ==================== 主推理 Pipeline ====================

def run_reasoning(query: str, chunks: list[RetrievedChunk]) -> ReasoningResult:
    """
    Layer 3 完整推理 Pipeline：
      1. 可回答性判定
      2. Context 构建
      3. LLM 推理
      4. 引用校验
      5. 后处理输出

    所有错误均走 Fail Fast → 拒答，不向上抛异常。
    """
    # ---------- Step 1：可回答性判定 ----------
    answerable, refuse_reason, max_score = is_answerable(chunks)
    if not answerable:
        logger.info("拒答（%s），max_score=%.3f", refuse_reason, max_score)
        return ReasoningResult(
            answer=REFUSAL_TEXT + " 分数小于" + SCORE_THRESHOLD +"检查不通过",
            is_refusal=True,
            refuse_reason=refuse_reason,
            max_score=max_score,
            confidence=0.0,
        )

    # ---------- Step 2：构建 Context ----------
    context_blocks, used_chunks = build_context_blocks(chunks)

    # ---------- Step 3：LLM 推理 ----------
    prompt = PROMPT_TEMPLATE.format(
        context_blocks=context_blocks,
        query=query,
    )

    try:
        raw_output = call_llm(prompt)
    except RuntimeError as e:
        logger.error("LLM 调用最终失败: %s", e)
        return ReasoningResult(
            answer=REFUSAL_TEXT,
            is_refusal=True,
            refuse_reason="llm_error",
            max_score=max_score,
            confidence=0.0,
        )

    # ---------- Step 3.5：解析 LLM 输出 ----------
    parsed, is_llm_refuse = parse_llm_output(raw_output)

    if is_llm_refuse:
        # LLM 主动拒答：尝试从 parsed 中提取 trap_type/unanswerable_reason
        trap_type: Optional[str] = None
        unanswerable_reason: Optional[str] = None
        if parsed:
            trap_type = parsed.get("trap_type") or None
            unanswerable_reason = parsed.get("unanswerable_reason") or None
        logger.info("LLM 主动拒答，trap_type=%s", trap_type)
        return ReasoningResult(
            answer=REFUSAL_TEXT + unanswerable_reason,
            is_refusal=True,
            refuse_reason="llm_refuse",
            max_score=max_score,
            confidence=0.0,
            trap_type=trap_type,
            unanswerable_reason=unanswerable_reason,
        )

    if parsed is None:
        # JSON 解析失败 → 拒答
        logger.warning("JSON 解析失败 → 拒答")
        return ReasoningResult(
            answer=REFUSAL_TEXT,
            is_refusal=True,
            refuse_reason="json_parse_error",
            max_score=max_score,
            confidence=0.0,
        )

    answer_text: str = parsed.get("answer", "").strip()
    raw_citation_ids: list = parsed.get("citation_ids", [])

    # 确保 citation_ids 是整数列表
    try:
        citation_ids = [int(cid) for cid in raw_citation_ids]
    except (TypeError, ValueError):
        citation_ids = []

    if not answer_text:
        return ReasoningResult(
            answer=REFUSAL_TEXT,
            is_refusal=True,
            refuse_reason="empty_answer",
            max_score=max_score,
            confidence=0.0,
        )

    # ---------- Step 4：引用校验 ----------
    valid_citation_ids = validate_citations(citation_ids, used_chunks)

    # 所有引用均非法（LLM 编造了不存在的 ID） → 拒答
    if citation_ids and not valid_citation_ids:
        logger.warning("引用全部非法 → 拒答")
        return ReasoningResult(
            answer=REFUSAL_TEXT,
            is_refusal=True,
            refuse_reason="invalid_citation",
            max_score=max_score,
            confidence=0.0,
        )

    # ---------- Step 5：成功响应 ----------
    confidence = round(max_score, 4)

    return ReasoningResult(
        answer=answer_text,
        citation_ids=valid_citation_ids,
        is_refusal=False,
        refuse_reason=None,
        max_score=max_score,
        confidence=confidence,
    )


def build_citations(
    citation_ids: list[int],
    used_chunks: list[RetrievedChunk],
) -> list[Citation]:
    """
    将内部 citation_id（1-based）映射为赛题标准 Citation 格式。
    """
    result: list[Citation] = []
    seen: set[tuple[str, str]] = set()  # 去重

    for cid in citation_ids:
        if 1 <= cid <= len(used_chunks):
            chunk = used_chunks[cid - 1]
            key = (chunk.doc_path, chunk.anchor)
            if key not in seen:
                seen.add(key)
                result.append(Citation(doc_path=chunk.doc_path, anchor=chunk.anchor))

    return result
