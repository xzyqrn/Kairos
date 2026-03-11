"""
utils/providers/base.py — Abstract base class for AI provider backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Abstract base class for all AI provider backends.

    Each concrete subclass encapsulates the HTTP / SDK call for a single
    provider.  Retries and config management are handled by the caller
    (AIClient).
    """

    @abstractmethod
    async def generate(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        prompt: str,
    ) -> str:
        """
        Send a prompt to the provider and return the text response.

        Args:
            api_key: The API key for this provider.
            model: The model identifier string (e.g. "claude-haiku-4-5").
            system_prompt: The system / persona instruction string.
            prompt: The user prompt to send.

        Returns:
            The provider's text response, stripped of leading/trailing whitespace.

        Raises:
            RuntimeError: If the response is empty or cannot be parsed, or if a
                required package is missing.
            aiohttp.ClientError: On network failures (caller handles retries).
            asyncio.TimeoutError: On request timeout (caller handles retries).
        """
        ...
