"""
utils/lang.py — Per-user language preference helpers.

Storage: data/lang_prefs.json  →  { "user_id": "Filipino" }
Supported values: "English" (default), "Filipino"

Usage:
    from utils.lang import get_user_lang, set_user_lang, SUPPORTED_LANGS

    lang = await get_user_lang("123456")
    await set_user_lang("123456", "Filipino")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiofiles

log = logging.getLogger("kairos.lang")

_ROOT = Path(__file__).resolve().parent.parent
_LANG_PREFS_PATH = _ROOT / "data" / "lang_prefs.json"

SUPPORTED_LANGS: list[str] = ["English", "Filipino"]


# ── I/O helpers ───────────────────────────────────────────────────────────────

async def _read_prefs() -> dict[str, str]:
    if not _LANG_PREFS_PATH.exists():
        return {}
    async with aiofiles.open(_LANG_PREFS_PATH, encoding="utf-8") as f:
        raw = (await f.read()).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        log.warning("lang_prefs.json is invalid JSON: %s", exc)
        return {}


async def _write_prefs(prefs: dict[str, str]) -> None:
    _LANG_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(_LANG_PREFS_PATH, "w", encoding="utf-8") as f:
        await f.write(json.dumps(prefs, indent=2))


# ── Public API ────────────────────────────────────────────────────────────────

async def get_user_lang(user_id: str | int) -> str:
    """
    Return the user's preferred language, defaulting to "English".
    """
    prefs = await _read_prefs()
    lang = prefs.get(str(user_id), "English")
    return lang if lang in SUPPORTED_LANGS else "English"


async def set_user_lang(user_id: str | int, language: str) -> None:
    """
    Persist the user's language preference.
    Raises ValueError if the language is not supported.
    """
    if language not in SUPPORTED_LANGS:
        raise ValueError(
            f"Unsupported language '{language}'. Choose from: {', '.join(SUPPORTED_LANGS)}"
        )
    prefs = await _read_prefs()
    prefs[str(user_id)] = language
    await _write_prefs(prefs)
    log.info("Language preference set: user=%s lang=%s", user_id, language)


async def clear_user_lang(user_id: str | int) -> None:
    """Remove the user's language preference (resets to English)."""
    prefs = await _read_prefs()
    prefs.pop(str(user_id), None)
    await _write_prefs(prefs)
