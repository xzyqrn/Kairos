"""
utils/providers/claude_provider.py — Anthropic Claude provider backend.
"""

from __future__ import annotations

from utils.providers.base import AIProvider

# Must match ai_client.py constant
MAX_TOKENS = 600


class ClaudeProvider(AIProvider):
    """Generate responses using the Anthropic Claude API."""

    async def generate(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        prompt: str,
    ) -> str:
        """
        Generate a response using the Anthropic Claude messages API.

        Args:
            api_key: Anthropic API key.
            model: Claude model identifier (e.g. "claude-haiku-4-5").
            system_prompt: System instruction string.
            prompt: User message content.

        Returns:
            Concatenated text from all text content blocks in the response.

        Raises:
            RuntimeError: If the anthropic package is not installed, or if
                Claude returns an empty response.
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError("anthropic package is not installed") from exc

        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        text_chunks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if getattr(block, "type", "") == "text" and isinstance(text, str) and text.strip():
                text_chunks.append(text.strip())

        if not text_chunks:
            raise RuntimeError("Claude returned an empty response")

        return "\n".join(text_chunks)
