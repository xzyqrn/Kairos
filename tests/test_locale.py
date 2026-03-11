"""
tests/test_locale.py — Unit tests for utils/locale.py
"""

from __future__ import annotations

import json
from pathlib import Path

from utils.locale import Locale

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_locale(tmp_path: Path, data: dict) -> Locale:
    """Create a Locale instance backed by *data* in a temp directory."""
    locales = tmp_path / "locales"
    locales.mkdir(exist_ok=True)
    (locales / "en.json").write_text(json.dumps(data), encoding="utf-8")

    loc = Locale.__new__(Locale)
    loc._lang = "en"
    loc._data = {}
    # Monkeypatch the locales dir
    import utils.locale as locale_module
    original = locale_module._LOCALES_DIR
    locale_module._LOCALES_DIR = locales
    try:
        loc._load()
    finally:
        locale_module._LOCALES_DIR = original
    return loc


# ── moods() ───────────────────────────────────────────────────────────────────

class TestMoods:
    def test_returns_list(self, tmp_path):
        loc = make_locale(tmp_path, {
            "moods": [
                {"emoji": "😊", "label": "Happy", "context": "happy"},
                {"emoji": "😢", "label": "Sad",   "context": "sad"},
            ]
        })
        assert len(loc.moods()) == 2

    def test_mood_has_required_keys(self, tmp_path):
        loc = make_locale(tmp_path, {
            "moods": [{"emoji": "😊", "label": "Happy", "context": "happy"}]
        })
        mood = loc.moods()[0]
        assert "emoji" in mood
        assert "label" in mood
        assert "context" in mood

    def test_empty_moods_returns_empty_list(self, tmp_path):
        loc = make_locale(tmp_path, {})
        assert loc.moods() == []

    def test_moods_is_copy(self, tmp_path):
        """Mutating the returned list should not affect the internal data."""
        loc = make_locale(tmp_path, {
            "moods": [{"emoji": "😊", "label": "Happy", "context": "happy"}]
        })
        result = loc.moods()
        result.clear()
        assert len(loc.moods()) == 1


# ── prompt() ──────────────────────────────────────────────────────────────────

class TestPrompt:
    def test_returns_formatted_string(self, tmp_path):
        loc = make_locale(tmp_path, {
            "prompts": {"howareyou": "Responding because {mood_context}."}
        })
        result = loc.prompt("howareyou", mood_context="anxious")
        assert result == "Responding because anxious."

    def test_missing_key_returns_empty_string(self, tmp_path):
        loc = make_locale(tmp_path, {"prompts": {}})
        assert loc.prompt("nonexistent") == ""

    def test_missing_format_var_returns_raw_template(self, tmp_path):
        loc = make_locale(tmp_path, {
            "prompts": {"test": "Hello {name}!"}
        })
        # Missing 'name' kwarg — should return raw template without crashing
        result = loc.prompt("test")
        assert result == "Hello {name}!"

    def test_no_substitution_when_no_kwargs(self, tmp_path):
        loc = make_locale(tmp_path, {
            "prompts": {"plain": "No substitution here."}
        })
        assert loc.prompt("plain") == "No substitution here."


# ── ui() ──────────────────────────────────────────────────────────────────────

class TestUI:
    def test_returns_string(self, tmp_path):
        loc = make_locale(tmp_path, {"ui": {"key": "Hello!"}})
        assert loc.ui("key") == "Hello!"

    def test_formats_kwargs(self, tmp_path):
        loc = make_locale(tmp_path, {"ui": {"greeting": "Hello, {name}!"}})
        assert loc.ui("greeting", name="Jay") == "Hello, Jay!"

    def test_missing_key_returns_key_itself(self, tmp_path):
        loc = make_locale(tmp_path, {"ui": {}})
        # Falls back to returning the key so UI doesn't silently show blank
        assert loc.ui("missing_key") == "missing_key"


# ── help_meta() & help_fields() ───────────────────────────────────────────────

class TestHelp:
    def _loc(self, tmp_path):
        return make_locale(tmp_path, {
            "help": {
                "embed_title": "📖 Help",
                "embed_footer": "Footer.",
                "fields": [
                    {"name": "Cat A", "value": "Cmd A"},
                    {"name": "Cat B", "value": "Cmd B"},
                ]
            }
        })

    def test_help_meta_title(self, tmp_path):
        assert self._loc(tmp_path).help_meta("embed_title") == "📖 Help"

    def test_help_meta_missing_returns_empty(self, tmp_path):
        loc = make_locale(tmp_path, {"help": {}})
        assert loc.help_meta("nonexistent") == ""

    def test_help_fields_count(self, tmp_path):
        assert len(self._loc(tmp_path).help_fields()) == 2

    def test_help_fields_keys(self, tmp_path):
        field = self._loc(tmp_path).help_fields()[0]
        assert "name" in field
        assert "value" in field

    def test_help_fields_empty_when_missing(self, tmp_path):
        loc = make_locale(tmp_path, {})
        assert loc.help_fields() == []


# ── Production locale smoke-test ──────────────────────────────────────────────

class TestProductionLocale:
    """Smoke-tests against the real locales/en.json to catch regressions."""

    def test_moods_count(self):
        from utils.locale import locale
        assert len(locale.moods()) == 6

    def test_all_moods_have_required_keys(self):
        from utils.locale import locale
        for mood in locale.moods():
            assert "emoji" in mood, f"Missing emoji in {mood}"
            assert "label" in mood, f"Missing label in {mood}"
            assert "context" in mood, f"Missing context in {mood}"

    def test_all_prompts_nonempty(self):
        from utils.locale import locale
        for key in ("howareyou", "suggest", "advice", "verse", "devotion", "pray"):
            assert locale.prompt(key), f"Prompt '{key}' is empty in production locale"

    def test_help_fields_count(self):
        from utils.locale import locale
        assert len(locale.help_fields()) == 8

    def test_help_meta_title_nonempty(self):
        from utils.locale import locale
        assert locale.help_meta("embed_title")

    def test_ui_error_generic_formats(self):
        from utils.locale import locale
        result = locale.ui("error_generic", error="something went wrong")
        assert "something went wrong" in result
