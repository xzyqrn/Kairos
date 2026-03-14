from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils.ai_client import ai_client
from utils.channel_context import (
    MentionContext,
    build_channel_memory_rollup_prompt,
    build_mention_context,
    build_mention_prompt,
    clean_mention_text,
)
from utils.channel_memory_store import channel_memory_store
from utils.rate_limiter import check_user_cooldown, format_cooldown_message
from utils.response import trim_response

log = logging.getLogger("kairos.chat_listener")


class ChatListener(commands.Cog):
    """
    A cog that listens for mentions and provides AI-powered conversational responses.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _clean_prompt(content: str, bot_id: int) -> str:
        return clean_mention_text(content, bot_id)

    async def _respond(
        self,
        prompt: str,
        *,
        guild_id: str,
        user_id: str,
        reply_target: discord.Message,
    ) -> str | None:
        async with reply_target.channel.typing():
            try:
                response_text = await ai_client.generate_response(
                    prompt=prompt,
                    guild_id=guild_id,
                    user_id=user_id,
                )
            except RuntimeError as exc:
                log.warning("ChatListener AI error for guild %s: %s", guild_id, exc)
                await reply_target.reply(
                    "I couldn't think of a response right now. Please try again in a moment.",
                    delete_after=15,
                )
                return None
            except Exception as exc:
                log.exception(
                    "An unexpected error occurred in ChatListener for guild %s: %s",
                    guild_id,
                    exc,
                )
                await reply_target.reply(
                    "I ran into an unexpected error. Please try again in a moment.",
                    delete_after=15,
                )
                return None

        reply_text = trim_response(response_text, "mention_chat")
        await reply_target.reply(reply_text)
        return reply_text

    def _schedule_memory_refresh(
        self,
        *,
        message: discord.Message,
        mention_context: MentionContext,
        response_text: str,
    ) -> None:
        task = asyncio.create_task(
            self._refresh_channel_memory(
                message=message,
                mention_context=mention_context,
                response_text=response_text,
            )
        )
        task.add_done_callback(self._log_memory_refresh_error)

    @staticmethod
    def _log_memory_refresh_error(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as exc:
            log.warning("Channel memory refresh failed: %s", exc)

    async def _refresh_channel_memory(
        self,
        *,
        message: discord.Message,
        mention_context: MentionContext,
        response_text: str,
    ) -> None:
        if message.guild is None:
            return

        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)

        existing_summary = await channel_memory_store.get_summary(guild_id, channel_id)
        rollup_prompt = build_channel_memory_rollup_prompt(
            existing_summary.summary if existing_summary is not None else None,
            mention_context.recent_messages,
            current_author_name=message.author.display_name,
            current_text=mention_context.current_text,
            response_text=response_text,
        )

        summary_text = await ai_client.generate_response(
            prompt=rollup_prompt,
            guild_id=guild_id,
        )
        summary_text = trim_response(summary_text, "channel_memory")
        await channel_memory_store.upsert_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            summary=summary_text,
            last_message_id=int(message.id),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Handles incoming messages to check for bot mentions.
        """
        # Ignore bot-authored messages to prevent reply loops.
        if getattr(message.author, "bot", False):
            return

        bot_user = self.bot.user
        if bot_user is None:
            return

        # Mention-chat is only supported in guild text conversations.
        if message.guild is None or bot_user not in message.mentions:
            return

        prompt = self._clean_prompt(message.content, bot_user.id)

        if not prompt:
            return

        retry_after = await check_user_cooldown(
            "mention_chat",
            guild_id=message.guild.id,
            user_id=message.author.id,
        )
        if retry_after is not None:
            await message.reply(
                format_cooldown_message(retry_after, action="Kairos chat"),
                delete_after=15,
            )
            return

        mention_context: MentionContext | None = None
        final_prompt = prompt

        try:
            mention_context = await build_mention_context(message, bot_user)
        except Exception as exc:
            log.warning(
                "Falling back to stateless mention prompt in guild %s: %s",
                message.guild.id,
                exc,
            )

        if mention_context is not None:
            channel_summary: str | None = None
            try:
                stored_summary = await channel_memory_store.get_summary(
                    str(message.guild.id),
                    str(message.channel.id),
                )
                if stored_summary is not None:
                    channel_summary = stored_summary.summary
            except Exception as exc:
                log.warning(
                    "Could not load channel memory for guild %s channel %s: %s",
                    message.guild.id,
                    message.channel.id,
                    exc,
                )

            final_prompt = build_mention_prompt(
                mention_context.current_text,
                mention_context.recent_messages,
                channel_summary=channel_summary,
            )

        response_text = await self._respond(
            final_prompt,
            guild_id=str(message.guild.id),
            user_id=str(message.author.id),
            reply_target=message,
        )
        if response_text and mention_context is not None:
            self._schedule_memory_refresh(
                message=message,
                mention_context=mention_context,
                response_text=response_text,
            )


async def setup(bot: commands.Bot) -> None:
    """
    The setup function to add the cog to the bot.
    """
    await bot.add_cog(ChatListener(bot))
