"""
utils/locale.py — Thin locale loader for Kairos.

Loads a JSON file from the ``locales/`` directory and exposes helpers to
fetch strings and format prompt templates.

Usage::

    from utils.locale import locale

    mood_options = locale.moods()
    embed_title  = locale.ui("howareyou_embed_title")
    prompt       = locale.prompt("howareyou", mood_context="the user is anxious")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("kairos.locale")

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES_DIR = _ROOT / "locales"


class Locale:
    """Lightweight wrapper around a single JSON locale file."""

    def __init__(self, lang: str = "en") -> None:
        self._lang = lang
        self._data: dict[str, Any] = {}
        self._load()

    # ── Loading ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        path = _LOCALES_DIR / f"{self._lang}.json"
        if not path.exists():
            log.error("Locale file not found: %s — falling back to empty strings", path)
            return
        try:
            with open(path, encoding="utf-8") as fh:
                self._data = json.load(fh)
            log.info("Loaded locale: %s (%d top-level keys)", self._lang, len(self._data))
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON in locale file %s: %s", path, exc)

    def reload(self, lang: str | None = None) -> None:
        """Hot-reload the locale data, optionally switching language."""
        if lang:
            self._lang = lang
        self._load()

    # ── Accessors ──────────────────────────────────────────────────────────────

    def moods(self) -> list[dict[str, str]]:
        """Return the list of mood dicts [{emoji, label, context}, ...]."""
        return list(self._data.get("moods", []))

    def ui(self, key: str, **kwargs: Any) -> str:
        """
        Return a UI string by key, formatting any keyword args.

        Example::

            locale.ui("lang_success", language="Filipino")
        """
        template: str = self._data.get("ui", {}).get(key, "")
        if not template:
            log.warning("Missing UI locale key: %s", key)
            return key  # return the key itself as a fallback
        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError as exc:
                log.warning("UI locale key '%s' missing format var %s", key, exc)
        return template

    def prompt(self, key: str, **kwargs: Any) -> str:
        """
        Return a prompt template by key, formatting any keyword args.

        Example::

            locale.prompt("howareyou", mood_context="the user is anxious")
        """
        template: str = self._data.get("prompts", {}).get(key, "")
        if not template:
            log.warning("Missing prompt locale key: %s", key)
            return ""
        if kwargs:
            try:
                return template.format(**kwargs)
            except KeyError as exc:
                log.warning("Prompt locale key '%s' missing format var %s", key, exc)
        return template

    def help_meta(self, key: str) -> str:
        """
        Return a top-level string from the ``help`` section.

        Example::

            locale.help_meta("embed_title")   # "📖 Kairos — Command Reference"
        """
        value: str = self._data.get("help", {}).get(key, "")
        if not value:
            log.warning("Missing help locale key: %s", key)
        return value

    def help_fields(self) -> list[dict[str, str]]:
        """
        Return the list of embed field dicts for the /help command.

        Each dict has "name" and "value" keys.
        """
        return list(self._data.get("help", {}).get("fields", []))


# ── Singleton ─────────────────────────────────────────────────────────────────

locale = Locale("en")
