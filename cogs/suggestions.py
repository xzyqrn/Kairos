"""
cogs/suggestions.py — Mood Check-in, Suggestions, Advice, Community Suggestions,
                       Language toggle, and /help command.

Commands:
  /howareyou          — Mood dropdown with 6 options; AI responds with verse + reflection
  /suggest [topic]    — 3–5 practical biblical suggestions
  /advice [situation] — Personal advice (ephemeral)
  /community_suggest  — Post to #suggestions-box with ✅ ❌ reactions
  /lang [language]    — Set preferred language (English | Filipino)
  /help               — Full command reference embed
"""

from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.lang import set_user_lang
from utils.rate_limiter import (
    check_user_cooldown,
    cooldown,
    format_cooldown_message,
    guild_rate_limit,
    handle_cooldown_error,
)

log = logging.getLogger("kairos.suggestions")

_MOODS = [
    ("😊", "Happy / Grateful", "the user feels happy and grateful"),
    ("😰", "Anxious / Stressed", "the user is feeling anxious or stressed"),
    ("😢", "Sad / Lonely", "the user is feeling sad or lonely"),
    ("😠", "Angry / Frustrated", "the user is feeling angry or frustrated"),
    ("🌵", "Spiritually Dry", "the user is experiencing spiritual dryness or a dry season in their faith"),
    ("🤔", "Confused / Lost", "the user feels confused or spiritually lost"),
]


# ── Mood Dropdown ─────────────────────────────────────────────────────────────

