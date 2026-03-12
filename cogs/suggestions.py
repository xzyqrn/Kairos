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
        except RuntimeError:
            await interaction.followup.send(
                "⚠️ I couldn't create a response right now. Please try again in a moment.",
                ephemeral=True,
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

    @app_commands.command(
        name="howareyou",
        description="Share how you're feeling and get a private Bible-based response.",
    )
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
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        view = MoodView(guild_id=str(interaction.guild_id), user_id=str(interaction.user.id))
        await interaction.response.send_message(
            "👋 Choose how you're feeling below and Kairos will reply privately with something encouraging. 💙",
            view=view,
            ephemeral=True,
        )

    # ── /suggest ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="suggest",
        description="Get a few practical, Bible-based ideas for a topic.",
    )
    @app_commands.describe(
        topic="Example: how to pray more, dealing with stress, peer pressure",
    )
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
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
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
        except RuntimeError:
            await interaction.followup.send(
                "⚠️ I couldn't create suggestions right now. Please try again in a moment."
            )
            return

        embed = discord.Embed(
            title=f"💡 Biblical Suggestions: {topic.title()}",
            description=response[:4000],
            color=discord.Color.from_rgb(87, 187, 138),
        )
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    # ── /advice ───────────────────────────────────────────────────────────────

    @app_commands.command(
        name="advice",
        description="Get private Bible-based advice for a situation you're facing.",
    )
    @app_commands.describe(
        situation="Briefly explain what's going on and what kind of help you need",
    )
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
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
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
        except RuntimeError:
            await interaction.followup.send(
                "⚠️ I couldn't create advice right now. Please try again in a moment.",
                ephemeral=True,
            )
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
        description="Post an idea for your server in #suggestions-box.",
    )
    @app_commands.describe(suggestion="Your idea for the server or community")
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
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
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
        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ I couldn't post your suggestion right now. Please try again in a moment.",
                ephemeral=True,
            )
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
        description="Choose the language Kairos should use when replying to you.",
    )
    @app_commands.describe(language="Pick the language you want Kairos to use")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="English", value="English"),
            app_commands.Choice(name="Filipino / Tagalog", value="Filipino"),
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
            "Kairos will now reply in that language when possible.",
            ephemeral=True,
        )

    # ── /help ─────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="help",
        description="See a simple list of commands and what each one does.",
    )
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
            title="📖 Kairos Commands",
            description=(
                "New here? Start with `/dailyverse`, `/ask`, or `/howareyou`.\n"
                "Many support commands reply only to you."
            ),
            color=discord.Color.from_rgb(74, 144, 226),
        )

        embed.add_field(
            name="🌟 Start Here",
            value=(
                "`/dailyverse` — See today's verse and encouragement\n"
                "`/verse [passage/topic]` — Look up a verse or topic and get a simple explanation\n"
                "`/devotion [topic]` — Get a short devotional\n"
                "`/ask [question]` — Ask a Bible, faith, or life question"
            ),
            inline=False,
        )

        embed.add_field(
            name="💙 Private Support",
            value=(
                "`/howareyou` — Share how you feel and get a private response\n"
                "`/advice [situation]` — Get private Bible-based advice\n"
                "`/prayer [topic]` — Get a private personal prayer\n"
                "`/journal [entry]` — Save a private journal entry\n"
                "`/journal_view` — Read your private journal entries\n"
                "`/journal_clear` — Delete your private journal entries\n"
                "`/clear_history` — Clear Kairos chat memory for you"
            ),
            inline=False,
        )

        embed.add_field(
            name="🙏 Community",
            value=(
                "`/prayer_request [request] [anonymous]` — Share a prayer request\n"
                "`/prayer_list` — See open prayer requests\n"
                "`/prayer_answered [id]` — Mark your request as answered\n"
                "`/suggest [topic]` — Get practical Bible-based ideas\n"
                "`/community_suggest [idea]` — Post an idea to #suggestions-box\n"
                "`/quiz` — Start a Bible trivia question\n"
                "`/quiz_leaderboard` — See top quiz scores\n"
                "`/mystats` — See your devotion streak\n"
                "`/streaks` — See the server's top streaks"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚙️ Settings & Leader Tools",
            value=(
                "`/lang [language]` — Choose your reply language\n"
                "`/daily_verse_time [hour] [minute]` — View or change the daily verse time _(Admin)_\n"
                "`/send_daily_verse` — Post today's daily verse now _(Admin)_\n"
                "`/prayer_clear [id]` — Remove a prayer request _(Admin)_\n"
                "`/quiz_reset` — Reset quiz scores _(Admin)_\n"
                "`/sermon [topic]` — Create a sermon outline _(Youth Leader / Admin)_\n"
                "`/sermon_notes [file]` — Summarize sermon notes _(Youth Leader / Admin)_\n"
                "`/ai_setup`, `/ai_status`, `/ai_test`, `/ai_clear`, `/ai_tone` _(Admin)_"
            ),
            inline=False,
        )

        embed.set_footer(text="Kairos is here to make starting simple.")
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
