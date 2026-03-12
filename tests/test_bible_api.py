"""
tests/test_bible_api.py — Unit tests for utils/bible_api.py.
"""

from __future__ import annotations

import datetime

import pytest

import utils.bible_api as bible_api
from utils.bible_api import BibleVerse


class TestFetchDailyVerse:
    async def test_uses_api_for_curated_reference_when_configured(self, monkeypatch):
        requested: list[str] = []
        target_date = datetime.date(2026, 3, 11)
        fallback = bible_api.get_fallback_verse(on_date=target_date)

        async def fake_fetch(passage: str, *, api_key: str, bible_id: str) -> BibleVerse | None:
            requested.append(passage)
            assert api_key == "secret"
            assert bible_id == "bible-id"
            return BibleVerse(reference=passage, text="API text", source="api")

        monkeypatch.setenv("BIBLE_API_KEY", "secret")
        monkeypatch.setenv("BIBLE_ID", "bible-id")
        monkeypatch.setattr(bible_api, "_fetch_api_verse", fake_fetch)

        result = await bible_api.fetch_daily_verse(on_date=target_date)

        assert requested == [fallback.reference]
        assert result == BibleVerse(reference=fallback.reference, text="API text", source="api")

    async def test_falls_back_without_api_key(self, monkeypatch):
        target_date = datetime.date(2026, 3, 11)
        fallback = bible_api.get_fallback_verse(on_date=target_date)

        async def should_not_run(*args, **kwargs):
            raise AssertionError("_fetch_api_verse should not be called without an API key")

        monkeypatch.delenv("BIBLE_API_KEY", raising=False)
        monkeypatch.setattr(bible_api, "_fetch_api_verse", should_not_run)

        result = await bible_api.fetch_daily_verse(on_date=target_date)

        assert result == fallback

    async def test_raises_when_api_returns_none_with_api_key(self, monkeypatch):
        target_date = datetime.date(2026, 3, 11)

        async def fake_fetch(*args, **kwargs) -> BibleVerse | None:
            return None

        monkeypatch.setenv("BIBLE_API_KEY", "secret")
        monkeypatch.setattr(bible_api, "_fetch_api_verse", fake_fetch)

        with pytest.raises(RuntimeError, match="Configured daily verse lookup failed"):
            await bible_api.fetch_daily_verse(on_date=target_date)


class TestFetchVerse:
    async def test_specific_passage_returns_none_without_api_key(self, monkeypatch):
        monkeypatch.delenv("BIBLE_API_KEY", raising=False)

        result = await bible_api.fetch_verse("Romans 12:2")

        assert result is None

    async def test_specific_passage_returns_none_when_api_returns_none(self, monkeypatch):
        async def fake_fetch(*args, **kwargs) -> BibleVerse | None:
            return None

        monkeypatch.setenv("BIBLE_API_KEY", "secret")
        monkeypatch.setattr(bible_api, "_fetch_api_verse", fake_fetch)

        result = await bible_api.fetch_verse("Romans 12:2")

        assert result is None

    async def test_no_passage_keeps_daily_fallback_behavior(self, monkeypatch):
        fallback = BibleVerse(reference="Psalm 23:1", text="The LORD is my shepherd; I shall not want.", source="fallback")

        monkeypatch.setattr(bible_api, "_daily_fallback", lambda on_date=None: fallback)

        result = await bible_api.fetch_verse()

        assert result == fallback


class TestPhtDateHandling:
    def test_pht_today_uses_pht_calendar_day(self):
        utc_time = datetime.datetime(2026, 3, 11, 23, 30, tzinfo=datetime.UTC)

        result = bible_api._pht_today(utc_time)

        assert result == datetime.date(2026, 3, 12)
