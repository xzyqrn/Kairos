"""
tests/test_welcome_wall.py — Unit tests for welcome-wall config and channel safety.
"""

from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.welcome_wall as welcome_wall


def _make_cog() -> welcome_wall.WelcomeWall:
    cog = object.__new__(welcome_wall.WelcomeWall)
    cog.bot = MagicMock()
    return cog


def _make_interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = 999
    interaction.guild = MagicMock()
    interaction.channel = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestLoadConfig:
    async def test_invalid_json_returns_empty_dict(self, tmp_path, monkeypatch):
        config_path = tmp_path / "welcome_wall.json"
        config_path.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(welcome_wall, "_CONFIG_PATH", config_path)

        assert await welcome_wall._load_config() == {}


class TestPrayerWall:
    async def test_missing_configured_channel_returns_error(self, tmp_path, monkeypatch):
        config_path = tmp_path / "welcome_wall.json"
        config_path.write_text(
            json.dumps({"999": {"prayer_wall_channel": "123456"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(welcome_wall, "_CONFIG_PATH", config_path)

        interaction = _make_interaction()
        interaction.guild.get_channel.return_value = None
        cog = _make_cog()
        list_open = AsyncMock()
        monkeypatch.setattr(welcome_wall.prayer_store, "list_open", list_open)

        await cast(Any, welcome_wall.WelcomeWall.prayer_wall.callback)(cog, interaction)

        list_open.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with(
            "❌ The configured prayer wall channel wasn't found. "
            "Use `/set_prayer_wall_channel` to set a new one."
        )

    async def test_non_sendable_current_channel_returns_error(self, tmp_path, monkeypatch):
        config_path = tmp_path / "welcome_wall.json"
        config_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(welcome_wall, "_CONFIG_PATH", config_path)

        interaction = _make_interaction()
        interaction.channel = object()
        cog = _make_cog()
        list_open = AsyncMock()
        monkeypatch.setattr(welcome_wall.prayer_store, "list_open", list_open)

        await cast(Any, welcome_wall.WelcomeWall.prayer_wall.callback)(cog, interaction)

        list_open.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with(
            "❌ I can only post the prayer wall in a text channel or thread."
        )
