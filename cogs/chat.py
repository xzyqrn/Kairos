"""
cogs/chat.py — Slash commands for AI chat and history management.

Provides:
  /ask [question] — Ask Kairos anything (20-second cooldown)
  /clear_history — Clear your personal conversation history with the bot

NOTE: All conversational mention-based chat is now handled by cogs/chat_listener.py
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.history import history_store
from utils.rate_limiter import (
    cooldown,
    guild_rate_limit,
    handle_cooldown_error,
)

log = logging.getLogger("kairos.chat")


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _build_history_prompt(
        self, guild_id: str, user_id: str, current_message: str
    ) -> str:
        history = await history_store.get(guild_id=guild_id, user_id=user_id)
        return history_store.build_prompt(history, current_message)

    @app_commands.command(
        name="ask",
        description="Ask Kairos a Bible, faith, or life question in plain language.",
    )
    @app_commands.describe(
        question="Ask anything, like 'How do I pray?' or 'What is grace?'",
    )
    @cooldown("ask")
    @guild_rate_limit()
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        prompt = await self._build_history_prompt(
            str(interaction.guild_id), str(interaction.user.id), question
        )

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError:
            await interaction.followup.send(
                "⚠️ I'm having trouble reaching my AI provider right now. Please try again in a moment."
            )
            return

        await history_store.push(
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
            user_msg=question,
            bot_reply=response,
        )

        embed = discord.Embed(
            description=response[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_author(
            name=f"Q: {question[:100]}",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.set_footer(text="Kairos · powered by faith 🕊️")

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="clear_history",
        description="Clear the past chat messages Kairos remembers for you.",
    )
    async def clear_history(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        deleted = await history_store.clear(
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
        )
        if deleted:
            await interaction.response.send_message(
                "✅ I cleared your saved chat history with Kairos.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ℹ️ There isn't any saved chat history to clear yet.",
                ephemeral=True,
            )

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
    await bot.add_cog(Chat(bot))
