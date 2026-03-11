"""
utils/bible_api.py — Fetch Bible verses from scripture.api.bible with a hardcoded fallback.

Primary:  scripture.api.bible  (BIBLE_API_KEY + BIBLE_ID from .env)
Fallback: 8 KJV verses cycling by date ordinal

Usage:
    from utils.bible_api import fetch_verse

    text = await fetch_verse("John 3:16")      # named passage
    text = await fetch_verse()                  # today's verse (fallback list)
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import NamedTuple

import aiohttp

log = logging.getLogger("kairos.bible_api")

# ── Config ─────────────────────────────────────────────────────────────────────
_API_BASE = "https://api.scripture.api.bible/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# ── Hardcoded fallback verses (KJV) ───────────────────────────────────────────
_FALLBACK_VERSES: list[dict[str, str]] = [
    {
        "reference": "John 3:16",
        "text": (
            "For God so loved the world, that he gave his only begotten Son, "
            "that whosoever believeth in him should not perish, but have everlasting life."
        ),
    },
    {
        "reference": "Psalm 23:1",
        "text": "The LORD is my shepherd; I shall not want.",
    },
    {
        "reference": "Proverbs 3:5-6",
        "text": (
            "Trust in the LORD with all thine heart; and lean not unto thine own understanding. "
            "In all thy ways acknowledge him, and he shall direct thy paths."
        ),
    },
    {
        "reference": "Philippians 4:13",
        "text": "I can do all things through Christ which strengtheneth me.",
    },
    {
        "reference": "Romans 8:28",
        "text": (
            "And we know that all things work together for good to them that love God, "
            "to them who are the called according to his purpose."
        ),
    },
    {
        "reference": "Isaiah 40:31",
        "text": (
            "But they that wait upon the LORD shall renew their strength; they shall mount up "
            "with wings as eagles; they shall run, and not be weary; and they shall walk, and not faint."
        ),
    },
    {
        "reference": "Jeremiah 29:11",
        "text": (
            "For I know the thoughts that I think toward you, saith the LORD, thoughts of peace, "
            "and not of evil, to give you an expected end."
        ),
    },
    {
        "reference": "Matthew 11:28",
        "text": (
            "Come unto me, all ye that labour and are heavy laden, and I will give you rest."
        ),
    },
]


class BibleVerse(NamedTuple):
    reference: str
    text: str
    source: str  # "api" or "fallback"


def _daily_fallback() -> BibleVerse:
    """Cycle through the 8 fallback verses by date ordinal."""
    index = datetime.date.today().toordinal() % len(_FALLBACK_VERSES)
    entry = _FALLBACK_VERSES[index]
    return BibleVerse(reference=entry["reference"], text=entry["text"], source="fallback")


async def fetch_verse(passage: str | None = None) -> BibleVerse:
    """
    Fetch a verse by passage name, or today's verse if passage is None.

    Always tries scripture.api.bible first; falls back to local list on any error.

    Args:
        passage: e.g. "John 3:16", "Psalm 23", "Romans 8:28"

    Returns:
        BibleVerse(reference, text, source)
    """
    api_key = os.getenv("BIBLE_API_KEY", "").strip()
    bible_id = os.getenv("BIBLE_ID", "de4e12af7f28f599-02").strip()

    if not passage:
        # No specific passage → today's fallback verse (no API call needed)
        return _daily_fallback()

    if not api_key:
        log.warning("BIBLE_API_KEY not set — using fallback verse.")
        return _daily_fallback()

    search_url = f"{_API_BASE}/bibles/{bible_id}/search"
    headers = {"api-key": api_key}
    params = {"query": passage, "limit": 1}

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(search_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    log.warning("Bible API returned HTTP %s for '%s': %s", resp.status, passage, body)
                    return _daily_fallback()

                data = await resp.json()

        passages_list = data.get("data", {}).get("passages", [])
        verses_list = data.get("data", {}).get("verses", [])

        # Prefer passages > verses
        if passages_list:
            item = passages_list[0]
            raw_text = _strip_html(str(item.get("content", item.get("text", ""))))
            reference = str(item.get("reference", passage))
        elif verses_list:
            item = verses_list[0]
            raw_text = _strip_html(str(item.get("text", "")))
            reference = str(item.get("reference", passage))
        else:
            log.info("Bible API found no results for '%s', using fallback.", passage)
            return _daily_fallback()

        if not raw_text.strip():
            return _daily_fallback()

        return BibleVerse(reference=reference, text=raw_text.strip(), source="api")

    except Exception as exc:
        log.warning("Bible API error for '%s': %s — using fallback.", passage, exc)
        return _daily_fallback()


def _strip_html(text: str) -> str:
    """Remove simple HTML tags from API response text."""
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def get_fallback_verse(index: int | None = None) -> BibleVerse:
    """Return a specific fallback verse by index, or today's by ordinal."""
    if index is not None:
        entry = _FALLBACK_VERSES[index % len(_FALLBACK_VERSES)]
    else:
        entry = _FALLBACK_VERSES[datetime.date.today().toordinal() % len(_FALLBACK_VERSES)]
    return BibleVerse(reference=entry["reference"], text=entry["text"], source="fallback")
