from typing import List, Optional
import google.generativeai as genai
from packages.llm.base import LLMMessage, LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        genai.configure(api_key=api_key)
        self.model_name = model

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        system_instruction = None
        user_parts = []

        for m in messages:
            if m.role == "system":
                system_instruction = m.content
            else:
                user_parts.append(f"[{m.role.upper()}]:\n{m.content}")

        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_instruction,
        )

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if response_format == "json" else None,
        )

        prompt = "\n\n".join(user_parts)
        # Run async in executor if generate_content_async is available
        resp = await model.generate_content_async(
            prompt,
            generation_config=generation_config,
        )

        return LLMResponse(
            content=resp.text or "",
            model=self.model_name,
            usage={},
        )
