"""
tests/test_cog_scheduler.py — Unit tests for manual daily verse posting responses.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.scheduler as scheduler


def _make_cog() -> scheduler.Scheduler:
    cog = object.__new__(scheduler.Scheduler)
    cog.bot = cast(Any, SimpleNamespace(guilds=[]))
    return cog


def _make_interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = 999
    interaction.guild = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestSendDailyVerse:
    async def test_success_response(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(cog, "_post_daily_verse", AsyncMock(return_value="sent"))

        await cast(Any, scheduler.Scheduler.send_daily_verse.callback)(cog, interaction)

        interaction.followup.send.assert_awaited_once_with(
            "✅ Today's daily verse has been posted.",
            ephemeral=True,
        )

    async def test_missing_channel_response(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(cog, "_post_daily_verse", AsyncMock(return_value="missing_channel"))
        monkeypatch.setenv("DAILY_VERSE_CHANNEL", "daily-verse")

        await cast(Any, scheduler.Scheduler.send_daily_verse.callback)(cog, interaction)

        interaction.followup.send.assert_awaited_once_with(
            "❌ I couldn't post because this server doesn't have a #daily-verse channel yet.",
            ephemeral=True,
        )

    async def test_send_failure_response(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(cog, "_post_daily_verse", AsyncMock(return_value="send_failed"))

        await cast(Any, scheduler.Scheduler.send_daily_verse.callback)(cog, interaction)

        interaction.followup.send.assert_awaited_once_with(
            "❌ I couldn't post today's verse. Please check my channel permissions and try again.",
            ephemeral=True,
        )


class TestDailyVerseTimeCommand:
    async def test_shows_current_time_when_hour_is_omitted(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(scheduler.scheduler_store, "get_daily_time", AsyncMock(return_value=(7, 0)))

        await cast(Any, scheduler.Scheduler.daily_verse_time.callback)(cog, interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "🕒 Daily verse posts are currently set for **07:00 PHT** in this server.",
            ephemeral=True,
        )

    async def test_sets_time_for_server(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        set_daily_time = AsyncMock(return_value="09:30")
        monkeypatch.setattr(scheduler.scheduler_store, "set_daily_time", set_daily_time)

        await cast(Any, scheduler.Scheduler.daily_verse_time.callback)(cog, interaction, 9, 30)

        set_daily_time.assert_awaited_once_with("999", 9, 30)
        interaction.response.send_message.assert_awaited_once_with(
            "✅ Daily verse posts will now go out at **09:30 PHT** in this server.",
            ephemeral=True,
        )

    async def test_rejects_invalid_time(self):
        interaction = _make_interaction()
        cog = _make_cog()

        await cast(Any, scheduler.Scheduler.daily_verse_time.callback)(cog, interaction, 25, 0)

        interaction.response.send_message.assert_awaited_once_with(
            "❌ Please use an `hour` from 0-23 and a `minute` from 0-59.",
            ephemeral=True,
        )


class TestRunDueDailyVerses:
    async def test_posts_only_when_time_matches_and_marks_sent(self, monkeypatch):
        cog = _make_cog()
        guild = MagicMock()
        guild.id = 123
        bot = cast(Any, cog.bot)
        bot.guilds = [guild]

        monkeypatch.setattr(scheduler.scheduler_store, "get_daily_time", AsyncMock(return_value=(7, 30)))
        monkeypatch.setattr(scheduler.scheduler_store, "was_daily_sent", AsyncMock(return_value=False))
        mark_daily_sent = AsyncMock()
        monkeypatch.setattr(scheduler.scheduler_store, "mark_daily_sent", mark_daily_sent)
        post_daily_verse = AsyncMock(return_value="sent")
        monkeypatch.setattr(cog, "_post_daily_verse", post_daily_verse)

        now = datetime.datetime(2026, 3, 12, 7, 30, tzinfo=scheduler._PHT)
        await cog._run_due_daily_verses(now=now)

        post_daily_verse.assert_awaited_once_with(guild)
        mark_daily_sent.assert_awaited_once_with("123", "2026-03-12")

    async def test_skips_when_time_does_not_match(self, monkeypatch):
        cog = _make_cog()
        guild = MagicMock()
        guild.id = 123
        bot = cast(Any, cog.bot)
        bot.guilds = [guild]

        monkeypatch.setattr(scheduler.scheduler_store, "get_daily_time", AsyncMock(return_value=(7, 0)))
        post_daily_verse = AsyncMock()
        monkeypatch.setattr(cog, "_post_daily_verse", post_daily_verse)

        now = datetime.datetime(2026, 3, 12, 7, 1, tzinfo=scheduler._PHT)
        await cog._run_due_daily_verses(now=now)

        post_daily_verse.assert_not_awaited()

    async def test_skips_when_daily_verse_was_already_sent(self, monkeypatch):
        cog = _make_cog()
        guild = MagicMock()
        guild.id = 123
        bot = cast(Any, cog.bot)
        bot.guilds = [guild]

        monkeypatch.setattr(scheduler.scheduler_store, "get_daily_time", AsyncMock(return_value=(7, 30)))
        monkeypatch.setattr(scheduler.scheduler_store, "was_daily_sent", AsyncMock(return_value=True))
        post_daily_verse = AsyncMock()
        mark_daily_sent = AsyncMock()
        monkeypatch.setattr(cog, "_post_daily_verse", post_daily_verse)
        monkeypatch.setattr(scheduler.scheduler_store, "mark_daily_sent", mark_daily_sent)

        now = datetime.datetime(2026, 3, 12, 7, 30, tzinfo=scheduler._PHT)
        await cog._run_due_daily_verses(now=now)

        post_daily_verse.assert_not_awaited()
        mark_daily_sent.assert_not_awaited()
