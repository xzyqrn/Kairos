"""
tests/test_cog_chat.py — Unit tests for cogs/chat.py listener rate limiting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.chat as chat


class _TypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _make_message(*, content: str = "<@999> hello") -> MagicMock:
    message = MagicMock()
    message.author.bot = False
    message.author.id = 42
    message.guild.id = 123
    message.content = content
    message.reply = AsyncMock()
    message.channel.typing = MagicMock(return_value=_TypingContext())
    return message


class TestChatMentionRateLimit:
    async def test_rate_limited_mentions_reply_without_calling_ai(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat.Chat(bot)
        message = _make_message()
        message.mentions = [bot.user]

        monkeypatch.setattr(chat.ai_client, "get_guild_config", AsyncMock(return_value={"provider": "openai"}))
        monkeypatch.setattr(chat, "check_user_cooldown", AsyncMock(return_value=12.3))
        cog._respond = AsyncMock()

        await cog.on_message(message)

        cog._respond.assert_not_awaited()
        message.reply.assert_awaited_once()
        sent = message.reply.await_args.args[0]
        assert "Kairos chat" in sent
        assert "**12.3s**" in sent

    async def test_allowed_mentions_flow_through_to_responder(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat.Chat(bot)
        message = _make_message(content="<@999>   teach me about grace  ")
        message.mentions = [bot.user]

        monkeypatch.setattr(chat.ai_client, "get_guild_config", AsyncMock(return_value={"provider": "openai"}))
        monkeypatch.setattr(chat, "check_user_cooldown", AsyncMock(return_value=None))
        cog._respond = AsyncMock()

        await cog.on_message(message)

        cog._respond.assert_awaited_once_with(
            "teach me about grace",
            guild_id="123",
            user_id="42",
            reply_target=message,
        )
