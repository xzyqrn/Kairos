"""
cogs/bible.py — Daily Bible Verse + Devotion commands.

Commands:
  /verse [passage]   — Fetch and AI-explain a passage or topic
  /devotion [topic?] — Generate a daily devotional
  /pray [topic]      — Generate a personal prayer (ephemeral)
  /dailyverse        — Get today's verse (also increments streak)
"""

from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.bible_api import fetch_verse
from utils.rate_limiter import cooldown, guild_rate_limit, handle_cooldown_error

log = logging.getLogger("kairos.bible")

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _increment_streak(bot: commands.Bot, user_id: int) -> None:
    """Fire-and-forget streak increment via the Streaks cog if loaded."""
    streaks_cog = bot.cogs.get("Streaks")
    if streaks_cog and hasattr(streaks_cog, "record_devotion"):
        try:
            await streaks_cog.record_devotion(str(user_id))
        except Exception as exc:
            log.warning("Could not increment streak for user %s: %s", user_id, exc)


def _verse_embed(reference: str, text: str, source: str) -> discord.Embed:
    version_name = os.getenv("BIBLE_VERSION_NAME", "NIV").strip()
    embed = discord.Embed(
        title=f"📖 {reference}",
        description=f"> {text}",
        color=discord.Color.from_rgb(74, 144, 226),
    )
    if source == "fallback":
        embed.set_footer(text="KJV · offline fallback")
    else:
        embed.set_footer(text=f"{version_name} · scripture.api.bible")
    return embed


# ── Cog ───────────────────────────────────────────────────────────────────────

