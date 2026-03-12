from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from utils.ai_client import ai_client

log = logging.getLogger("kairos.chat_listener")


class ChatListener(commands.Cog):
    """
    A cog that listens for mentions and provides AI-powered conversational responses.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Handles incoming messages to check for bot mentions.
        """
        # 1. Ignore messages from the bot itself to prevent loops
        if message.author == self.bot.user:
            return

        # 2. Check if the bot is mentioned
        if not self.bot.user or not self.bot.user.mentioned_in(message):
            return
            
        # 3. Ensure the message is from a guild
        if not message.guild:
            return

        # 4. Clean the message content to create a prompt
        # Removes the bot's mention and strips leading/trailing whitespace
        prompt = re.sub(f"<@!?{self.bot.user.id}>", "", message.content).strip()

        # 5. If the prompt is empty after cleaning, do nothing
        # (This happens if the message was just a ping with no text)
        if not prompt:
            return

        # 6. Generate an AI response
        async with message.channel.typing():
            try:
                response_text = await ai_client.generate_response(
                    prompt=prompt,
                    guild_id=str(message.guild.id),
                    user_id=str(message.author.id),
                )
                await message.reply(response_text)
            except RuntimeError as exc:
                log.warning("ChatListener AI error for guild %s: %s", message.guild.id, exc)
                await message.reply("I couldn't think of a response right now. Please try again in a moment.", delete_after=15)
            except Exception as exc:
                log.exception("An unexpected error occurred in ChatListener for guild %s: %s", message.guild.id, exc)


async def setup(bot: commands.Bot) -> None:
    """
    The setup function to add the cog to the bot.
    """
    await bot.add_cog(ChatListener(bot))
