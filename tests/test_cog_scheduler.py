"""
tests/test_cog_scheduler.py — Unit tests for manual daily verse posting responses.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.scheduler as scheduler


def _make_cog() -> scheduler.Scheduler:
    cog = object.__new__(scheduler.Scheduler)
    cog.bot = MagicMock()
    return cog


def _make_interaction() -> MagicMock:
    interaction = MagicMock()
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

        interaction.followup.send.assert_awaited_once_with("✅ Daily verse posted.", ephemeral=True)

    async def test_missing_channel_response(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(cog, "_post_daily_verse", AsyncMock(return_value="missing_channel"))
        monkeypatch.setenv("DAILY_VERSE_CHANNEL", "daily-verse")

        await cast(Any, scheduler.Scheduler.send_daily_verse.callback)(cog, interaction)

        interaction.followup.send.assert_awaited_once_with(
            "❌ Could not post: no #daily-verse channel was found.",
            ephemeral=True,
        )

    async def test_send_failure_response(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        monkeypatch.setattr(cog, "_post_daily_verse", AsyncMock(return_value="send_failed"))

        await cast(Any, scheduler.Scheduler.send_daily_verse.callback)(cog, interaction)

        interaction.followup.send.assert_awaited_once_with(
            "❌ Could not post today's verse. Check the bot permissions and try again.",
            ephemeral=True,
        )
