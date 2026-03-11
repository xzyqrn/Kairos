"""
tests/test_cog_prayer_commands.py — Unit tests for cogs/prayer.py command flows.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.prayer as prayer


def _make_cog() -> prayer.Prayer:
    cog = object.__new__(prayer.Prayer)
    cog.bot = MagicMock()
    return cog


def _make_interaction(*, user_id: int = 123, is_admin: bool = False) -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = 999
    interaction.user.id = user_id
    interaction.user.guild_permissions.administrator = is_admin
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestPrayerAnswered:
    async def test_uses_exact_resolved_id_for_update(self, monkeypatch):
        interaction = _make_interaction(user_id=42)
        cog = _make_cog()
        target = {
            "id": "abcd1234-full-id",
            "user_id": "42",
            "request": "Please pray",
            "anonymous": False,
            "timestamp": "2026-03-07T09:00:00",
            "answered": False,
        }

        monkeypatch.setattr(prayer.prayer_store, "find_matches", AsyncMock(return_value=[target]))
        mark_answered = AsyncMock(return_value=True)
        monkeypatch.setattr(prayer.prayer_store, "mark_answered", mark_answered)

        await cast(Any, prayer.Prayer.prayer_answered.callback)(cog, interaction, "abcd")

        mark_answered.assert_awaited_once_with("999", "abcd1234-full-id")

    async def test_ambiguous_prefix_returns_error(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        matches = [
            {"id": "abcd1111-full-id"},
            {"id": "abcd2222-full-id"},
        ]

        monkeypatch.setattr(prayer.prayer_store, "find_matches", AsyncMock(return_value=matches))
        mark_answered = AsyncMock()
        monkeypatch.setattr(prayer.prayer_store, "mark_answered", mark_answered)

        await cast(Any, prayer.Prayer.prayer_answered.callback)(cog, interaction, "abcd")

        mark_answered.assert_not_awaited()
        interaction.followup.send.assert_awaited()
        message = interaction.followup.send.await_args.args[0]
        assert "matches multiple requests" in message

    async def test_invalid_prefix_is_rejected_before_lookup(self, monkeypatch):
        interaction = _make_interaction()
        cog = _make_cog()
        find_matches = AsyncMock()
        monkeypatch.setattr(prayer.prayer_store, "find_matches", find_matches)

        await cast(Any, prayer.Prayer.prayer_answered.callback)(cog, interaction, "%")

        find_matches.assert_not_awaited()
        interaction.followup.send.assert_awaited()
        message = interaction.followup.send.await_args.args[0]
        assert "hexadecimal characters and hyphens" in message


class TestPrayerClear:
    async def test_uses_exact_resolved_id_for_delete(self, monkeypatch):
        interaction = _make_interaction(is_admin=True)
        cog = _make_cog()
        target = {"id": "abcd1234-full-id"}

        monkeypatch.setattr(prayer.prayer_store, "find_matches", AsyncMock(return_value=[target]))
        delete = AsyncMock(return_value=True)
        monkeypatch.setattr(prayer.prayer_store, "delete", delete)

        await cast(Any, prayer.Prayer.prayer_clear.callback)(cog, interaction, "abcd")

        delete.assert_awaited_once_with("999", "abcd1234-full-id")

    async def test_invalid_prefix_is_rejected_before_lookup(self, monkeypatch):
        interaction = _make_interaction(is_admin=True)
        cog = _make_cog()
        find_matches = AsyncMock()
        monkeypatch.setattr(prayer.prayer_store, "find_matches", find_matches)

        await cast(Any, prayer.Prayer.prayer_clear.callback)(cog, interaction, "abc_def")

        find_matches.assert_not_awaited()
        interaction.followup.send.assert_awaited()
        message = interaction.followup.send.await_args.args[0]
        assert "hexadecimal characters and hyphens" in message
