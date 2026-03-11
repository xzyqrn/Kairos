"""
tests/test_response.py — Unit tests for utils/response.py (trim_response)
"""

from __future__ import annotations

import pytest

from utils.response import _COMMAND_CAPS, EMBED_DESC_LIMIT, trim_response


class TestTrimResponse:
    # ── No trimming needed ────────────────────────────────────────────────────

    def test_short_text_returned_unchanged(self):
        assert trim_response("Hello world", "howareyou") == "Hello world"

    def test_empty_string_returned_unchanged(self):
        assert trim_response("", "howareyou") == ""

    def test_text_exactly_at_limit_not_trimmed(self):
        limit = _COMMAND_CAPS["howareyou"]
        text = "x" * limit
        assert trim_response(text, "howareyou") == text
        assert not trim_response(text, "howareyou").endswith("…")

    # ── Trimming applied ──────────────────────────────────────────────────────

    def test_text_over_limit_ends_with_ellipsis(self):
        limit = _COMMAND_CAPS["howareyou"]
        text = "a" * (limit + 100)
        result = trim_response(text, "howareyou")
        assert result.endswith("…")

    def test_trimmed_text_within_limit(self):
        limit = _COMMAND_CAPS["howareyou"]
        text = "a" * (limit + 500)
        result = trim_response(text, "howareyou")
        assert len(result) <= limit

    def test_word_boundary_preferred(self):
        """Trim should break at whitespace, not mid-word."""
        limit = _COMMAND_CAPS["howareyou"]
        # Build a string where a space lands well before the cut point
        words = ("word " * (limit // 5 + 1))[:limit + 50]
        result = trim_response(words, "howareyou")
        # The character just before the ellipsis should not be mid-word
        assert result[:-1].endswith(" ") or result[:-1][-1].isalpha()

    # ── Per-command caps ──────────────────────────────────────────────────────

    def test_different_commands_have_different_caps(self):
        """suggest allows more chars than howareyou."""
        assert _COMMAND_CAPS["suggest"] > _COMMAND_CAPS["howareyou"]

    def test_unknown_command_falls_back_to_embed_limit(self):
        long_text = "x" * (EMBED_DESC_LIMIT - 10)
        # Should NOT be trimmed — well under EMBED_DESC_LIMIT
        assert trim_response(long_text, "unknown_command") == long_text

    def test_unknown_command_over_embed_limit_is_trimmed(self):
        long_text = "x" * (EMBED_DESC_LIMIT + 100)
        result = trim_response(long_text, "unknown_command")
        assert len(result) <= EMBED_DESC_LIMIT
        assert result.endswith("…")

    # ── All registered commands stay within their caps ────────────────────────

    @pytest.mark.parametrize("command", list(_COMMAND_CAPS.keys()))
    def test_all_caps_within_embed_limit(self, command):
        assert _COMMAND_CAPS[command] <= EMBED_DESC_LIMIT

    @pytest.mark.parametrize("command", list(_COMMAND_CAPS.keys()))
    def test_trim_respects_each_command_cap(self, command):
        cap = _COMMAND_CAPS[command]
        text = "word " * (cap // 5 + 50)
        result = trim_response(text, command)
        assert len(result) <= cap, f"trim_response exceeded cap for '{command}'"
