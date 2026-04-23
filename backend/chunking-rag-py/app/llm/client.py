from typing import AsyncIterator

from openai import AsyncOpenAI


class LlmClient:
    def __init__(self, client: AsyncOpenAI, model: str):
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, *, api_key: str, base_url: str, model: str) -> "LlmClient":
        return cls(client=AsyncOpenAI(api_key=api_key, base_url=base_url), model=model)

    async def stream_answer(self, prompt: str) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", None)
            if token:
                yield token
