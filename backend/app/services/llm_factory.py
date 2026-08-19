"""LLM client factory.

Two providers are supported and switched via LLM_PROVIDER:
  - "openai": public OpenAI (or any OpenAI-compatible base URL).
  - "azure":  Azure OpenAI gateway, typically internal (production default).

API key resolution order (per call):
  1. The contextvar `_api_key_var` if set (populated from the incoming
     request's Authorization: Bearer header in app/api/chat.py).
  2. The provider-specific env key (OPENAI_API_KEY or HCHAT_API_KEY).

Constructed clients are cached by (key, provider, streaming, temperature)
so the HTTP client is reused while still honoring per-request key overrides.
"""

from __future__ import annotations

from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


_api_key_var: ContextVar[str | None] = ContextVar("llm_api_key", default=None)


def set_api_key(key: str | None) -> None:
    """Set the LLM API key for the current async context.

    Pass None to clear (subsequent calls fall back to the active provider's
    env key).
    """
    _api_key_var.set(key or None)


def resolve_api_key() -> str:
    override = _api_key_var.get()
    if override:
        return override
    return get_settings().active_api_key


@lru_cache(maxsize=8)
def _build(
    api_key: str,
    provider: str,
    *,
    streaming: bool,
    temperature: float,
) -> BaseChatModel:
    s = get_settings()
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = dict(
            api_key=api_key,
            model=s.openai_model,
            streaming=streaming,
            temperature=temperature,
        )
        if s.openai_base_url.strip():
            kwargs["base_url"] = s.openai_base_url.strip()
        return ChatOpenAI(**kwargs)

    # azure (internal corporate gateway)
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=s.hchat_endpoint,
        azure_deployment=s.hchat_deployment,
        api_version=s.hchat_api_version,
        api_key=api_key,
        streaming=streaming,
        temperature=temperature,
    )


def get_judge_llm() -> BaseChatModel:
    """Non-streaming, T=0 LLM for routing/analysis/JSON nodes."""
    s = get_settings()
    return _build(resolve_api_key(), s.llm_provider, streaming=False, temperature=0.0)


def get_generator_llm() -> BaseChatModel:
    """Streaming LLM for the final answer node."""
    s = get_settings()
    return _build(resolve_api_key(), s.llm_provider, streaming=True, temperature=0.3)
