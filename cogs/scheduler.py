"""
cogs/scheduler.py — Automated daily/weekly Bible verse posting.

Tasks:
  • Daily verse   — #daily-verse at a per-server PHT time every day
  • Weekly verse  — #announcements at 08:00 PHT every Sunday (with pin)

Commands (Admin only):
  /send_daily_verse — manual trigger of the daily verse post
  /daily_verse_time — view or set the server's daily verse time
"""

from __future__ import annotations

import datetime
import logging
import os
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.ai_client import ai_client
from utils.bible_api import fetch_daily_verse
from utils.scheduler_store import scheduler_store

log = logging.getLogger("kairos.scheduler")

# ── PHT = UTC+8 ───────────────────────────────────────────────────────────────
_PHT = datetime.timezone(datetime.timedelta(hours=8))
_WEEKLY_TIME = datetime.time(hour=8, minute=0, tzinfo=_PHT)
DailyVerseStatus = Literal["sent", "missing_channel", "fetch_failed", "send_failed"]


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._daily_task.start()
        self._weekly_task.start()

    async def cog_unload(self) -> None:
        self._daily_task.cancel()
        self._weekly_task.cancel()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _post_daily_verse(self, guild: discord.Guild) -> DailyVerseStatus:
        """Post today's verse to #daily-verse in a single guild."""
        channel_name = os.getenv("DAILY_VERSE_CHANNEL", "daily-verse")
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel is None:
            log.warning("Guild '%s' has no #%s channel.", guild.name, channel_name)
            return "missing_channel"

        try:
            verse = await fetch_daily_verse()
        except Exception as exc:
            log.error("fetch_verse failed for daily task in guild %s: %s", guild.id, exc)
            return "fetch_failed"

        embed = discord.Embed(
            title=f"🌅 Verse of the Day — {verse.reference}",
            description=f"> {verse.text}",
            color=discord.Color.from_rgb(74, 144, 226),
        )

        config = await ai_client.get_guild_config(str(guild.id))
        if config:
            prompt = (
                f"In 2 encouraging sentences, share a reflection for young Christians on:\n"
                f"\"{verse.reference}: {verse.text}\""
            )
            try:
                reflection = await ai_client.generate_response(
                    prompt=prompt, guild_id=str(guild.id)
                )
                embed.add_field(name="✨ Reflection", value=reflection[:512], inline=False)
            except RuntimeError as exc:
                log.warning("AI reflection failed for daily verse guild %s: %s", guild.id, exc)

        _today = datetime.datetime.now(_PHT).date()
        today = f"{_today.strftime('%A, %B')} {_today.day}, {_today.year}"
        version_name = os.getenv("BIBLE_VERSION_NAME", "NIV").strip()
        ver = version_name if verse.source == "api" else "KJV"
        embed.set_footer(text=f"{today} · {ver}")

        try:
            await channel.send(embed=embed)
            log.info("Daily verse posted to guild '%s' #%s", guild.name, channel_name)
            return "sent"
        except discord.HTTPException as exc:
            log.error("Failed to send daily verse to guild %s: %s", guild.id, exc)
            return "send_failed"

    async def _post_weekly_verse(self, guild: discord.Guild) -> None:
        """Post and pin the weekly verse in #announcements."""
        channel = discord.utils.get(guild.text_channels, name="announcements")
        if channel is None:
            # fall back to any channel with "announce" in the name
            channel = next(
                (c for c in guild.text_channels if "announce" in c.name.lower()), None
            )
        if channel is None:
            log.warning("Guild '%s' has no #announcements channel for weekly verse.", guild.name)
            return

        try:
            verse = await fetch_daily_verse()
        except Exception as exc:
            log.error("fetch_verse failed for weekly task in guild %s: %s", guild.id, exc)
            return

        # Unpin the previous Kairos weekly verse if any
        try:
            pins = await channel.pins()
            for pin in pins:
                if pin.author == self.bot.user and pin.embeds:
                    first_embed = pin.embeds[0]
                    if first_embed.title and "Verse of the Week" in first_embed.title:
                        await pin.unpin()
                        break
        except discord.HTTPException as exc:
            log.warning("Could not unpin previous weekly verse in guild %s: %s", guild.id, exc)

        embed = discord.Embed(
            title=f"📌 Verse of the Week — {verse.reference}",
            description=f"> {verse.text}",
            color=discord.Color.gold(),
        )

        config = await ai_client.get_guild_config(str(guild.id))
        if config:
            prompt = (
                f"Write a 3–4 sentence weekly encouragement for young Christians based on:\n"
                f"\"{verse.reference}: {verse.text}\"\n"
                "Make it inspiring for the week ahead."
            )
            try:
                reflection = await ai_client.generate_response(
                    prompt=prompt, guild_id=str(guild.id)
                )
                embed.add_field(name="📖 This Week's Encouragement", value=reflection[:700], inline=False)
            except RuntimeError as exc:
                log.warning("AI reflection failed for weekly verse guild %s: %s", guild.id, exc)

        _wday = datetime.datetime.now(_PHT).date()
        week_label = f"Week of {_wday.strftime('%B')} {_wday.day}, {_wday.year}"
        version_name = os.getenv("BIBLE_VERSION_NAME", "NIV").strip()
        ver = version_name if verse.source == "api" else "KJV"
        embed.set_footer(text=f"{week_label} · {ver}")

        try:
            msg = await channel.send(embed=embed)
            await msg.pin()
            log.info("Weekly verse posted and pinned in guild '%s'", guild.name)
        except discord.HTTPException as exc:
            log.error("Failed to send/pin weekly verse in guild %s: %s", guild.id, exc)

    # ── Scheduled tasks ───────────────────────────────────────────────────────

    async def _run_due_daily_verses(self, now: datetime.datetime | None = None) -> None:
        current = (now or datetime.datetime.now(_PHT)).astimezone(_PHT)
        today = current.date().isoformat()
        log.info("Checking daily verse schedules for %d guild(s).", len(self.bot.guilds))

        for guild in self.bot.guilds:
            hour, minute = await scheduler_store.get_daily_time(str(guild.id))
            if current.hour != hour or current.minute != minute:
                continue
            if await scheduler_store.was_daily_sent(str(guild.id), today):
                continue

            status = await self._post_daily_verse(guild)
            if status == "sent":
                await scheduler_store.mark_daily_sent(str(guild.id), today)

    @tasks.loop(minutes=1)
    async def _daily_task(self) -> None:
        await self._run_due_daily_verses()

    @tasks.loop(time=_WEEKLY_TIME)
    async def _weekly_task(self) -> None:
        now_pht = datetime.datetime.now(_PHT)
        if now_pht.weekday() != 6:  # 6 = Sunday
            return
        log.info("Running weekly verse task for %d guild(s).", len(self.bot.guilds))
        for guild in self.bot.guilds:
            await self._post_weekly_verse(guild)

    @_daily_task.before_loop
    async def _before_daily(self) -> None:
        await self.bot.wait_until_ready()

    @_weekly_task.before_loop
    async def _before_weekly(self) -> None:
        await self.bot.wait_until_ready()

    # ── /send_daily_verse ─────────────────────────────────────────────────────

    @app_commands.command(
        name="send_daily_verse",
        description="Post today's daily verse now in this server. (Admin)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def send_daily_verse(self, interaction: discord.Interaction) -> None:
        """Manually trigger the daily verse post for this server's configured channel.

        Posts today's verse (and an AI reflection if configured) to the #daily-verse
        channel immediately, without waiting for the 07:00 PHT scheduled task. Useful
        for testing or making up a missed post. Requires Administrator permission.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        status = await self._post_daily_verse(interaction.guild)
        channel_name = os.getenv("DAILY_VERSE_CHANNEL", "daily-verse")
        messages: dict[DailyVerseStatus, str] = {
            "sent": "✅ Today's daily verse has been posted.",
            "missing_channel": f"❌ I couldn't post because this server doesn't have a #{channel_name} channel yet.",
            "fetch_failed": "❌ I couldn't load today's verse right now.",
            "send_failed": "❌ I couldn't post today's verse. Please check my channel permissions and try again.",
        }
        await interaction.followup.send(messages[status], ephemeral=True)

    @app_commands.command(
        name="daily_verse_time",
        description="View or change when daily verses are posted in this server. (Admin)",
    )
    @app_commands.describe(
        hour="Hour in PHT, from 0 to 23. Leave blank to just view the current time",
        minute="Minute in PHT, from 0 to 59. If omitted, Kairos uses 00",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def daily_verse_time(
        self,
        interaction: discord.Interaction,
        hour: int | None = None,
        minute: int | None = None,
    ) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        if hour is None:
            current_hour, current_minute = await scheduler_store.get_daily_time(str(interaction.guild_id))
            await interaction.response.send_message(
                f"🕒 Daily verse posts are currently set for **{current_hour:02d}:{current_minute:02d} PHT** in this server.",
                ephemeral=True,
            )
            return

        selected_minute = 0 if minute is None else minute
        if not (0 <= hour <= 23 and 0 <= selected_minute <= 59):
            await interaction.response.send_message(
                "❌ Please use an `hour` from 0-23 and a `minute` from 0-59.",
                ephemeral=True,
            )
            return

        formatted = await scheduler_store.set_daily_time(
            str(interaction.guild_id),
            hour,
            selected_minute,
        )
        await interaction.response.send_message(
            f"✅ Daily verse posts will now go out at **{formatted} PHT** in this server.",
            ephemeral=True,
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need Administrator permission to use this command.",
                ephemeral=True,
            )
        else:
            log.exception("Scheduler command error: %s", error)
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ `{error}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ `{error}`", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
