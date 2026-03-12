from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from utils.ai_client import ai_client
from utils.rate_limiter import check_user_cooldown, format_cooldown_message

log = logging.getLogger("kairos.chat_listener")


class ChatListener(commands.Cog):
    """
    A cog that listens for mentions and provides AI-powered conversational responses.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def _clean_prompt(content: str, bot_id: int) -> str:
        return re.sub(fr"<@!?{bot_id}>", "", content).strip()

    async def _respond(
        self,
        prompt: str,
        *,
        guild_id: str,
        user_id: str,
        reply_target: discord.Message,
    ) -> None:
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
                return
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
                return

        await reply_target.reply(response_text)

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

        await self._respond(
            prompt,
            guild_id=str(message.guild.id),
            user_id=str(message.author.id),
            reply_target=message,
        )


async def setup(bot: commands.Bot) -> None:
    """
    The setup function to add the cog to the bot.
    """
    await bot.add_cog(ChatListener(bot))