class MoodSelect(discord.ui.Select):
    def __init__(self, guild_id: str, user_id: str) -> None:
        self.guild_id = guild_id
        self.user_id = user_id

        options = [
            discord.SelectOption(label=label, value=context, emoji=emoji)
            for emoji, label, context in _MOODS
        ]
        super().__init__(
            placeholder="How are you feeling right now?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        retry_after = await check_user_cooldown(
            "mood_select",
            guild_id=int(self.guild_id),
            user_id=interaction.user.id,
        )
        if retry_after is not None:
            log.info(
                "Rate limit hit: user=%s guild=%s command=mood_select retry_after=%.1fs",
                interaction.user.id,
                self.guild_id,
                retry_after,
            )
            await interaction.response.send_message(
                format_cooldown_message(retry_after, action="This mood check"),
                ephemeral=True,
            )
            return

        mood_context = self.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)

        version_name = os.getenv("BIBLE_VERSION_NAME", "NIV").strip()
        prompt = (
            f"A young Christian (ages 13–25) is reaching out because {mood_context}.\n"
            "Please respond with:\n"
            f"1. **Verse** — one relevant Bible verse ({version_name}), quoted in full.\n"
            "2. **Reflection** — exactly 2 sentences connecting the verse to how they feel.\n"
            "3. **Encouragement** — one concrete, actionable step they can take today.\n"
            "Keep the whole response under 200 words. Speak directly to them (use 'you')."
        )

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=self.guild_id,
                user_id=self.user_id,
            )
        except RuntimeError as exc:
            await interaction.followup.send(
                f"❌ Could not generate a response right now: `{exc}`", ephemeral=True
            )
            return

        # Find the label for the selected mood
        label = next(
            (lbl for _, lbl, ctx in _MOODS if ctx == mood_context),
            "your mood",
        )

        embed = discord.Embed(
            title="💙 A Word for You",
            description=response[:4000],
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.set_footer(text=f"You selected: {label} · This message is only visible to you.")
        await interaction.followup.send(embed=embed, ephemeral=True)


class MoodView(discord.ui.View):
    def __init__(self, guild_id: str, user_id: str) -> None:
        super().__init__(timeout=120)
        self.add_item(MoodSelect(guild_id=guild_id, user_id=user_id))


# ── Cog ───────────────────────────────────────────────────────────────────────

class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /howareyou ────────────────────────────────────────────────────────────

    @app_commands.command(name="howareyou", description="Tell Kairos how you're feeling and receive a biblical response.")
    @cooldown("howareyou")
    @guild_rate_limit()
    async def howareyou(self, interaction: discord.Interaction) -> None:
        """
        Present a mood selection dropdown; respond with an AI-generated verse and
        reflection for the chosen mood.

        The response is ephemeral (only visible to the user who invoked the command).

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        view = MoodView(guild_id=str(interaction.guild_id), user_id=str(interaction.user.id))
        await interaction.response.send_message(
            "👋 Hey! Select how you're feeling below and Kairos will respond with a word for you. 💙",
            view=view,
            ephemeral=True,
        )

    # ── /suggest ──────────────────────────────────────────────────────────────

    @app_commands.command(name="suggest", description="Get 3–5 practical biblical suggestions on a topic.")
    @app_commands.describe(topic="Topic you want suggestions on, e.g. 'how to pray more', 'dealing with peer pressure'")
    @cooldown("suggest")
    @guild_rate_limit()
    async def suggest(self, interaction: discord.Interaction, topic: str) -> None:
        """
        Generate 3 to 5 numbered, practical biblical suggestions on a given topic.

        Each suggestion includes a bold title, 1-2 sentences of explanation,
        and at least one Bible verse reference.

        Args:
            interaction: The Discord interaction context.
            topic: The topic to generate suggestions for.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        prompt = (
            f"A young Christian wants practical biblical suggestions on: \"{topic}\".\n"
            "Give 3–5 numbered, actionable suggestions. Each suggestion should:\n"
            "- Start with a bold title (3–5 words)\n"
            "- Include 1–2 sentences of explanation\n"
            "- Reference at least one Bible verse\n"
            "Keep the total response under 400 words."
        )

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ `{exc}`")
            return

        embed = discord.Embed(
            title=f"💡 Biblical Suggestions: {topic.title()}",
            description=response[:4000],
            color=discord.Color.from_rgb(87, 187, 138),
        )
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    # ── /advice ───────────────────────────────────────────────────────────────

    @app_commands.command(name="advice", description="Get personal biblical advice for a situation (private).")
    @app_commands.describe(situation="Describe your situation — what do you need advice on?")
    @cooldown("advice")
    @guild_rate_limit()
    async def advice(self, interaction: discord.Interaction, situation: str) -> None:
        """
        Provide compassionate, biblically-grounded advice for a situation.

        Response is ephemeral (only visible to the requesting user). Includes
        acknowledgement, 2-3 practical Scripture-based suggestions, and a closing
        prayer or encouraging verse.

        Args:
            interaction: The Discord interaction context.
            situation: A description of the situation the user needs advice on.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        prompt = (
            f"A young Christian is dealing with this situation: \"{situation}\".\n"
            "Provide compassionate, biblically-grounded advice:\n"
            "1. Acknowledge their feelings briefly (1 sentence)\n"
            "2. Give 2–3 pieces of practical advice rooted in Scripture\n"
            "3. End with a short prayer or encouraging verse\n"
            "Keep under 250 words. Speak directly to them."
        )

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ `{exc}`", ephemeral=True)
            return

        embed = discord.Embed(
            title="🕊️ Personal Advice",
            description=response[:4000],
            color=discord.Color.from_rgb(155, 89, 182),
        )
        embed.set_footer(text="This message is only visible to you.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /community_suggest ────────────────────────────────────────────────────

    @app_commands.command(
        name="community_suggest",
        description="Post a suggestion to the #suggestions-box channel for the community to vote on.",
    )
    @app_commands.describe(suggestion="Your suggestion for the community or server")
    async def community_suggest(
        self, interaction: discord.Interaction, suggestion: str
    ) -> None:
        """
        Post a community suggestion to the #suggestions-box channel with vote reactions.

        Creates an embed in #suggestions-box and adds ✅ and ❌ reaction buttons
        so the community can vote. The channel must already exist.

        Args:
            interaction: The Discord interaction context.
            suggestion: The suggestion text to post.
        """
        if not interaction.guild:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        channel = discord.utils.get(interaction.guild.text_channels, name="suggestions-box")
        if channel is None:
            await interaction.response.send_message(
                "❌ Could not find a **#suggestions-box** channel. Ask an admin to create it.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="💬 Community Suggestion",
            description=suggestion[:1000],
            color=discord.Color.teal(),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        embed.set_footer(text="React with ✅ to support · ❌ to oppose")

        try:
            msg = await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to post in **#suggestions-box**.", ephemeral=True
            )
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"❌ Failed to post: `{exc}`", ephemeral=True)
            return

        # Confirm to the user first — add_reaction errors should not block this
        await interaction.response.send_message(
            f"✅ Your suggestion has been posted to {channel.mention}!", ephemeral=True
        )

        # Reactions are best-effort; missing permission is non-fatal
        try:
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── /lang ─────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="lang",
        description="Set your preferred language for Kairos responses.",
    )
    @app_commands.describe(language="Choose your preferred language")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="English", value="English"),
            app_commands.Choice(name="Filipino", value="Filipino"),
        ]
    )
    async def lang(self, interaction: discord.Interaction, language: str) -> None:
        """
        Set the caller's preferred language for Kairos AI responses.

        The preference is stored per-user and applied to all AI-generated
        content (verses, devotions, advice, etc.) across all servers.

        Args:
            interaction: The Discord interaction context.
            language: The preferred language — "English" or "Filipino".
        """
        try:
            await set_user_lang(interaction.user.id, language)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Language preference set to **{language}**. "
            "Kairos will now respond in your chosen language.",
            ephemeral=True,
        )

    # ── /help ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="View all Kairos commands grouped by category.")
    async def help(self, interaction: discord.Interaction) -> None:
        """
        Display the full Kairos command reference grouped by category.

        Shows all available slash commands with brief descriptions organized
        into sections: Bible & Devotion, Prayer, Quiz, Mood & Advice,
        Sermon & Study, Streaks & Journal, Files, and Settings.

        Args:
            interaction: The Discord interaction context.
        """
        embed = discord.Embed(
            title="📖 Kairos — Command Reference",
            description="A biblically-grounded AI assistant for your Christian youth community.",
            color=discord.Color.from_rgb(74, 144, 226),
        )

        embed.add_field(
            name="📖 Bible & Devotion",
            value=(
                "`/verse [passage]` — Look up & explain a Bible verse\n"
                "`/devotion [topic]` — Get a daily devotional\n"
                "`/pray [topic]` — Personal prayer (private)\n"
                "`/dailyverse` — Today's verse of the day"
            ),
            inline=False,
        )

        embed.add_field(
            name="🙏 Prayer",
            value=(
                "`/pray_request [request] [anonymous]` — Submit a prayer request\n"
                "`/pray_list` — View open requests\n"
                "`/pray_answered [id]` — Mark your request as answered\n"
                "`/pray_clear [id]` — Delete a request _(Admin)_"
            ),
            inline=False,
        )

        embed.add_field(
            name="🧠 Quiz",
            value=(
                "`/quiz` — Bible trivia (30s timer, +10 pts)\n"
                "`/quiz_leaderboard` — Top 10 scores\n"
                "`/quiz_reset` — Reset scores _(Admin)_"
            ),
            inline=False,
        )

        embed.add_field(
            name="💙 Mood & Advice",
            value=(
                "`/howareyou` — Mood check-in with biblical response (private)\n"
                "`/suggest [topic]` — 3–5 practical biblical suggestions\n"
                "`/advice [situation]` — Personal advice (private)\n"
                "`/ask [question]` — Ask Kairos anything"
            ),
            inline=False,
        )

        embed.add_field(
            name="📝 Sermon & Study",
            value=(
                "`/sermon [topic]` — Sermon outline _(Youth Leader / Admin)_\n"
                "`/sermon_notes [file]` — Summarize sermon notes _(Youth Leader / Admin)_"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔥 Streaks & Journal",
            value=(
                "`/mystats` — Your devotion streak & stats\n"
                "`/streaks` — Top 10 devotion streaks\n"
                "`/journal [entry]` — Write a private journal entry\n"
                "`/journal_view` — Read your past entries (private)"
            ),
            inline=False,
        )

        embed.add_field(
            name="📁 Files",
            value=(
                "`/file_read [file]` — AI-summarize an uploaded file\n"
                "`/file_ask [file] [question]` — Ask a question about a file\n"
                "`/file_write [name] [content]` — Create & download a file _(Leader/Admin)_\n"
                "`/file_convert [file] [format]` — Convert file format _(Leader/Admin)_"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚙️ Settings",
            value=(
                "`/lang [language]` — Set response language (English / Filipino)\n"
                "`/community_suggest [idea]` — Post to #suggestions-box\n"
                "`/ai_setup` · `/ai_status` · `/ai_test` · `/ai_clear` · `/ai_tone` _(Admin)_"
            ),
            inline=False,
        )

        embed.set_footer(text="Kairos — guided by faith, built for community 🕊️")
        await interaction.response.send_message(embed=embed)

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if await handle_cooldown_error(interaction, error):
            return
        msg = f"❌ `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))
