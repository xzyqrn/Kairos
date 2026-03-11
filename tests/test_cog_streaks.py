"""
tests/test_cog_streaks.py — Unit tests for PHT-aware streak behavior.
"""

from __future__ import annotations

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.streaks as streaks


def _make_cog() -> streaks.Streaks:
    cog = object.__new__(streaks.Streaks)
    cog.bot = MagicMock()
    cast(Any, cog)._send_milestone_dm = AsyncMock()
    return cog


class TestPhtToday:
    def test_uses_pht_calendar_day(self):
        utc_time = datetime.datetime(2026, 3, 11, 23, 30, tzinfo=datetime.UTC)

        result = streaks._pht_today(utc_time)

        assert result == datetime.date(2026, 3, 12)


class TestRecordDevotion:
    async def test_uses_pht_date_for_consecutive_day_logic(self, monkeypatch):
        cog = _make_cog()
        monkeypatch.setattr(streaks, "_pht_today", lambda now=None: datetime.date(2026, 3, 12))
        monkeypatch.setattr(
            streaks.streak_store,
            "get",
            AsyncMock(
                return_value={
                    "current_streak": 4,
                    "longest_streak": 4,
                    "total_devotions": 7,
                    "last_date": "2026-03-11",
                }
            ),
        )
        upsert = AsyncMock()
        monkeypatch.setattr(streaks.streak_store, "upsert", upsert)

        result = await streaks.Streaks.record_devotion(cog, "123")

        assert result["current_streak"] == 5
        assert result["last_date"] == "2026-03-12"
        upsert.assert_awaited_once_with(
            user_id="123",
            current_streak=5,
            longest_streak=5,
            total_devotions=8,
            last_date="2026-03-12",
        )


class TestMyStats:
    async def test_status_uses_pht_day_boundary(self, monkeypatch):
        cog = _make_cog()
        interaction = MagicMock()
        interaction.user.id = 123
        interaction.user.display_name = "Test User"
        interaction.user.display_avatar.url = "https://example.com/avatar.png"
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        monkeypatch.setattr(streaks, "_pht_today", lambda now=None: datetime.date(2026, 3, 12))
        monkeypatch.setattr(
            streaks.streak_store,
            "get",
            AsyncMock(
                return_value={
                    "current_streak": 4,
                    "longest_streak": 6,
                    "total_devotions": 10,
                    "last_date": "2026-03-11",
                }
            ),
        )

        await cast(Any, streaks.Streaks.mystats.callback)(cog, interaction)

        embed = interaction.followup.send.await_args.kwargs["embed"]
        status_field = next(field for field in embed.fields if field.name == "Status")
        assert status_field.value == "⚡ Active — do your devotion today to keep the streak!"
