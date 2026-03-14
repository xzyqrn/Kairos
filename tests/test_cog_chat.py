"""
tests/test_cog_chat.py — Unit tests for mention-chat listener behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("discord")
import cogs.chat_listener as chat_listener
from utils.channel_context import MentionContext, MentionContextMessage
from utils.channel_memory_store import ChannelMemoryEntry


class _TypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _AsyncHistory:
    def __init__(self, messages):
        self._messages = list(messages)

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _make_author(author_id: int, name: str, *, bot: bool = False):
    return SimpleNamespace(id=author_id, display_name=name, bot=bot)


def _make_history_message(
    message_id: int,
    *,
    content: str,
    author,
):
    return SimpleNamespace(
        id=message_id,
        content=content,
        clean_content=content,
        author=author,
        attachments=[],
        type=SimpleNamespace(name="default"),
        reference=None,
    )


def _make_message(*, content: str = "<@999> hello") -> MagicMock:
    message = MagicMock()
    message.id = 99
    message.author = _make_author(42, "Noah")
    message.guild.id = 123
    message.content = content
    message.clean_content = content
    message.mentions = []
    message.reply = AsyncMock()
    message.channel.typing = MagicMock(return_value=_TypingContext())
    message.channel.id = 456
    message.channel.history = MagicMock(return_value=_AsyncHistory([]))
    message.channel.fetch_message = AsyncMock()
    message.reference = None
    message.type = SimpleNamespace(name="default")
    message.attachments = []
    return message


def _make_cog(monkeypatch):
    bot = MagicMock()
    bot.user = _make_author(999, "Kairos", bot=True)
    cog = chat_listener.ChatListener(bot)
    monkeypatch.setattr(
        chat_listener.channel_memory_store,
        "get_summary",
        AsyncMock(return_value=None),
    )
    cog._schedule_memory_refresh = MagicMock()
    return bot, cog


class TestChatMentionRateLimit:
    async def test_rate_limited_mentions_reply_without_calling_ai_or_history(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message()
        message.mentions = [bot.user]

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=12.3))
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(return_value="unused"),
        )

        await cog.on_message(message)

        message.channel.history.assert_not_called()
        message.reply.assert_awaited_once()
        sent = message.reply.await_args.args[0]
        assert "Kairos chat" in sent
        assert "**12.3s**" in sent

    async def test_contextual_prompt_includes_recent_channel_messages(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999>   what should I say back?  ")
        message.mentions = [bot.user]

        older = _make_history_message(
            1,
            content="we've been talking about forgiveness all night",
            author=_make_author(100, "Jay"),
        )
        newer = _make_history_message(
            2,
            content="I still don't know how to start the conversation",
            author=_make_author(101, "Mia"),
        )
        message.channel.history = MagicMock(return_value=_AsyncHistory([newer, older]))

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        generate = AsyncMock(return_value="Context-aware reply")
        monkeypatch.setattr(chat_listener.ai_client, "generate_response", generate)

        await cog.on_message(message)

        prompt = generate.await_args.kwargs["prompt"]
        assert "[Recent channel context:]" in prompt
        assert "Jay: we've been talking about forgiveness all night" in prompt
        assert "Mia: I still don't know how to start the conversation" in prompt
        assert "[Current message addressed to Kairos:]" in prompt
        assert "what should I say back?" in prompt
        cog._schedule_memory_refresh.assert_called_once()
        message.reply.assert_awaited_once_with("Context-aware reply")

    async def test_long_term_channel_memory_is_included_in_prompt(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999> what should we focus on?")
        message.mentions = [bot.user]
        message.channel.history = MagicMock(return_value=_AsyncHistory([]))

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        monkeypatch.setattr(
            chat_listener.channel_memory_store,
            "get_summary",
            AsyncMock(
                return_value=ChannelMemoryEntry(
                    guild_id="123",
                    channel_id="456",
                    summary="They have been discussing forgiveness after a friend conflict.",
                    last_message_id=88,
                    updated_at="2026-03-14T12:00:00Z",
                )
            ),
        )
        generate = AsyncMock(return_value="Context-aware reply")
        monkeypatch.setattr(chat_listener.ai_client, "generate_response", generate)

        await cog.on_message(message)

        prompt = generate.await_args.kwargs["prompt"]
        assert "[Long-term channel memory:]" in prompt
        assert "They have been discussing forgiveness after a friend conflict." in prompt

    async def test_other_bots_excluded_but_kairos_message_kept(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999> what do you mean by that?")
        message.mentions = [bot.user]

        human = _make_history_message(
            1,
            content="can somebody explain grace",
            author=_make_author(100, "Jay"),
        )
        kairos_msg = _make_history_message(
            2,
            content="Grace is God's undeserved favor.",
            author=_make_author(999, "Kairos", bot=True),
        )
        other_bot = _make_history_message(
            3,
            content="Scheduled reminder",
            author=_make_author(500, "Reminder", bot=True),
        )
        message.channel.history = MagicMock(
            return_value=_AsyncHistory([other_bot, kairos_msg, human])
        )

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        generate = AsyncMock(return_value="reply")
        monkeypatch.setattr(chat_listener.ai_client, "generate_response", generate)

        await cog.on_message(message)

        prompt = generate.await_args.kwargs["prompt"]
        assert "Jay: can somebody explain grace" in prompt
        assert "Kairos: Grace is God's undeserved favor." in prompt
        assert "Scheduled reminder" not in prompt

    async def test_mention_only_ping_is_ignored(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999>")
        message.mentions = [bot.user]

        cooldown_check = AsyncMock(return_value=None)
        monkeypatch.setattr(chat_listener, "check_user_cooldown", cooldown_check)
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(return_value="unused"),
        )

        await cog.on_message(message)

        cooldown_check.assert_not_awaited()
        message.channel.history.assert_not_called()
        message.reply.assert_not_awaited()

    async def test_bot_authors_are_ignored(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message()
        message.author = _make_author(42, "Noah", bot=True)
        message.mentions = [bot.user]

        cooldown_check = AsyncMock(return_value=None)
        monkeypatch.setattr(chat_listener, "check_user_cooldown", cooldown_check)
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(return_value="unused"),
        )

        await cog.on_message(message)

        cooldown_check.assert_not_awaited()
        message.channel.history.assert_not_called()
        message.reply.assert_not_awaited()

    async def test_runtime_error_replies_with_fallback(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
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

    async def test_context_build_failure_falls_back_to_stateless_prompt(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999> help me pray")
        message.mentions = [bot.user]
        message.channel.history = MagicMock(side_effect=RuntimeError("history unavailable"))

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        generate = AsyncMock(return_value="Fallback reply")
        monkeypatch.setattr(chat_listener.ai_client, "generate_response", generate)

        await cog.on_message(message)

        assert generate.await_args.kwargs["prompt"] == "help me pray"
        message.reply.assert_awaited_once_with("Fallback reply")

    async def test_long_provider_reply_is_trimmed_before_send(self, monkeypatch):
        bot, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999> give me a lot of detail")
        message.mentions = [bot.user]

        monkeypatch.setattr(chat_listener, "check_user_cooldown", AsyncMock(return_value=None))
        long_reply = "word " * 600
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(return_value=long_reply),
        )

        await cog.on_message(message)

        sent = message.reply.await_args.args[0]
        assert len(sent) <= 1800
        assert sent.endswith("…")

    async def test_refresh_channel_memory_summarizes_and_saves(self, monkeypatch):
        _, cog = _make_cog(monkeypatch)
        message = _make_message(content="<@999> what should we do first?")
        mention_context = MentionContext(
            current_text="what should we do first?",
            recent_messages=(
                MentionContextMessage(
                    author_name="Jay",
                    content="we're trying to reconcile after a fight",
                ),
            ),
        )

        monkeypatch.setattr(
            chat_listener.channel_memory_store,
            "get_summary",
            AsyncMock(return_value=None),
        )
        upsert_summary = AsyncMock()
        monkeypatch.setattr(
            chat_listener.channel_memory_store,
            "upsert_summary",
            upsert_summary,
        )
        monkeypatch.setattr(
            chat_listener.ai_client,
            "generate_response",
            AsyncMock(return_value="They have been discussing reconciliation after a recent fight."),
        )

        await cog._refresh_channel_memory(
            message=message,
            mention_context=mention_context,
            response_text="Start with humility and a willingness to listen.",
        )

        prompt = chat_listener.ai_client.generate_response.await_args.kwargs["prompt"]
        assert "[Previous long-term memory:]" in prompt
        assert "Jay: we're trying to reconcile after a fight" in prompt
        assert "Noah: what should we do first?" in prompt
        assert "Kairos: Start with humility and a willingness to listen." in prompt
        upsert_summary.assert_awaited_once_with(
            guild_id="123",
            channel_id="456",
            summary="They have been discussing reconciliation after a recent fight.",
            last_message_id=99,
        )
