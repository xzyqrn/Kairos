"""
tests/test_cog_chat.py — Unit tests for mention-chat listener behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.chat_listener as chat_listener


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
    message.mentions = []
    message.reply = AsyncMock()
    message.channel.typing = MagicMock(return_value=_TypingContext())
    return message


class TestChatMentionRateLimit:
    async def test_rate_limited_mentions_reply_without_calling_ai(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat_listener.ChatListener(bot)
        message = _make_message()
        message.mentions = [bot.user]

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=12.3))
        respond = AsyncMock()
        monkeypatch.setattr(cog, "_respond", respond)

        await cog.on_message(message)

        respond.assert_not_awaited()
        message.reply.assert_awaited_once()
        sent = message.reply.await_args.args[0]
        assert "Kairos chat" in sent
        assert "**12.3s**" in sent

    async def test_allowed_mentions_flow_through_to_responder(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat_listener.ChatListener(bot)
        message = _make_message(content="<@999>   teach me about grace  ")
        message.mentions = [bot.user]

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        respond = AsyncMock()
        monkeypatch.setattr(cog, "_respond", respond)

        await cog.on_message(message)

        respond.assert_awaited_once_with(
            "teach me about grace",
            guild_id="123",
            user_id="42",
            reply_target=message,
        )

    async def test_mention_only_ping_is_ignored(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat_listener.ChatListener(bot)
        message = _make_message(content="<@999>")
        message.mentions = [bot.user]

        cooldown_check = AsyncMock(return_value=None)
        monkeypatch.setattr(chat_listener, "check_user_cooldown", cooldown_check)
        respond = AsyncMock()
        monkeypatch.setattr(cog, "_respond", respond)

        await cog.on_message(message)

        cooldown_check.assert_not_awaited()
        respond.assert_not_awaited()
        message.reply.assert_not_awaited()

    async def test_bot_authors_are_ignored(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat_listener.ChatListener(bot)
        message = _make_message()
        message.author.bot = True
        message.mentions = [bot.user]

        cooldown_check = AsyncMock(return_value=None)
        monkeypatch.setattr(chat_listener, "check_user_cooldown", cooldown_check)
        respond = AsyncMock()
        monkeypatch.setattr(cog, "_respond", respond)

        await cog.on_message(message)

        cooldown_check.assert_not_awaited()
        respond.assert_not_awaited()
        message.reply.assert_not_awaited()

    async def test_runtime_error_replies_with_fallback(self, monkeypatch):
        bot = MagicMock()
        bot.user = MagicMock(id=999)
        cog = chat_listener.ChatListener(bot)
        message = _make_message(content="<@999> help me pray")
        message.mentions = [bot.user]

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(side_effect=RuntimeError("provider unavailable")),
        )

        await cog.on_message(message)

        message.reply.assert_awaited_once_with(
            "I couldn't think of a response right now. Please try again in a moment.",
            delete_after=15,
        )