class Bible(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /verse ────────────────────────────────────────────────────────────────

    @app_commands.command(name="verse", description="Look up and get an AI explanation of a Bible verse or topic.")
    @app_commands.describe(passage="e.g. 'John 3:16', 'Psalm 23', 'faith'")
    @cooldown("verse")
    @guild_rate_limit()
    async def verse(self, interaction: discord.Interaction, passage: str) -> None:
        """
        Look up a Bible passage or topic and return an AI explanation and verse reference.

        Fetches the verse from the Bible API, then generates an AI reflection
        with a practical takeaway for young Christians.

        Args:
            interaction: The Discord interaction context.
            passage: A Bible reference (e.g. "John 3:16") or topic keyword.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        # 1. Fetch the verse
        try:
            bible_verse = await fetch_verse(passage)
        except Exception as exc:
            log.warning("fetch_verse error for '%s': %s", passage, exc)
            await interaction.followup.send(
                f"❌ Could not find a verse for **{passage}**. Try a different reference.",
            )
            return

        # 2. AI explanation
        prompt = (
            f"The user asked about: \"{passage}\".\n"
            f"Here is the relevant Bible verse:\n\n"
            f"{bible_verse.reference}: {bible_verse.text}\n\n"
            "Please: (1) briefly explain what this verse means in context, "
            "(2) share one practical takeaway for a young Christian today. "
            "Keep it under 200 words. Begin with the verse reference in bold."
        )

        try:
            explanation = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(
                f"❌ AI explanation unavailable: `{exc}`\n\n"
                + f"> **{bible_verse.reference}** — {bible_verse.text}"
            )
            return

        embed = _verse_embed(bible_verse.reference, bible_verse.text, bible_verse.source)
        embed.add_field(name="✨ Reflection", value=explanation[:1024], inline=False)
        embed.set_author(name=str(interaction.user.display_name), icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed)

    # ── /devotion ─────────────────────────────────────────────────────────────

    @app_commands.command(name="devotion", description="Get a short daily devotional, optionally on a topic.")
    @app_commands.describe(topic="Optional topic, e.g. 'hope', 'forgiveness', 'anxiety'")
    @cooldown("devotion")
    @guild_rate_limit()
    async def devotion(self, interaction: discord.Interaction, topic: str = "") -> None:
        """
        Generate a short daily devotional, optionally focused on a topic.

        The devotional includes a key verse, 3-4 sentences of reflection,
        and a closing prayer. Also increments the user's devotion streak.

        Args:
            interaction: The Discord interaction context.
            topic: Optional topic keyword (e.g. "hope", "forgiveness").
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        topic_clause = f" on the topic of **{topic}**" if topic.strip() else ""
        prompt = (
            f"Write a short daily devotional{topic_clause} for a young Christian (ages 13–25). "
            "Structure it as:\n"
            "1. **Verse** — pick one relevant Bible verse (KJV) and quote it in full.\n"
            "2. **Devotion** — 3–4 sentences of reflection connecting the verse to everyday life.\n"
            "3. **Prayer** — one short closing prayer sentence.\n"
            "Keep the total under 250 words. Use a warm, conversational tone."
        )

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ Could not generate devotion: `{exc}`")
            return

        title = f"📅 Daily Devotion{(' — ' + topic.title()) if topic.strip() else ''}"
        embed = discord.Embed(
            title=title,
            description=response[:4000],
            color=discord.Color.from_rgb(255, 200, 87),
        )
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)
        await _increment_streak(self.bot, interaction.user.id)

    # ── /pray ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="prayer", description="Generate a personal prayer for you (private).")
    @app_commands.describe(topic="What do you want to pray about? e.g. 'anxiety', 'my family', 'exams'")
    @cooldown("prayer")
    @guild_rate_limit()
    async def pray(self, interaction: discord.Interaction, topic: str) -> None:
        """
        Generate a personal prayer on the given topic, sent as an ephemeral message.

        The prayer is addressed to God, references a relevant Bible verse,
        and ends with "Amen." Only the requesting user can see the response.

        Args:
            interaction: The Discord interaction context.
            topic: What the user wants to pray about.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        prompt = (
            f"Write a sincere, personal prayer for a young Christian about: \"{topic}\".\n"
            "The prayer should:\n"
            "- Be addressed directly to God\n"
            "- Reference at least one Bible verse that is relevant\n"
            "- Be 4–6 sentences long\n"
            "- End with 'Amen.'\n"
            "Do not include any commentary — only the prayer itself."
        )

        try:
            prayer_text = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(
                f"❌ Could not generate prayer: `{exc}`", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🙏 A Prayer for You",
            description=prayer_text[:4000],
            color=discord.Color.purple(),
        )
        embed.set_footer(text=f"Topic: {topic} · This message is only visible to you.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /dailyverse ───────────────────────────────────────────────────────────

    @app_commands.command(name="dailyverse", description="Get today's Bible verse of the day.")
    @guild_rate_limit()
    async def dailyverse(self, interaction: discord.Interaction) -> None:
        """
        Fetch today's verse of the day and an optional AI reflection.

        If the server has AI configured, appends a 2-sentence encouraging
        reflection. Also increments the user's devotion streak.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            verse = await fetch_verse()  # no passage = today's fallback verse
        except Exception as exc:
            log.warning("dailyverse fetch error: %s", exc)
            await interaction.followup.send("❌ Could not retrieve today's verse. Try again shortly.")
            return

        embed = _verse_embed(verse.reference, verse.text, verse.source)
        embed.title = f"🌅 Verse of the Day — {verse.reference}"

        # Attempt AI reflection if guild is configured
        config = await ai_client.get_guild_config(str(interaction.guild_id))
        if config:
            prompt = (
                f"In 2 sentences, share an encouraging reflection on this verse for a young Christian:\n"
                f"\"{verse.reference}: {verse.text}\""
            )
            try:
                reflection = await ai_client.generate_response(
                    prompt=prompt,
                    guild_id=str(interaction.guild_id),
                    user_id=str(interaction.user.id),
                )
                embed.add_field(name="✨ Today's Reflection", value=reflection[:512], inline=False)
            except RuntimeError:
                pass  # reflection is optional; omit silently

        await interaction.followup.send(embed=embed)
        await _increment_streak(self.bot, interaction.user.id)

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if await handle_cooldown_error(interaction, error):
            return
        msg = f"❌ Command error: `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Bible(bot))
