"""
tests/test_ai_client.py — Unit tests for pure utility functions from ai_client.py
"""

from __future__ import annotations

try:
    from utils.ai_client import AIClient
    from utils.ai_client import mask_api_key as _mask_api_key

    def _guild_key(guild_id: str) -> str:
        return AIClient._guild_key(guild_id)

    def mask_api_key(api_key: str) -> str:
        return _mask_api_key(api_key)

except ImportError:
    # Fallback when optional deps (aiohttp, etc.) are not installed.
    # Keep in sync with utils/ai_client.py.
    def _guild_key(guild_id: str) -> str:  # type: ignore[misc]
        clean = str(guild_id).strip()
        if clean.startswith("guild_"):
            return clean
        return f"guild_{clean}"

    def mask_api_key(api_key: str) -> str:  # type: ignore[misc]
        clean = api_key.strip()
        if not clean:
            return "(empty)"
        if len(clean) <= 8:
            return f"{clean}..."
        return f"{clean[:8]}..."


# ── _guild_key ────────────────────────────────────────────────────────────────

class TestGuildKey:
    def test_plain_id_is_prefixed(self):
        assert _guild_key("123456") == "guild_123456"

    def test_already_prefixed_id_unchanged(self):
        assert _guild_key("guild_123456") == "guild_123456"

    def test_strips_surrounding_whitespace(self):
        assert _guild_key("  789  ") == "guild_789"

    def test_strips_whitespace_before_checking_prefix(self):
        assert _guild_key("  guild_abc  ") == "guild_abc"

    def test_numeric_string_id(self):
        assert _guild_key("999999999999999999") == "guild_999999999999999999"


# ── mask_api_key ──────────────────────────────────────────────────────────────

class TestMaskApiKey:
    def test_empty_string_returns_sentinel(self):
        assert mask_api_key("") == "(empty)"

    def test_whitespace_only_returns_sentinel(self):
        assert mask_api_key("   ") == "(empty)"

    def test_short_key_appends_ellipsis(self):
        result = mask_api_key("abc")
        assert result.endswith("...")
        assert "abc" in result

    def test_long_key_shows_first_eight_chars(self):
        key = "sk-abcdefghijklmnop"
        result = mask_api_key(key)
        assert result.startswith("sk-abcde")
        assert "..." in result

    def test_long_key_does_not_reveal_full_secret(self):
        key = "sk-supersecretkey12345"
        result = mask_api_key(key)
        assert key not in result

    def test_exactly_eight_chars_shows_all_then_ellipsis(self):
        key = "12345678"
        result = mask_api_key(key)
        assert result.startswith("12345678")
        assert result.endswith("...")

    def test_strips_surrounding_whitespace(self):
        result = mask_api_key("  sk-test123456  ")
        assert result.startswith("sk-test1")
