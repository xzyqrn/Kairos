"""
utils/rate_limiter.py — Cooldown helpers for Kairos slash commands.

Usage in a cog:
    from utils.rate_limiter import cooldown, guild_rate_limit

    @app_commands.command(...)
    @cooldown("verse")          # per-user cooldown
    @guild_rate_limit()         # per-guild global limit
    async def verse(self, interaction): ...

All cooldowns are per-user per-guild (app_commands.BucketType.user).
If a user hits the limit they receive an ephemeral error message and
the violation is logged.

The guild rate limit uses a rolling-window token bucket (in-memory).
It resets on bot restart, which is acceptable for an anti-abuse measure.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import defaultdict
from collections.abc import Callable

import discord
from discord import app_commands

log = logging.getLogger("kairos.rate_limiter")

# ── Per-user cooldown table (seconds) ─────────────────────────────────────────
COOLDOWNS: dict[str, float] = {
    "verse":        15.0,
    "devotion":     15.0,
    "pray":         15.0,
    "ask":          20.0,
    "suggest":      20.0,
    "advice":       20.0,
    "quiz":         30.0,
    "file_read":    30.0,
    "file_ask":     30.0,
    "howareyou":    60.0,
    "pray_request": 120.0,
}


def cooldown(command_key: str) -> Callable:
    """
    Decorator factory — wraps a slash command with a per-user cooldown.

    Example::

        @app_commands.command(name="verse", ...)
        @cooldown("verse")
        async def verse(self, interaction: discord.Interaction): ...
    """
    rate = COOLDOWNS.get(command_key, 15.0)

    def decorator(func: Callable) -> Callable:
        # discord.py app_commands cooldown: rate=1 call per `per` seconds per user
        cooldown_deco = app_commands.checks.cooldown(
            rate=1,
            per=rate,
            key=lambda i: (i.guild_id, i.user.id),
        )
        return cooldown_deco(func)

    return decorator


async def handle_cooldown_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> bool:
    """
    Call this in a cog's error handler to process CommandOnCooldown errors.

    Returns True if the error was a cooldown (and was handled), False otherwise.
    """
    if isinstance(error, app_commands.CommandOnCooldown):
        retry_in = round(error.retry_after, 1)
        message = (
            f"⏳ Slow down! This command is on cooldown.\n"
            f"Try again in **{retry_in}s**."
        )
        log.info(
            "Rate limit hit: user=%s guild=%s command=%s retry_after=%.1fs",
            getattr(interaction.user, "id", "?"),
            interaction.guild_id,
            interaction.command.name if interaction.command else "?",
            error.retry_after,
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
        return True
    return False


# ── Per-guild global rate limit ────────────────────────────────────────────────

#: Maximum number of AI-heavy command invocations per guild per rolling window.
GUILD_LIMIT_REQUESTS: int = 30

#: Length of the rolling window in seconds.
GUILD_LIMIT_WINDOW_SECONDS: float = 60.0

# In-memory rolling window: {guild_id: [monotonic_timestamp, ...]}
_guild_request_times: dict[int, list[float]] = defaultdict(list)
_guild_limit_lock = asyncio.Lock()


async def _check_guild_limit(guild_id: int) -> float | None:
    """
    Record a request for *guild_id* in the rolling window and check the limit.

    Returns:
        ``None`` if the guild is under the limit (request recorded).
        The number of seconds to wait (float >= 0) if the limit has been hit.
    """
    now = time.monotonic()
    cutoff = now - GUILD_LIMIT_WINDOW_SECONDS

    async with _guild_limit_lock:
        # Evict timestamps outside the rolling window
        times = [t for t in _guild_request_times[guild_id] if t > cutoff]
        _guild_request_times[guild_id] = times

        if len(times) >= GUILD_LIMIT_REQUESTS:
            # Oldest timestamp in the window determines when the slot frees up
            retry_after = max((times[0] + GUILD_LIMIT_WINDOW_SECONDS) - now, 0.0)
            return retry_after

        _guild_request_times[guild_id].append(now)
        return None


def guild_rate_limit() -> Callable:
    """
    Decorator factory — applies a per-guild rolling-window rate limit.

    When a guild exceeds ``GUILD_LIMIT_REQUESTS`` commands in
    ``GUILD_LIMIT_WINDOW_SECONDS``, subsequent commands are refused with an
    ephemeral error message until the window slides forward.

    Apply **after** the per-user ``@cooldown`` decorator so personal cooldowns
    are evaluated first (cheaper check first)::

        @app_commands.command(...)
        @cooldown("verse")
        @guild_rate_limit()
        async def verse(self, interaction): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(cog_self, interaction: discord.Interaction, *args, **kwargs):
            guild_id = interaction.guild_id
            if guild_id is not None:
                retry_after = await _check_guild_limit(guild_id)
                if retry_after is not None:
                    retry_in = round(retry_after, 1)
                    message = (
                        f"⏳ This server is sending commands too quickly.\n"
                        f"Try again in **{retry_in}s**."
                    )
                    log.warning(
                        "Guild rate limit hit: guild=%s retry_after=%.1fs",
                        guild_id,
                        retry_after,
                    )
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send(message, ephemeral=True)
                        else:
                            await interaction.response.send_message(message, ephemeral=True)
                    except discord.HTTPException:
                        pass
                    return
            return await func(cog_self, interaction, *args, **kwargs)
        return wrapper
    return decorator
