"""
cogs/sermon.py — Sermon Notes Helper.

Commands (Youth Leader or Admin only):
  /sermon [topic]              — Generate a sermon outline for a given topic
  /sermon_notes [attachment]   — Summarize an uploaded .txt or .md sermon notes file

Output includes: title, 3–5 key points, key verses, 3 follow-up readings, one discussion question.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.rate_limiter import guild_rate_limit, handle_cooldown_error

log = logging.getLogger("kairos.sermon")

_ALLOWED_EXTENSIONS = {".txt", ".md"}
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_ROLE_NAMES = ("Youth Leader", "Admin", "Administrator")


def _has_leader_role(interaction: discord.Interaction) -> bool:
    if not hasattr(interaction.user, "roles"):
        return False
    if interaction.user.guild_permissions.administrator:  # type: ignore[union-attr]
        return True
    return any(role.name in _ROLE_NAMES for role in interaction.user.roles)  # type: ignore[union-attr]


class Sermon(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /sermon ───────────────────────────────────────────────────────────────

    @app_commands.command(name="sermon", description="(Youth Leader/Admin) Generate a sermon outline on a topic.")
    @app_commands.describe(topic="The sermon topic, e.g. 'The parable of the prodigal son', 'Grace and mercy'")
    @guild_rate_limit()
    async def sermon(self, interaction: discord.Interaction, topic: str) -> None:
        """
        Generate a structured sermon outline for a given topic.

        Restricted to users with the Youth Leader, Admin, or Administrator role.
        The outline includes a title, scripture focus, introduction, 3-5 key points
        with supporting verses, follow-up readings, a discussion question, and closing.

        Args:
            interaction: The Discord interaction context.
            topic: The sermon topic to generate an outline for.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        if not _has_leader_role(interaction):
            await interaction.response.send_message(
                "❌ This command is restricted to **Youth Leaders** and **Admins**.", ephemeral=True
            )
            return

        await interaction.response.defer()

        prompt = (
            f"Create a comprehensive sermon outline on: \"{topic}\".\n\n"
            "Structure the outline exactly as follows:\n\n"
            "**Title:** [A compelling sermon title]\n\n"
            "**Scripture Focus:** [Primary Bible passage]\n\n"
            "**Introduction:** [1-2 sentences to open the message]\n\n"
            "**Key Points:**\n"
            "1. [Point title] — [1-2 sentence explanation + supporting verse]\n"
            "2. [Point title] — [explanation + verse]\n"
            "3. [Point title] — [explanation + verse]\n"
            "4. [Point title] — [explanation + verse] (optional)\n"
            "5. [Point title] — [explanation + verse] (optional)\n\n"
            "**Key Verses:** [List 3–5 relevant Bible references]\n\n"
            "**Follow-Up Readings:**\n"
            "1. [Reference + one sentence why]\n"
            "2. [Reference + one sentence why]\n"
            "3. [Reference + one sentence why]\n\n"
            "**Discussion Question:** [One thought-provoking question for group discussion]\n\n"
            "**Closing:** [1-2 sentence altar call or challenge]\n\n"
            "Keep the total under 600 words. Use KJV for all references."
        )

        try:
            outline = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ Could not generate sermon outline: `{exc}`")
            return

        embed = discord.Embed(
            title=f"📜 Sermon Outline: {topic.title()}",
            description=outline[:4000],
            color=discord.Color.dark_blue(),
        )
        embed.set_footer(text=f"Generated for {interaction.user.display_name} · Kairos")

        await interaction.followup.send(embed=embed)

    # ── /sermon_notes ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="sermon_notes",
        description="(Youth Leader/Admin) Upload and AI-summarize your sermon notes (.txt or .md).",
    )
    @app_commands.describe(file="Your sermon notes file (.txt or .md, max 5MB)")
    @guild_rate_limit()
    async def sermon_notes(
        self, interaction: discord.Interaction, file: discord.Attachment
    ) -> None:
        """
        Upload and AI-summarize a sermon notes file.

        Accepts .txt and .md files up to 5MB. Restricted to Youth Leader and
        Administrator roles. Generates a structured summary with title, key
        points, key verses, follow-up readings, and a discussion question.

        Args:
            interaction: The Discord interaction context.
            file: The sermon notes attachment (.txt or .md, max 5MB).
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        if not _has_leader_role(interaction):
            await interaction.response.send_message(
                "❌ This command is restricted to **Youth Leaders** and **Admins**.", ephemeral=True
            )
            return

        # Validate file
        filename = file.filename.lower()
        if not any(filename.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
            await interaction.response.send_message(
                f"❌ Only `.txt` and `.md` files are supported. Got: `{file.filename}`",
                ephemeral=True,
            )
            return

        if file.size > _MAX_FILE_SIZE:
            await interaction.response.send_message(
                f"❌ File too large. Maximum is 5MB. Got: {file.size / 1024 / 1024:.1f}MB",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Download file content
        try:
            raw_bytes = await file.read()
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            await interaction.followup.send(f"❌ Could not read the file: `{exc}`")
            return

        if len(content.strip()) < 10:
            await interaction.followup.send("❌ The file appears to be empty or too short.")
            return

        # Truncate to avoid token limits (~3000 words max)
        truncated = content[:6000]
        was_truncated = len(content) > 6000

        prompt = (
            "Summarize the following sermon notes. Return your summary using this exact structure:\n\n"
            "**Title:** [A suitable sermon title based on the content]\n\n"
            "**Key Points:**\n"
            "1. [key point]\n"
            "2. [key point]\n"
            "3. [key point]\n"
            "(up to 5 key points)\n\n"
            "**Key Verses:** [List the main Bible verses referenced]\n\n"
            "**Follow-Up Readings:**\n"
            "1. [Reference — one sentence why it's relevant]\n"
            "2. [Reference — one sentence why it's relevant]\n"
            "3. [Reference — one sentence why it's relevant]\n\n"
            "**Discussion Question:** [One thoughtful discussion question for a youth group]\n\n"
            "---\n"
            "SERMON NOTES:\n\n"
            f"{truncated}"
        )

        try:
            summary = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ AI error: `{exc}`")
            return

        embed = discord.Embed(
            title=f"📋 Sermon Notes Summary — {file.filename}",
            description=summary[:4000],
            color=discord.Color.dark_teal(),
        )
        embed.set_footer(
            text=(
                f"Summarized for {interaction.user.display_name}"
                + (" · Note: file was truncated at 6000 chars." if was_truncated else "")
            )
        )

        await interaction.followup.send(embed=embed)

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
    await bot.add_cog(Sermon(bot))
