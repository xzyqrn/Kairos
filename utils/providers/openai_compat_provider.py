"""
utils/providers/openai_compat_provider.py — OpenAI-compatible endpoint provider.

Handles OpenAI, OpenRouter, and Groq — all of which expose the same
/chat/completions API shape.
"""

from __future__ import annotations

import aiohttp

from utils.providers.base import AIProvider

# Must match ai_client.py constant
MAX_TOKENS = 600


class OpenAICompatProvider(AIProvider):
    """Generate responses using any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, provider_name: str, base_url: str) -> None:
        """
        Create a provider for any OpenAI-compatible endpoint.

        Args:
            provider_name: Used to determine custom headers
                (e.g. ``"openrouter"`` adds HTTP-Referer / X-Title headers).
            base_url: The base URL for the API (without trailing slash).
        """
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=60)

    async def generate(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        prompt: str,
    ) -> str:
        """
        Generate a response using an OpenAI-compatible chat completions endpoint.

        Args:
            api_key: Bearer token for the provider.
            model: Model identifier string.
            system_prompt: System message content.
            prompt: User message content.

        Returns:
            The text content of the first choice's message.

        Raises:
            RuntimeError: On HTTP 4xx/5xx, empty choices, or unparseable content.
            aiohttp.ClientError: On network-level failures (caller handles retries).
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self._provider_name == "openrouter":
            headers["HTTP-Referer"] = "https://discord.com"
            headers["X-Title"] = "Kairos Bot"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": MAX_TOKENS,
        }

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status >= 400:
                    error_body = (await response.text())[:400]
                    raise RuntimeError(f"HTTP {response.status}: {error_body}")

                data = await response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("No choices returned from provider")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if isinstance(content, str):
            if not content.strip():
                raise RuntimeError("Provider returned an empty message")
            return content.strip()

        if isinstance(content, list):
            text_parts = [
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = "\n".join(part for part in text_parts if part)
            if text:
                return text

        raise RuntimeError("Unable to parse provider response content")
