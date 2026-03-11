"""
utils/bot_logger.py — Send color-coded embeds to #bot-logs and write to the Python log.

Usage:
    from utils.bot_logger import BotLogger
    logger = BotLogger(bot)

    await logger.info("Cog 'bible' loaded successfully.")
    await logger.warning("Rate limit hit by user 123456 on /verse.")
    await logger.error("Claude API error: 401 Unauthorized.")

Rules:
  - green  = info
  - yellow = warning
  - red    = error
  - NEVER log API keys or raw DM content.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.ext.commands import Bot

log = logging.getLogger("kairos.bot_logger")

_COLORS = {
    "info":    discord.Color.green(),
    "warning": discord.Color.gold(),
    "error":   discord.Color.red(),
}

_ICONS = {
    "info":    "🟢",
    "warning": "🟡",
    "error":   "🔴",
}


class BotLogger:
    """
    Thin wrapper that writes to Python logging AND optionally sends an embed
    to the #bot-logs Discord channel (if the bot is ready and the channel exists).
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._channel_name: str = os.getenv("BOT_LOGS_CHANNEL", "bot-logs")
        self._channel_cache: dict[int, discord.TextChannel | None] = {}

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """Return the guild's #bot-logs channel, or None if not found."""
        if guild.id in self._channel_cache:
            return self._channel_cache[guild.id]

        channel: discord.TextChannel | None = discord.utils.get(
            guild.text_channels,
            name=self._channel_name,
        )
        self._channel_cache[guild.id] = channel
        return channel

    async def _send_to_all_guilds(
        self,
        level: str,
        message: str,
        title: str | None = None,
    ) -> None:
        """Send a color-coded embed to every guild's #bot-logs channel."""
        if not self._bot.is_ready():
            return

        color = _COLORS.get(level, discord.Color.light_grey())
        icon = _ICONS.get(level, "⚪")
        embed_title = title or f"{icon} Kairos — {level.capitalize()}"

        embed = discord.Embed(
            title=embed_title,
            description=message[:4000],
            color=color,
        )

        for guild in self._bot.guilds:
            channel = self._get_log_channel(guild)
            if channel is None:
                continue
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                log.warning("Missing permission to send to #%s in guild %s", self._channel_name, guild.id)
            except discord.HTTPException as exc:
                log.warning("Failed to send log embed to guild %s: %s", guild.id, exc)

    async def _send_to_guild(
        self,
        guild_id: int,
        level: str,
        message: str,
        title: str | None = None,
    ) -> None:
        """Send a log embed to a specific guild's #bot-logs channel."""
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return

        channel = self._get_log_channel(guild)
        if channel is None:
            return

        color = _COLORS.get(level, discord.Color.light_grey())
        icon = _ICONS.get(level, "⚪")
        embed_title = title or f"{icon} Kairos — {level.capitalize()}"

        embed = discord.Embed(
            title=embed_title,
            description=message[:4000],
            color=color,
        )

        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("Failed to send log embed to guild %s: %s", guild_id, exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def info(
        self,
        message: str,
        *,
        guild_id: int | None = None,
        title: str | None = None,
    ) -> None:
        """Log an informational message (green embed)."""
        log.info(message)
        if guild_id:
            await self._send_to_guild(guild_id, "info", message, title)
        else:
            await self._send_to_all_guilds("info", message, title)

    async def warning(
        self,
        message: str,
        *,
        guild_id: int | None = None,
        title: str | None = None,
    ) -> None:
        """Log a warning (yellow embed)."""
        log.warning(message)
        if guild_id:
            await self._send_to_guild(guild_id, "warning", message, title)
        else:
            await self._send_to_all_guilds("warning", message, title)

    async def error(
        self,
        message: str,
        *,
        guild_id: int | None = None,
        title: str | None = None,
    ) -> None:
        """Log an error (red embed)."""
        log.error(message)
        if guild_id:
            await self._send_to_guild(guild_id, "error", message, title)
        else:
            await self._send_to_all_guilds("error", message, title)

    def log_cog_status(self, results: list[tuple[str, bool, str | None]]) -> None:
        """
        Log cog load results to Python logging only (called before bot is ready).

        results: list of (cog_name, success, error_msg_or_None)
        """
        for cog_name, success, err in results:
            if success:
                log.info("✅ Loaded cog: %s", cog_name)
            else:
                log.error("❌ Failed to load cog %s: %s", cog_name, err)
