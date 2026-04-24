def build_prompt(question: str, chunks: list[dict]) -> str:
    context = "\n\n---\n\n".join(
        f"【文档 {i+1}】{c['content'][:500]}" for i, c in enumerate(chunks)
    )
    return f"""请根据以下【参考文档片段】回答问题。

【用户问题】
{question}

【参考文档片段】
{context}

【回答要求】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 如果文档中没有相关信息，请明确说明无法回答
3. 答案应直接、完整，避免额外无关解释

请开始回答："""
