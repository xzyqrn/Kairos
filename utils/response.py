"""
utils/response.py — AI response post-processing utilities for Kairos.

Provides trim_response(), which enforces per-command character limits before
text is inserted into Discord embeds.  Extracting this logic from the cogs
makes it independently testable and reusable across multiple commands.

Usage::

    from utils.response import trim_response

    safe_text = trim_response(ai_reply, "howareyou")
"""

from __future__ import annotations

# Per-command character caps (must be ≤ EMBED_DESC_LIMIT).
# Tighter caps encourage the model to stay on-point for each command's
# stated purpose (e.g. /howareyou needs brevity for an ephemeral card).
_COMMAND_CAPS: dict[str, int] = {
    "howareyou": 800,
    "suggest":   1_600,
    "advice":    1_000,
    "verse":     1_000,
    "devotion":  1_200,
    "pray":      800,
    "sermon":    2_000,
    "ask":       1_800,
}

# Discord embed description hard limit.
EMBED_DESC_LIMIT = 4_000


def trim_response(text: str, command: str) -> str:
    """
    Trim *text* to the per-command character cap.

    If the text exceeds the cap it is hard-trimmed, preferring a word
    boundary where possible, and a trailing ellipsis ``…`` is appended.

    Args:
        text:    Raw AI response string.
        command: Command key matching a key in ``_COMMAND_CAPS``
                 (e.g. ``"howareyou"``, ``"suggest"``).  Unknown keys fall
                 back to ``EMBED_DESC_LIMIT``.

    Returns:
        A string guaranteed to be ``<= _COMMAND_CAPS[command]`` characters,
        with an ellipsis appended if it was trimmed.

    Examples::

        >>> trim_response("short text", "howareyou")
        'short text'
        >>> trim_response("x" * 900, "howareyou")  # cap is 800
        'xxx...…'                                   # trimmed at word boundary
    """
    limit = min(_COMMAND_CAPS.get(command, EMBED_DESC_LIMIT), EMBED_DESC_LIMIT)

    if len(text) <= limit:
        return text

    cut = text[: limit - 1]

    # Prefer to break on the last whitespace so we don't cut mid-word.
    last_space = cut.rfind(" ")
    if last_space > limit // 2:
        cut = cut[:last_space]

    return cut.rstrip() + "…"
