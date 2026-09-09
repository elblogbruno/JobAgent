from typing import List, Optional
import anthropic
from packages.llm.base import LLMMessage, LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        system_content = ""
        prompt_messages = []

        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                prompt_messages.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": self.model,
            "messages": prompt_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_content:
            kwargs["system"] = system_content

        resp = await self.client.messages.create(**kwargs)
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))

        return LLMResponse(
            content=text,
            model=resp.model,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )
