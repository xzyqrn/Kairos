"""
utils/providers — AI provider strategy pattern.

Factory function ``get_provider`` maps a provider name string to the concrete
``AIProvider`` implementation.  Adding a new provider requires only a new
subclass file and a new case in the match statement below.

Usage::

    from utils.providers import get_provider

    provider = get_provider("claude")
    text = await provider.generate(api_key=..., model=...,
                                   system_prompt=..., prompt=...)
"""

from __future__ import annotations

from utils.providers.base import AIProvider
from utils.providers.claude_provider import ClaudeProvider
from utils.providers.gemini_provider import GeminiProvider
from utils.providers.openai_compat_provider import OpenAICompatProvider

__all__ = [
    "AIProvider",
    "ClaudeProvider",
    "GeminiProvider",
    "OpenAICompatProvider",
    "OPENAI_COMPAT_BASE_URLS",
    "get_provider",
]

OPENAI_COMPAT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def get_provider(provider_name: str) -> AIProvider:
    """
    Return the concrete AIProvider for the given provider name string.

    Args:
        provider_name: One of ``"claude"``, ``"gemini"``, ``"openai"``,
            ``"openrouter"``, or ``"groq"``.

    Returns:
        A fresh AIProvider instance for the given provider.

    Raises:
        ValueError: If *provider_name* is not a supported provider.
    """
    match provider_name:
        case "claude":
            return ClaudeProvider()
        case "gemini":
            return GeminiProvider()
        case "openai" | "openrouter" | "groq":
            return OpenAICompatProvider(
                provider_name, OPENAI_COMPAT_BASE_URLS[provider_name]
            )
        case _:
            raise ValueError(
                f"Unsupported provider: '{provider_name}'. "
                f"Supported: claude, gemini, openai, openrouter, groq"
            )
