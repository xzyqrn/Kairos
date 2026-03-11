"""
cogs/scheduler.py — Automated daily/weekly Bible verse posting.

Tasks:
  • Daily verse   — #daily-verse at 07:00 PHT (UTC+8)  every day
  • Weekly verse  — #announcements at 08:00 PHT every Sunday (with pin)

Commands (Admin only):
  /send_daily_verse — manual trigger of the daily verse post
"""

from __future__ import annotations

import datetime
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.ai_client import ai_client
from utils.bible_api import fetch_verse

log = logging.getLogger("kairos.scheduler")

# ── PHT = UTC+8 ───────────────────────────────────────────────────────────────
_PHT = datetime.timezone(datetime.timedelta(hours=8))
_DAILY_TIME = datetime.time(hour=7, minute=0, tzinfo=_PHT)
_WEEKLY_TIME = datetime.time(hour=8, minute=0, tzinfo=_PHT)


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._daily_task.start()
        self._weekly_task.start()

    def cog_unload(self) -> None:
        self._daily_task.cancel()
        self._weekly_task.cancel()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _post_daily_verse(self, guild: discord.Guild) -> None:
        """Post today's verse to #daily-verse in a single guild."""
        channel_name = os.getenv("DAILY_VERSE_CHANNEL", "daily-verse")
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel is None:
            log.warning("Guild '%s' has no #%s channel.", guild.name, channel_name)
            return

        try:
            verse = await fetch_verse()
        except Exception as exc:
            log.error("fetch_verse failed for daily task in guild %s: %s", guild.id, exc)
            return

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

        today = datetime.date.today().strftime("%A, %B %-d, %Y")
        version_name = os.getenv("BIBLE_VERSION_NAME", "NIV").strip()
        ver = version_name if verse.source == "api" else "KJV"
        embed.set_footer(text=f"{today} · {ver}")

        try:
            await channel.send(embed=embed)
            log.info("Daily verse posted to guild '%s' #%s", guild.name, channel_name)
        except discord.HTTPException as exc:
            log.error("Failed to send daily verse to guild %s: %s", guild.id, exc)

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
            verse = await fetch_verse()
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

        week_label = datetime.date.today().strftime("Week of %B %-d, %Y")
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

    @tasks.loop(time=_DAILY_TIME)
    async def _daily_task(self) -> None:
        log.info("Running daily verse task for %d guild(s).", len(self.bot.guilds))
        for guild in self.bot.guilds:
            await self._post_daily_verse(guild)

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
        description="(Admin) Manually trigger today's daily verse post.",
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
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._post_daily_verse(interaction.guild)
        await interaction.followup.send("✅ Daily verse posted.", ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Administrator permission required.", ephemeral=True
            )
        else:
            log.exception("Scheduler command error: %s", error)
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ `{error}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ `{error}`", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
