from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from utils.locale import locale

if TYPE_CHECKING:
    import discord


log = logging.getLogger("kairos.channel_context")

RECENT_CONTEXT_LIMIT = 30
_HISTORY_FETCH_LIMIT = RECENT_CONTEXT_LIMIT - 1
MAX_CONTEXT_MESSAGE_CHARS = 300
MAX_CONTEXT_TOTAL_CHARS = 6_000

_USER_MENTION_RE = re.compile(r"<@!?\d+>")
_ROLE_MENTION_RE = re.compile(r"<@&\d+>")
_CHANNEL_MENTION_RE = re.compile(r"<#\d+>")

_FALLBACK_PROMPT_TEMPLATE = (
    "A channel conversation has been happening. Use the long-term memory and "
    "recent context below only if they help answer the current message.\n\n"
    "[Long-term channel memory:]\n"
    "{long_term_memory}\n\n"
    "[Recent channel context:]\n"
    "{recent_context}\n\n"
    "[Current message addressed to Kairos:]\n"
    "{current_message}\n\n"
    "[Response rules:]\n"
    "- Answer the current user directly.\n"
    "- Use the recent channel context only when it helps.\n"
    "- If the current message is ambiguous, infer the topic from context first.\n"
    "- If the context is still insufficient, say so briefly instead of guessing.\n"
    "- Do not claim to know messages older than the supplied context window."
)

_MEMORY_ROLLUP_FALLBACK_TEMPLATE = (
    "You are updating Kairos's bounded long-term memory for one Discord channel.\n\n"
    "[Previous long-term memory:]\n"
    "{previous_summary}\n\n"
    "[Latest discussion to fold in:]\n"
    "{recent_discussion}\n\n"
    "[Instructions:]\n"
    "- Produce a concise rolling summary for future replies.\n"
    "- Focus on ongoing topics, unresolved questions, decisions, and useful follow-ups.\n"
    "- Prefer topics over private personal details.\n"
    "- Mention names only when they materially help future context.\n"
    "- Keep it under 180 words.\n"
    "- Return summary text only."
)


@dataclass(frozen=True, slots=True)
class MentionContextMessage:
    author_name: str
    content: str
    message_id: int | str | None = None


@dataclass(frozen=True, slots=True)
class MentionContext:
    current_text: str
    recent_messages: tuple[MentionContextMessage, ...]


def clean_mention_text(content: str, bot_id: int) -> str:
    without_bot = re.sub(fr"<@!?{bot_id}>", "", content).strip()
    return _sanitize_discord_markup(without_bot)


def build_mention_prompt(
    current_text: str,
    context_messages: tuple[MentionContextMessage, ...] | list[MentionContextMessage],
    *,
    channel_summary: str | None = None,
) -> str:
    rendered_context = "\n".join(
        f"{msg.author_name}: {msg.content}" for msg in context_messages
    )
    if not rendered_context:
        rendered_context = "(No recent channel context.)"
    rendered_summary = channel_summary.strip() if channel_summary and channel_summary.strip() else "(No long-term channel memory yet.)"

    template = locale.prompt(
        "mention_chat",
        long_term_memory=rendered_summary,
        recent_context=rendered_context,
        current_message=current_text,
    )
    if not template:
        template = _FALLBACK_PROMPT_TEMPLATE.format(
            long_term_memory=rendered_summary,
            recent_context=rendered_context,
            current_message=current_text,
        )

    return template


def build_channel_memory_rollup_prompt(
    previous_summary: str | None,
    context_messages: tuple[MentionContextMessage, ...] | list[MentionContextMessage],
    *,
    current_author_name: str,
    current_text: str,
    response_text: str,
) -> str:
    discussion_lines = [f"{msg.author_name}: {msg.content}" for msg in context_messages]
    discussion_lines.append(f"{current_author_name}: {current_text}")
    discussion_lines.append(f"Kairos: {response_text}")
    rendered_discussion = "\n".join(discussion_lines)
    rendered_summary = previous_summary.strip() if previous_summary and previous_summary.strip() else "(No long-term channel memory yet.)"

    template = locale.prompt(
        "channel_memory_rollup",
        previous_summary=rendered_summary,
        recent_discussion=rendered_discussion,
    )
    if not template:
        template = _MEMORY_ROLLUP_FALLBACK_TEMPLATE.format(
            previous_summary=rendered_summary,
            recent_discussion=rendered_discussion,
        )
    return template


