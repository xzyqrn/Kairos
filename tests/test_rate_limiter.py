"""
tests/test_rate_limiter.py — Unit tests for utils/rate_limiter.py

Covers:
  - COOLDOWNS table values
  - handle_cooldown_error() dispatch
  - _check_guild_limit() rolling-window logic
  - guild_rate_limit() decorator behaviour
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

from utils.rate_limiter import (
    COOLDOWNS,
    GUILD_LIMIT_REQUESTS,
    GUILD_LIMIT_WINDOW_SECONDS,
    _check_guild_limit,
    _guild_request_times,
    guild_rate_limit,
    handle_cooldown_error,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_guild_times():
    """Clear the in-memory guild request log before each test."""
    _guild_request_times.clear()
    yield
    _guild_request_times.clear()


def _make_interaction(guild_id: int = 100, response_done: bool = False) -> MagicMock:
    """Build a minimal mock discord.Interaction."""
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.user.id = 42
    interaction.command = MagicMock()
    interaction.command.name = "verse"
    # response: use a MagicMock so is_done() returns a plain bool (not a coroutine)
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=response_done)
    interaction.response.send_message = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── TestCooldownTable ─────────────────────────────────────────────────────────

class TestCooldownTable:
    def test_cooldowns_is_dict(self):
        assert isinstance(COOLDOWNS, dict)

    def test_all_values_are_positive_floats(self):
        for key, val in COOLDOWNS.items():
            assert isinstance(val, (int, float)), f"{key} has non-numeric value"
            assert val > 0, f"{key} has non-positive cooldown"

    def test_known_commands_present(self):
        for cmd in ("verse", "devotion", "ask", "quiz", "howareyou"):
            assert cmd in COOLDOWNS, f"'{cmd}' missing from COOLDOWNS"


# ── TestHandleCooldownError ───────────────────────────────────────────────────

class TestHandleCooldownError:
    async def test_cooldown_error_returns_true(self):
        interaction = _make_interaction()
        error = app_commands.CommandOnCooldown(
            cooldown=MagicMock(rate=1, per=15.0, type=MagicMock()),
            retry_after=7.5,
        )
        result = await handle_cooldown_error(interaction, error)
        assert result is True

    async def test_non_cooldown_error_returns_false(self):
        interaction = _make_interaction()
        error = app_commands.MissingPermissions(["administrator"])
        result = await handle_cooldown_error(interaction, error)
        assert result is False

    async def test_sends_message_when_response_not_done(self):
        interaction = _make_interaction(response_done=False)
        error = app_commands.CommandOnCooldown(
            cooldown=MagicMock(rate=1, per=15.0, type=MagicMock()),
            retry_after=5.0,
        )
        await handle_cooldown_error(interaction, error)
        interaction.response.send_message.assert_called_once()

    async def test_sends_followup_when_response_done(self):
        interaction = _make_interaction(response_done=True)
        error = app_commands.CommandOnCooldown(
            cooldown=MagicMock(rate=1, per=15.0, type=MagicMock()),
            retry_after=5.0,
        )
        await handle_cooldown_error(interaction, error)
        interaction.followup.send.assert_called_once()


# ── TestCheckGuildLimit ───────────────────────────────────────────────────────

class TestCheckGuildLimit:
    async def test_first_request_allowed(self):
        result = await _check_guild_limit(999)
        assert result is None

    async def test_requests_under_limit_all_allowed(self):
        for _ in range(GUILD_LIMIT_REQUESTS - 1):
            result = await _check_guild_limit(777)
            assert result is None

    async def test_request_at_limit_is_blocked(self):
        for _ in range(GUILD_LIMIT_REQUESTS):
            await _check_guild_limit(555)
        result = await _check_guild_limit(555)
        assert result is not None
        assert result >= 0

    async def test_different_guilds_independent(self):
        for _ in range(GUILD_LIMIT_REQUESTS):
            await _check_guild_limit(111)
        # Guild 222 should not be affected
        result = await _check_guild_limit(222)
        assert result is None

    async def test_old_timestamps_evicted(self):
        import time
        guild_id = 333
        # Manually insert timestamps outside the rolling window
        old_time = time.monotonic() - GUILD_LIMIT_WINDOW_SECONDS - 1
        _guild_request_times[guild_id] = [old_time] * GUILD_LIMIT_REQUESTS
        # Should pass because all timestamps are expired
        result = await _check_guild_limit(guild_id)
        assert result is None


# ── TestGuildRateLimitDecorator ───────────────────────────────────────────────

class TestGuildRateLimitDecorator:
    async def test_decorated_function_called_under_limit(self):
        inner = AsyncMock(return_value="ok")
        decorated = guild_rate_limit()(inner)
        interaction = _make_interaction(guild_id=444)
        await decorated(MagicMock(), interaction)
        inner.assert_called_once()

    async def test_decorated_function_blocked_over_limit(self):
        for _ in range(GUILD_LIMIT_REQUESTS):
            await _check_guild_limit(445)

        inner = AsyncMock(return_value="ok")
        decorated = guild_rate_limit()(inner)
        interaction = _make_interaction(guild_id=445)
        await decorated(MagicMock(), interaction)
        # inner should NOT have been called
        inner.assert_not_called()

    async def test_no_guild_id_calls_through(self):
        inner = AsyncMock(return_value="ok")
        decorated = guild_rate_limit()(inner)
        interaction = _make_interaction()
        interaction.guild_id = None
        await decorated(MagicMock(), interaction)
        inner.assert_called_once()
