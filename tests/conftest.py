"""
tests/conftest.py — Shared pytest fixtures for Kairos test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to an empty temporary SQLite database."""
    db = tmp_path / "history_test.db"
    return db


@pytest.fixture()
def tmp_locale_dir(tmp_path: Path) -> Path:
    """Return a locales directory populated with a minimal en.json."""
    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "en.json").write_text(
        """{
            "moods": [
                {"emoji": "😊", "label": "Happy", "context": "the user is happy"},
                {"emoji": "😢", "label": "Sad",   "context": "the user is sad"}
            ],
            "prompts": {
                "howareyou": "A Christian is reaching out because {mood_context}.",
                "mention_chat": "[Long-term channel memory:]\\n{long_term_memory}\\n\\n[Recent channel context:]\\n{recent_context}\\n\\n[Current message addressed to Kairos:]\\n{current_message}",
                "channel_memory_rollup": "[Previous long-term memory:]\\n{previous_summary}\\n\\n[Latest discussion to fold in:]\\n{recent_discussion}"
            },
            "ui": {
                "howareyou_embed_title": "💙 A Word for You",
                "lang_success": "✅ Language set to {language}.",
                "error_generic": "❌ `{error}`"
            },
            "help": {
                "embed_title": "📖 Help",
                "embed_description": "Help description.",
                "embed_footer": "Footer text.",
                "fields": [
                    {"name": "Category A", "value": "Command A description"}
                ]
            }
        }""",
        encoding="utf-8",
    )
    return tmp_path
