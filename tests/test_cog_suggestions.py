"""
tests/test_cog_suggestions.py — Unit tests for cogs/suggestions.py rate limiting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.suggestions as suggestions


class TestMoodSelectRateLimit:
    async def test_callback_short_circuits_when_rate_limited(self, monkeypatch):
        select = suggestions.MoodSelect(guild_id="123", user_id="42")
        interaction = MagicMock()
        interaction.user.id = 42
        interaction.response.send_message = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        monkeypatch.setattr(suggestions, "check_user_cooldown", AsyncMock(return_value=9.9))
        generate_response = AsyncMock()
        monkeypatch.setattr(suggestions.ai_client, "generate_response", generate_response)

        await select.callback(interaction)

        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
        sent = interaction.response.send_message.await_args.args[0]
        assert "mood check" in sent
        assert "**9.9s**" in sent
        generate_response.assert_not_awaited()
