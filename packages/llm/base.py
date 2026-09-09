from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str # system, user, assistant
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: Dict[str, Any] = {}


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[str] = None, # "json" or None
    ) -> LLMResponse:
        pass
