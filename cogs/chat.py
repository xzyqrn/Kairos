"""
cogs/chat.py — Conversational AI listener (Mentions ONLY).

Listens for:
  • @mentions of the bot in any channel

Also provides:
  /ask [question] — Ask Kairos anything (20-second cooldown)

Features:
  • Per-user persistent SQLite conversation history (last 5 exchanges)
  • Language preference applied from data/lang_prefs.json
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.history import history_store
from utils.rate_limiter import (
    check_user_cooldown,
    cooldown,
    format_cooldown_message,
    guild_rate_limit,
    handle_cooldown_error,
)

log = logging.getLogger("kairos.chat")


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Conversation history ──────────────────────────────────────────────────

    async def _build_history_prompt(
        self, guild_id: str, user_id: str, current_message: str
    ) -> str:
        history = await history_store.get(guild_id=guild_id, user_id=user_id)
        return history_store.build_prompt(history, current_message)

    # ── Core responder ────────────────────────────────────────────────────────

    async def _respond(
        self,
        content: str,
        *,
        guild_id: str | None,
        user_id: str,
        reply_target: discord.Message | None = None,
        interaction: discord.Interaction | None = None,
    ) -> None:
        """Generate an AI response and send it to the appropriate target."""
        if not guild_id:
            return

        prompt = await self._build_history_prompt(guild_id, user_id, content)

        try:
            response = await ai_client.generate_response(
                prompt=prompt,
                guild_id=guild_id,
                user_id=user_id,
            )
        except RuntimeError as exc:
            log.warning("AI error in chat for guild %s: %s", guild_id, exc)
            error_msg = (
                "⚠️ I'm having trouble reaching my AI provider right now. "
                "Please try again in a moment."
            )
            if interaction:
                if interaction.response.is_done():
                    await interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(error_msg)
            elif reply_target:
                await reply_target.reply(error_msg, mention_author=False)
            return

        await history_store.push(
            guild_id=guild_id,
            user_id=user_id,
            user_msg=content,
            bot_reply=response,
        )

        # Chunk at 2000 chars for Discord message limit
        chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]

        if interaction:
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)
        elif reply_target:
            await reply_target.reply(chunks[0], mention_author=False)
            for chunk in chunks[1:]:
                await reply_target.channel.send(chunk)

    # ── on_message listener ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        # ONLY respond if significantly mentioned
        bot_user = self.bot.user
        if bot_user is None:
            return
        is_mention = bot_user in message.mentions

        if not is_mention:
            return

        guild_id = str(message.guild.id) if message.guild else None
        if not guild_id:
            # DM logic simplified: only if mentioned (though you can't really "mention" in a basic DM usually)
            return

        config = await ai_client.get_guild_config(guild_id)
        if not config:
            return

        # Strip @mention from message content
        content = message.content
        content = content.replace(f"<@{bot_user.id}>", "").replace(
            f"<@!{bot_user.id}>", ""
        ).strip()

        if not content:
            await message.reply("Yes? 😊 How can I help you today?", mention_author=False)
            return

        retry_after = await check_user_cooldown(
            "mention_chat",
            guild_id=message.guild.id,
            user_id=message.author.id,
        )
        if retry_after is not None:
            log.info(
                "Rate limit hit: user=%s guild=%s command=mention_chat retry_after=%.1fs",
                message.author.id,
                message.guild.id,
                retry_after,
            )
            await message.reply(
                format_cooldown_message(retry_after, action="Kairos chat"),
                mention_author=False,
            )
            return

        async with message.channel.typing():
            await self._respond(
                content,
                guild_id=guild_id,
                user_id=str(message.author.id),
                reply_target=message,
            )

    # ── /ask ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="ask", description="Ask Kairos anything — Bible, faith, life questions.")
    @app_commands.describe(question="Your question for Kairos")
    @cooldown("ask")
    @guild_rate_limit()
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
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
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ `{exc}`")
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

    # ── /clear_history ────────────────────────────────────────────────────────

    @app_commands.command(
        name="clear_history",
        description="Clear your conversation history with Kairos.",
    )
    async def clear_history(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        deleted = await history_store.clear(
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
        )
        if deleted:
            await interaction.response.send_message(
                "✅ Your conversation history with Kairos has been cleared.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ℹ️ You have no conversation history to clear.",
                ephemeral=True,
            )

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
    await bot.add_cog(Chat(bot))
