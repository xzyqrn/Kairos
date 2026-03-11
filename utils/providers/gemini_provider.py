"""
utils/providers/gemini_provider.py — Google Gemini provider backend.
"""

from __future__ import annotations

import asyncio

from utils.providers.base import AIProvider


class GeminiProvider(AIProvider):
    """Generate responses using the Google Gemini generative AI API."""

    # Since google-generativeai uses a global `genai.configure`, we must use a
    # lock to prevent multiple concurrent requests from overlapping and
    # using the wrong API key.
    _lock = asyncio.Lock()

    async def generate(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        prompt: str,
    ) -> str:
        """
        Generate a response using the Google Gemini API.

        Uses ``generate_content_async`` when available, falling back to
        ``asyncio.to_thread`` for older SDK versions that lack the async method.

        Args:
            api_key: Google AI API key.
            model: Gemini model identifier (e.g. "gemini-2.0-flash").
            system_prompt: System instruction string passed as ``system_instruction``.
            prompt: User message content.

        Returns:
            The text content of the first non-empty candidate part.

        Raises:
            RuntimeError: If the google-generativeai package is not installed,
                or if Gemini returns an empty response.
        """
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError("google-generativeai package is not installed") from exc

        async with self._lock:
            genai.configure(api_key=api_key)
            model_client = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)
            response: object

            if hasattr(model_client, "generate_content_async"):
                response = await model_client.generate_content_async(prompt)
            else:
                response = await asyncio.to_thread(lambda: model_client.generate_content(prompt))

        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        candidates = getattr(response, "candidates", []) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", []) if content else []
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    return part_text.strip()

        raise RuntimeError("Gemini returned an empty response")
