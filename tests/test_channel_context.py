from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import utils.channel_context as channel_context


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


def _make_message(
    message_id: int,
    *,
    content: str,
    author,
    clean_content: str | None = None,
    message_type: str = "default",
    reference=None,
):
    return SimpleNamespace(
        id=message_id,
        content=content,
        clean_content=clean_content if clean_content is not None else content,
        author=author,
        attachments=[],
        type=SimpleNamespace(name=message_type),
        reference=reference,
    )


class TestMentionContext:
    async def test_orders_messages_oldest_first_and_cleans_current_text(self):
        bot_user = SimpleNamespace(id=999)
        older = _make_message(
            1,
            content="we have been talking about grace",
            author=_make_author(10, "Jay"),
        )
        newer = _make_message(
            2,
            content="I still do not get it",
            author=_make_author(11, "Mia"),
        )
        current = _make_message(
            3,
            content="<@999> what does that mean?",
            author=_make_author(12, "Noah"),
        )

        channel = MagicMock()
        channel.history = MagicMock(return_value=_AsyncHistory([newer, older]))
        current.channel = channel

        result = await channel_context.build_mention_context(current, bot_user)

        assert result.current_text == "what does that mean?"
        assert [msg.author_name for msg in result.recent_messages] == ["Jay", "Mia"]
        assert [msg.content for msg in result.recent_messages] == [
            "we have been talking about grace",
            "I still do not get it",
        ]

    async def test_excludes_other_bots_but_keeps_kairos_messages(self):
        bot_user = SimpleNamespace(id=999)
        human = _make_message(
            1,
            content="can someone explain grace",
            author=_make_author(10, "Jay"),
        )
        kairos = _make_message(
            2,
            content="Grace is God's undeserved favor.",
            author=_make_author(999, "Kairos", bot=True),
        )
        other_bot = _make_message(
            3,
            content="server reminder",
            author=_make_author(500, "Reminder", bot=True),
        )
        current = _make_message(
            4,
            content="<@999> can you explain that more?",
            author=_make_author(12, "Noah"),
        )

        channel = MagicMock()
        channel.history = MagicMock(return_value=_AsyncHistory([other_bot, kairos, human]))
        current.channel = channel

        result = await channel_context.build_mention_context(current, bot_user)

        assert [msg.author_name for msg in result.recent_messages] == ["Jay", "Kairos"]
        assert "server reminder" not in {
            msg.content for msg in result.recent_messages
        }

    async def test_includes_replied_to_message_outside_history_window(self):
        bot_user = SimpleNamespace(id=999)
        reply_target = _make_message(
            40,
            content="we were comparing grace and mercy",
            author=_make_author(14, "Ella"),
        )
        current = _make_message(
            41,
            content="<@999> which one fits here?",
            author=_make_author(12, "Noah"),
            reference=SimpleNamespace(resolved=reply_target),
        )

        channel = MagicMock()
        channel.history = MagicMock(return_value=_AsyncHistory([]))
        current.channel = channel

        result = await channel_context.build_mention_context(current, bot_user)

        assert result.recent_messages[0].author_name == "Ella"
        assert result.recent_messages[0].content == "we were comparing grace and mercy"

    async def test_truncates_per_message_and_total_budget(self):
        bot_user = SimpleNamespace(id=999)
        current = _make_message(
            100,
            content="<@999> what should I say back?",
            author=_make_author(12, "Noah"),
        )

        history_messages = [
            _make_message(
                index,
                content=f"msg {index} " + ("x" * 500),
                author=_make_author(index, f"User {index}"),
            )
            for index in range(1, 35)
        ]

        channel = MagicMock()
        channel.history = MagicMock(
            return_value=_AsyncHistory(list(reversed(history_messages)))
        )
        current.channel = channel

        result = await channel_context.build_mention_context(current, bot_user)

        assert all(
            len(msg.content) <= channel_context.MAX_CONTEXT_MESSAGE_CHARS
            for msg in result.recent_messages
        )
        rendered = "\n".join(
            f"{msg.author_name}: {msg.content}" for msg in result.recent_messages
        )
        assert len(rendered) <= channel_context.MAX_CONTEXT_TOTAL_CHARS


class TestPromptBuilders:
    def test_mention_prompt_includes_long_term_memory(self):
        prompt = channel_context.build_mention_prompt(
            "what should I say back?",
            [channel_context.MentionContextMessage("Jay", "we are talking about forgiveness")],
            channel_summary="This channel has been discussing forgiveness after conflict.",
        )

        assert "[Long-term channel memory:]" in prompt
        assert "This channel has been discussing forgiveness after conflict." in prompt
        assert "Jay: we are talking about forgiveness" in prompt

    def test_channel_memory_rollup_prompt_includes_previous_summary_and_new_discussion(self):
        prompt = channel_context.build_channel_memory_rollup_prompt(
            "They have been discussing grace and whether to reconcile.",
            [channel_context.MentionContextMessage("Jay", "I want to make peace but I am nervous.")],
            current_author_name="Noah",
            current_text="what should I say first?",
            response_text="Start with honesty and a willingness to listen.",
        )

        assert "[Previous long-term memory:]" in prompt
        assert "They have been discussing grace and whether to reconcile." in prompt
        assert "Jay: I want to make peace but I am nervous." in prompt
        assert "Noah: what should I say first?" in prompt
        assert "Kairos: Start with honesty and a willingness to listen." in prompt
