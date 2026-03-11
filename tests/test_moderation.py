"""
tests/test_moderation.py — Unit tests for cogs/moderation.py helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("discord")
import cogs.moderation as moderation


class TestContainsBlockedWord:
    def test_matches_exact_word(self):
        assert moderation._contains_blocked_word("please stop", ["stop"]) == "stop"

    def test_matches_word_with_punctuation(self):
        assert moderation._contains_blocked_word("stop!", ["stop"]) == "stop"

    def test_does_not_match_substring_inside_longer_word(self):
        assert moderation._contains_blocked_word("unstoppable", ["stop"]) is None

    def test_empty_word_entries_are_ignored(self):
        assert moderation._contains_blocked_word("clean text", ["", "   "]) is None

    def test_returns_first_match_found(self):
        result = moderation._contains_blocked_word("alpha beta", ["beta", "alpha"])
        assert result == "beta"


class TestLoadBlocklist:
    async def test_missing_file_returns_defaults(self, tmp_path: Path, monkeypatch):
        missing = tmp_path / "missing_blocklist.json"
        monkeypatch.setattr(moderation, "_BLOCKLIST_PATH", missing)
        monkeypatch.setattr(moderation, "_DEFAULT_BLOCKLIST", ["default_word"])

        words = await moderation._load_blocklist()
        assert set(words) == {"default_word"}

    async def test_loads_and_normalizes_custom_words(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "blocklist.json"
        path.write_text(json.dumps({"words": [" bad ", "word", "BAD"]}), encoding="utf-8")
        monkeypatch.setattr(moderation, "_BLOCKLIST_PATH", path)
        monkeypatch.setattr(moderation, "_DEFAULT_BLOCKLIST", ["base"])

        words = await moderation._load_blocklist()
        assert set(words) == {"base", "bad", "word"}

    async def test_invalid_json_falls_back_to_defaults(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "blocklist.json"
        path.write_text("{not-json", encoding="utf-8")
        monkeypatch.setattr(moderation, "_BLOCKLIST_PATH", path)
        monkeypatch.setattr(moderation, "_DEFAULT_BLOCKLIST", ["base"])

        words = await moderation._load_blocklist()
        assert set(words) == {"base"}
