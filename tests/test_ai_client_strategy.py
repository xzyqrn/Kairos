"""
tests/test_ai_client_strategy.py — Unit tests for the provider strategy pattern
and AIClient retry logic.

Covers:
  - get_provider() factory (correct types returned, ValueError for unknown)
  - AIClient._with_retry() backoff behaviour
  - AIClient.generate_response() provider dispatch
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from utils.providers import (
    OPENAI_COMPAT_BASE_URLS,
    ClaudeProvider,
    GeminiProvider,
    OpenAICompatProvider,
    get_provider,
)
from utils.providers.base import AIProvider

# ── TestGetProvider ───────────────────────────────────────────────────────────

class TestGetProvider:
    def test_claude_returns_claude_provider(self):
        p = get_provider("claude")
        assert isinstance(p, ClaudeProvider)

    def test_gemini_returns_gemini_provider(self):
        p = get_provider("gemini")
        assert isinstance(p, GeminiProvider)

    def test_openai_returns_openai_compat_provider(self):
        p = get_provider("openai")
        assert isinstance(p, OpenAICompatProvider)

    def test_openrouter_returns_openai_compat_provider(self):
        p = get_provider("openrouter")
        assert isinstance(p, OpenAICompatProvider)

    def test_groq_returns_openai_compat_provider(self):
        p = get_provider("groq")
        assert isinstance(p, OpenAICompatProvider)

    def test_all_providers_are_aiprovider_subclass(self):
        for name in ("claude", "gemini", "openai", "openrouter", "groq"):
            assert isinstance(get_provider(name), AIProvider)

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            get_provider("unknown_ai")

    def test_openai_compat_base_urls_has_expected_keys(self):
        assert set(OPENAI_COMPAT_BASE_URLS.keys()) == {"openai", "openrouter", "groq"}


# ── TestWithRetry ─────────────────────────────────────────────────────────────

class TestWithRetry:
    """Tests for AIClient._with_retry() using a minimal mock coroutine."""

    async def test_succeeds_on_first_attempt(self):
        fn = AsyncMock(return_value="hello")
        from utils.ai_client import AIClient
        result = await AIClient._with_retry(fn)
        assert result == "hello"
        fn.assert_called_once()

    async def test_retries_on_aiohttp_error(self):
        import aiohttp

        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise aiohttp.ClientError("connection refused")
            return "ok"

        with patch("asyncio.sleep", new=AsyncMock()):
            from utils.ai_client import AIClient
            result = await AIClient._with_retry(flaky_fn)

        assert result == "ok"
        assert call_count == 3

    async def test_non_transient_runtime_error_not_retried(self):
        call_count = 0

        async def bad_fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Invalid API key")

        from utils.ai_client import AIClient
        with pytest.raises(RuntimeError, match="Invalid API key"):
            await AIClient._with_retry(bad_fn)

        assert call_count == 1  # no retry for non-transient errors

    async def test_transient_runtime_error_is_retried(self):

        call_count = 0

        async def overloaded_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("503 overloaded")
            return "recovered"

        with patch("asyncio.sleep", new=AsyncMock()):
            from utils.ai_client import AIClient
            result = await AIClient._with_retry(overloaded_fn)

        assert result == "recovered"
        assert call_count == 2

    async def test_exhausted_retries_raises_last_exception(self):
        import aiohttp

        async def always_fail():
            raise aiohttp.ClientError("persistent failure")

        with patch("asyncio.sleep", new=AsyncMock()):
            from utils.ai_client import AIClient
            with pytest.raises(aiohttp.ClientError):
                await AIClient._with_retry(always_fail)
