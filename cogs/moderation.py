"""
cogs/moderation.py — Content moderation with a configurable blocklist.

Behavior:
  - on_message listener checks all server messages against the blocklist
  - On match: silently delete the message + DM the user with community standards
  - Blocklist is stored in memory; can be extended via data/blocklist.json if desired
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import aiofiles
import discord
from discord.ext import commands

log = logging.getLogger("kairos.moderation")

_BLOCKLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "blocklist.json"

# Default blocklist — extend via data/blocklist.json
_DEFAULT_BLOCKLIST: list[str] = [
    # Profanity and slurs are intentionally omitted from this public file.
    # Add your own words to data/blocklist.json:
    # { "words": ["word1", "word2", ...] }
]


async def _load_blocklist() -> list[str]:
    """Load blocklist from JSON file, merging with defaults."""
    words = list(_DEFAULT_BLOCKLIST)
    if not _BLOCKLIST_PATH.exists():
        return words
    try:
        async with aiofiles.open(_BLOCKLIST_PATH, encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw)
        custom: list = data.get("words", [])
        words.extend(str(w).lower().strip() for w in custom if w)
    except Exception as exc:
        log.warning("Could not load blocklist.json: %s", exc)
    return list(set(words))  # deduplicate


def _contains_blocked_word(text: str, blocklist: list[str]) -> str | None:
    """Return the matched word if found, otherwise None."""
    lower_text = text.lower()
    for word in blocklist:
        if not word:
            continue
        # whole-word match (allow punctuation around it)
        pattern = r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])"
        if re.search(pattern, lower_text):
            return word
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._blocklist: list[str] = []

    async def cog_load(self) -> None:
        self._blocklist = await _load_blocklist()
        log.info("Moderation blocklist loaded: %d word(s).", len(self._blocklist))

    async def _dm_user(self, user: discord.Member) -> None:
        embed = discord.Embed(
            title="📋 Community Standards Reminder",
            description=(
                "Hey! One of your recent messages was removed because it may have contained "
                "language that goes against our community standards.\n\n"
                "Our server is a **safe, encouraging space** for young Christians. "
                "Please keep all messages respectful, uplifting, and appropriate for all ages.\n\n"
                "\"Let no corrupt communication proceed out of your mouth, but that which is good "
                "to the use of edifying, that it may minister grace unto the hearers.\" — Ephesians 4:29\n\n"
                "If you believe this was a mistake, please reach out to a server admin."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="This message was sent privately — no one else saw this.")
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass  # User has DMs disabled — that's fine

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots, DMs
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not isinstance(message.author, discord.Member):
            return

        if not self._blocklist:
            return

        matched = _contains_blocked_word(message.content, self._blocklist)
        if matched is None:
            return

        # Delete the message
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            log.warning("Could not delete violating message %s: %s", message.id, exc)
            return

        log.info(
            "Deleted message from %s (%s) in #%s — matched: %s",
            message.author,
            message.author.id,
            message.channel.name,
            matched,
        )

        await self._dm_user(message.author)

    @commands.Cog.listener()
    async def on_message_edit(self, _before: discord.Message, after: discord.Message) -> None:
        """Re-check edited messages using the same on_message handler."""
        await self.on_message(after)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