async def build_mention_context(
    message: discord.Message,
    bot_user: discord.ClientUser | discord.Member | discord.User,
) -> MentionContext:
    current_text = clean_mention_text(message.content, bot_user.id)

    recent_messages: list[tuple[bool, MentionContextMessage]] = []
    seen_ids: set[int | str] = set()

    replied_to = await _resolve_replied_to_message(message)
    if replied_to is not None:
        normalized = _normalize_context_message(replied_to, bot_user.id)
        if normalized is not None:
            recent_messages.append((True, normalized))
            seen_ids.add(_message_identity(replied_to))

    history_items: list[discord.Message] = []
    async for previous in message.channel.history(
        limit=_HISTORY_FETCH_LIMIT,
        before=message,
        oldest_first=False,
    ):
        history_items.append(previous)

    history_items.reverse()

    for previous in history_items:
        identity = _message_identity(previous)
        if identity in seen_ids:
            continue

        normalized = _normalize_context_message(previous, bot_user.id)
        if normalized is None:
            continue

        recent_messages.append((False, normalized))
        seen_ids.add(identity)

    trimmed_messages = _enforce_total_budget(recent_messages)
    return MentionContext(
        current_text=current_text,
        recent_messages=tuple(trimmed_messages),
    )


def _sanitize_discord_markup(text: str) -> str:
    sanitized = _USER_MENTION_RE.sub("@user", text)
    sanitized = _ROLE_MENTION_RE.sub("@role", sanitized)
    sanitized = _CHANNEL_MENTION_RE.sub("#channel", sanitized)
    return " ".join(sanitized.split())


def _message_identity(message: Any) -> int | str:
    message_id = getattr(message, "id", None)
    if isinstance(message_id, (int, str)):
        return message_id
    return f"obj:{id(message)}"


def _display_name(author: Any) -> str:
    for attr in ("display_name", "global_name", "name"):
        value = getattr(author, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    author_id = getattr(author, "id", None)
    if author_id is not None:
        return f"user-{author_id}"
    return "Unknown"


def _is_default_message(message: Any) -> bool:
    message_type = getattr(message, "type", None)
    if message_type is None:
        return True

    type_name = getattr(message_type, "name", None)
    if isinstance(type_name, str):
        return type_name == "default"

    return str(message_type) == "default"


def _normalize_context_message(
    message: Any,
    bot_user_id: int,
) -> MentionContextMessage | None:
    author = getattr(message, "author", None)
    if author is None:
        return None

    author_id = getattr(author, "id", None)
    is_bot_author = bool(getattr(author, "bot", False))
    if is_bot_author and author_id != bot_user_id:
        return None

    if not _is_default_message(message):
        return None

    clean_content = getattr(message, "clean_content", None)
    raw_content = getattr(message, "content", "")

    content = clean_content if isinstance(clean_content, str) else str(raw_content)
    content = _sanitize_discord_markup(content).strip()
    if not content:
        return None

    if len(content) > MAX_CONTEXT_MESSAGE_CHARS:
        content = content[: MAX_CONTEXT_MESSAGE_CHARS - 1].rstrip() + "…"

    return MentionContextMessage(
        author_name=_display_name(author),
        content=content,
        message_id=getattr(message, "id", None),
    )


def _enforce_total_budget(
    messages: list[tuple[bool, MentionContextMessage]],
) -> list[MentionContextMessage]:
    budgeted = messages[:]
    while _rendered_length(budgeted) > MAX_CONTEXT_TOTAL_CHARS:
        drop_index = next(
            (idx for idx, (required, _) in enumerate(budgeted) if not required),
            None,
        )
        if drop_index is None:
            break
        budgeted.pop(drop_index)

    return [msg for _, msg in budgeted]


def _rendered_length(messages: list[tuple[bool, MentionContextMessage]]) -> int:
    return sum(len(f"{msg.author_name}: {msg.content}\n") for _, msg in messages)


async def _resolve_replied_to_message(message: Any) -> Any | None:
    reference = getattr(message, "reference", None)
    if reference is None:
        return None

    resolved = getattr(reference, "resolved", None)
    if resolved is not None:
        return resolved

    message_id = getattr(reference, "message_id", None)
    if message_id is None:
        return None

    fetch_message = getattr(message.channel, "fetch_message", None)
    if fetch_message is None:
        return None

    try:
        return await fetch_message(message_id)
    except Exception as exc:
        log.debug("Could not fetch replied-to message %s: %s", message_id, exc)
        return None
