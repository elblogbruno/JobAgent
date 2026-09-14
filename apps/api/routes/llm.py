import os
import time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config.settings import settings
from packages.llm.base import LLMMessage
from packages.llm.gateway import LLMGateway

router = APIRouter(prefix="/api/llm", tags=["LLM Configuration"])


def mask_key(key: Optional[str]) -> str:
    if not key or len(key) < 8:
        return ""
    return f"{key[:4]}...{key[-4:]}"


class LLMConfigPayload(BaseModel):
    provider: str
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class LLMTestPayload(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


@router.get("/config")
async def get_llm_config():
    return {
        "active_provider": settings.default_llm_provider,
        "openai": {
            "is_configured": bool(settings.openai_api_key),
            "key_masked": mask_key(settings.openai_api_key),
            "model": settings.openai_model,
        },
        "anthropic": {
            "is_configured": bool(settings.anthropic_api_key),
            "key_masked": mask_key(settings.anthropic_api_key),
            "model": settings.anthropic_model,
        },
        "gemini": {
            "is_configured": bool(settings.gemini_api_key),
            "key_masked": mask_key(settings.gemini_api_key),
            "model": settings.gemini_model,
        },
        "ollama": {
            "base_url": settings.ollama_base_url,
            "model": "llama3",
        },
        "available_providers": ["openai", "anthropic", "gemini", "ollama", "mock"],
    }


def update_env_file(key_values: dict):
    env_path = Path(".env")
    if not env_path.exists():
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found_keys = set()

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in key_values:
                new_lines.append(f"{k}={key_values[k]}")
                found_keys.add(k)
                continue
        new_lines.append(line)

    for k, v in key_values.items():
        if k not in found_keys:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.put("/config")
async def update_llm_config(payload: LLMConfigPayload):
    try:
        env_updates = {}
        if payload.provider:
            settings.default_llm_provider = payload.provider
            env_updates["DEFAULT_LLM_PROVIDER"] = payload.provider

        if payload.openai_api_key is not None:
            settings.openai_api_key = payload.openai_api_key
            env_updates["OPENAI_API_KEY"] = payload.openai_api_key
        if payload.openai_model:
            settings.openai_model = payload.openai_model
            env_updates["OPENAI_MODEL"] = payload.openai_model

        if payload.anthropic_api_key is not None:
            settings.anthropic_api_key = payload.anthropic_api_key
            env_updates["ANTHROPIC_API_KEY"] = payload.anthropic_api_key
        if payload.anthropic_model:
            settings.anthropic_model = payload.anthropic_model
            env_updates["ANTHROPIC_MODEL"] = payload.anthropic_model

        if payload.gemini_api_key is not None:
            settings.gemini_api_key = payload.gemini_api_key
            env_updates["GEMINI_API_KEY"] = payload.gemini_api_key
        if payload.gemini_model:
            settings.gemini_model = payload.gemini_model
            env_updates["GEMINI_MODEL"] = payload.gemini_model

        if payload.ollama_base_url:
            settings.ollama_base_url = payload.ollama_base_url
            env_updates["OLLAMA_BASE_URL"] = payload.ollama_base_url

        update_env_file(env_updates)
        LLMGateway.reset()

        return {
            "status": "success",
            "message": f"LLM configurado exitosamente como '{payload.provider}'.",
            "active_provider": settings.default_llm_provider,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test")
async def test_llm_connection(payload: LLMTestPayload):
    provider_name = payload.provider.lower()
    start_time = time.time()

    try:
        provider = None
        if provider_name == "openai":
            from packages.llm.openai_provider import OpenAIProvider
            key = payload.api_key or settings.openai_api_key
            if not key:
                raise ValueError("No se proporcionó API Key para OpenAI.")
            provider = OpenAIProvider(api_key=key, model=payload.model or settings.openai_model)

        elif provider_name == "anthropic":
            from packages.llm.anthropic_provider import AnthropicProvider
            key = payload.api_key or settings.anthropic_api_key
            if not key:
                raise ValueError("No se proporcionó API Key para Anthropic.")
            provider = AnthropicProvider(api_key=key, model=payload.model or settings.anthropic_model)

        elif provider_name == "gemini":
            from packages.llm.gemini_provider import GeminiProvider
            key = payload.api_key or settings.gemini_api_key
            if not key:
                raise ValueError("No se proporcionó API Key para Gemini.")
            provider = GeminiProvider(api_key=key, model=payload.model or settings.gemini_model)

        elif provider_name == "ollama":
            from packages.llm.ollama_provider import OllamaProvider
            base_url = payload.base_url or settings.ollama_base_url
            provider = OllamaProvider(base_url=base_url, model=payload.model or "llama3")

        elif provider_name == "mock":
            from packages.llm.gateway import MockLLMProvider
            provider = MockLLMProvider()

        else:
            raise ValueError(f"Proveedor '{provider_name}' no soportado.")

        # Execute test ping
        messages = [
            LLMMessage(role="user", content="Responde únicamente la palabra 'CONECTADO'.")
        ]
        resp = await provider.generate(messages, max_tokens=15)
        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "provider": provider_name,
            "model": resp.model,
            "latency_ms": elapsed_ms,
            "response": resp.content.strip()[:100],
            "message": f"Conexión exitosa con {provider_name} ({elapsed_ms}ms)",
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "provider": provider_name,
            "latency_ms": elapsed_ms,
            "error": str(e),
            "message": f"Fallo al conectar con {provider_name}: {str(e)}",
        }
