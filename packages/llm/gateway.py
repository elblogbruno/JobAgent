from typing import Optional
from config.settings import settings
from packages.llm.base import LLMMessage, LLMProvider, LLMResponse


class LLMGateway:
    _instance: Optional["LLMGateway"] = None
    _provider: Optional[LLMProvider] = None

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or self._init_default_provider()

    @classmethod
    def get(cls) -> "LLMGateway":
        if cls._instance is None:
            cls._instance = LLMGateway()
        return cls._instance

    @classmethod
    def reset(cls):
        cls._instance = None

    def _init_default_provider(self) -> LLMProvider:
        # Priority order based on configured keys
        if settings.default_llm_provider == "ollama":
            try:
                from packages.llm.ollama_provider import OllamaProvider
                return OllamaProvider(base_url=settings.ollama_base_url, model="llama3")
            except Exception:
                pass
        elif settings.default_llm_provider == "mock":
            return MockLLMProvider()
        elif settings.default_llm_provider == "openai" and settings.openai_api_key:
            try:
                from packages.llm.openai_provider import OpenAIProvider
                return OpenAIProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model
                )
            except ImportError:
                pass
        elif settings.default_llm_provider == "anthropic" and settings.anthropic_api_key:
            try:
                from packages.llm.anthropic_provider import AnthropicProvider
                return AnthropicProvider(
                    api_key=settings.anthropic_api_key,
                    model=settings.anthropic_model
                )
            except ImportError:
                pass
        elif settings.default_llm_provider == "gemini" and settings.gemini_api_key:
            try:
                from packages.llm.gemini_provider import GeminiProvider
                return GeminiProvider(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model
                )
            except ImportError:
                pass

        # Fallback to whatever key is present
        if settings.openai_api_key:
            try:
                from packages.llm.openai_provider import OpenAIProvider
                return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
            except ImportError:
                pass
        elif settings.anthropic_api_key:
            try:
                from packages.llm.anthropic_provider import AnthropicProvider
                return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
            except ImportError:
                pass
        elif settings.gemini_api_key:
            try:
                from packages.llm.gemini_provider import GeminiProvider
                return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
            except ImportError:
                pass

        # Mock / Fallback provider for tests or local initialization without keys
        return MockLLMProvider()

    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        return await self.provider.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class MockLLMProvider(LLMProvider):
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[str] = None,
    ) -> LLMResponse:
        if response_format == "json":
            return LLMResponse(
                content="""{
                    "score": 88,
                    "recommendation": "APPLY",
                    "confidence": 0.95,
                    "strengths": ["Strong Unity & XR background", "Spatial computing architecture"],
                    "gaps": ["Metal shaders"],
                    "hard_requirements": ["5+ years Unity", "C#"],
                    "preferred_requirements": ["OpenCV", "VisionOS"],
                    "matched_skills": ["Unity", "C#", "XR", "AR", "VR"],
                    "missing_skills": ["Metal"],
                    "seniority_fit": "Excellent fit for Staff/Lead XR Engineer",
                    "location_fit": "Matches remote EU policy",
                    "salary_fit": "Above minimum salary target",
                    "domain_fit": "Exact match for real-time graphics & spatial computing",
                    "why_this_is_interesting": "Tier 1 XR team working on cutting-edge spatial computing interfaces.",
                    "risks": []
                }""",
                model="mock-provider",
            )
        return LLMResponse(
            content="Mock response from LLM provider.",
            model="mock-provider",
        )
