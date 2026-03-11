"""
utils/history.py — Persistent, SQLite-backed per-user conversation history.

Replaces the in-memory deque in the Chat cog so conversation context survives
bot restarts. History is partitioned by (guild_id, user_id) so each user has
an independent context per server.

Storage: data/history.db  ← auto-created on first use

Usage::

    from utils.history import history_store

    msgs  = await history_store.get(guild_id="123", user_id="456")
    await history_store.push(guild_id="123", user_id="456",
                             user_msg="hi", bot_reply="hello")
    await history_store.clear(guild_id="123", user_id="456")
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger("kairos.history")

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"

# How many full exchanges (user + assistant pairs) to keep per (guild, user)
_MAX_EXCHANGES = 5
# Max characters stored per message side (mirrors the old deque behaviour)
_MAX_CONTENT_CHARS = 1_500

_DDL = """
CREATE TABLE IF NOT EXISTS conversation_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT    NOT NULL,
    user_id    TEXT    NOT NULL,
    role       TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_guild_user
    ON conversation_history(guild_id, user_id);
"""


def _run_sync(fn, /, *args):
    """Execute a synchronous callable that uses a fresh SQLite connection."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    try:
        return fn(conn, *args)
    finally:
        conn.close()


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def _get(conn: sqlite3.Connection, guild_id: str, user_id: str) -> list[dict]:
    limit = _MAX_EXCHANGES * 2  # each exchange = 2 rows
    rows = conn.execute(
        """
        SELECT role, content FROM (
            SELECT id, role, content
            FROM   conversation_history
            WHERE  guild_id = ? AND user_id = ?
            ORDER  BY id DESC
            LIMIT  ?
        ) ORDER BY id ASC
        """,
        (guild_id, user_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _push(
    conn: sqlite3.Connection,
    guild_id: str,
    user_id: str,
    user_msg: str,
    bot_reply: str,
) -> None:
    conn.execute(
        "INSERT INTO conversation_history (guild_id, user_id, role, content) VALUES (?,?,?,?)",
        (guild_id, user_id, "user", user_msg[:_MAX_CONTENT_CHARS]),
    )
    conn.execute(
        "INSERT INTO conversation_history (guild_id, user_id, role, content) VALUES (?,?,?,?)",
        (guild_id, user_id, "assistant", bot_reply[:_MAX_CONTENT_CHARS]),
    )
    # Prune to keep only the most recent _MAX_EXCHANGES exchanges
    conn.execute(
        """
        DELETE FROM conversation_history
        WHERE  guild_id = ? AND user_id = ?
          AND  id NOT IN (
              SELECT id FROM conversation_history
              WHERE  guild_id = ? AND user_id = ?
              ORDER  BY id DESC
              LIMIT  ?
          )
        """,
        (guild_id, user_id, guild_id, user_id, _MAX_EXCHANGES * 2),
    )
    conn.commit()


def _clear(conn: sqlite3.Connection, guild_id: str, user_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM conversation_history WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    conn.commit()
    return cur.rowcount


class HistoryStore:
    """Async façade over the synchronous SQLite helpers."""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._ready = False

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._init_lock:
            if not self._ready:
                _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(_run_sync, _init)
                self._ready = True
                log.info("Conversation history DB ready at %s", _DB_PATH)

    async def get(self, guild_id: str, user_id: str) -> list[dict[str, str]]:
        """Return recent messages for the (guild, user) pair, oldest-first."""
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _get, guild_id, user_id)

    async def push(
        self,
        guild_id: str,
        user_id: str,
        user_msg: str,
        bot_reply: str,
    ) -> None:
        """Append a user/assistant exchange, pruning old rows automatically."""
        await self._ensure_ready()
        await asyncio.to_thread(_run_sync, _push, guild_id, user_id, user_msg, bot_reply)

    async def clear(self, guild_id: str, user_id: str) -> int:
        """Delete all history for (guild, user). Returns rows deleted."""
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _clear, guild_id, user_id)

    def build_prompt(self, history: list[dict[str, str]], current_message: str) -> str:
        """
        Merge *history* with *current_message* into a single prompt string,
        matching the format the AI models are accustomed to from the old cog.
        Pure / synchronous — no I/O.
        """
        if not history:
            return current_message

        lines = ["[Conversation history for context:]\n"]
        for msg in history:
            role = "User" if msg["role"] == "user" else "Kairos"
            lines.append(f"{role}: {msg['content']}")

        lines.append(f"\n[Current message:]\nUser: {current_message}")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────

history_store = HistoryStore()
