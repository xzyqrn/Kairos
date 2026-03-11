"""
utils/prayer_store.py — SQLite-backed prayer request store.

Replaces data/prayer_requests.json with a proper relational table so concurrent
writes are safe and queries are efficient.

Storage: data/history.db  ← shared with conversation history

Usage::

    from utils.prayer_store import prayer_store

    await prayer_store.add(id=..., guild_id=..., user_id=..., request=...,
                           anonymous=True, timestamp=...)
    reqs = await prayer_store.list_open(guild_id="123")
    matched = await prayer_store.mark_answered(guild_id="123", id_prefix="abcd1234")
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("kairos.prayer_store")

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"

_DDL = """
CREATE TABLE IF NOT EXISTS prayer_requests (
    id        TEXT    PRIMARY KEY,
    guild_id  TEXT    NOT NULL,
    user_id   TEXT    NOT NULL,
    request   TEXT    NOT NULL,
    anonymous INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT    NOT NULL,
    answered  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_prayer_guild
    ON prayer_requests(guild_id);
CREATE INDEX IF NOT EXISTS idx_prayer_answered
    ON prayer_requests(guild_id, answered);
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


def _add(
    conn: sqlite3.Connection,
    id: str,
    guild_id: str,
    user_id: str,
    request: str,
    anonymous: bool,
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO prayer_requests (id, guild_id, user_id, request, anonymous, timestamp, answered)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (id, guild_id, user_id, request, 1 if anonymous else 0, timestamp),
    )
    conn.commit()


def _list_open(conn: sqlite3.Connection, guild_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, guild_id, user_id, request, anonymous, timestamp, answered
        FROM prayer_requests
        WHERE guild_id = ? AND answered = 0
        ORDER BY rowid ASC
        """,
        (guild_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "guild_id": r["guild_id"],
            "user_id": r["user_id"],
            "request": r["request"],
            "anonymous": bool(r["anonymous"]),
            "timestamp": r["timestamp"],
            "answered": bool(r["answered"]),
        }
        for r in rows
    ]


def _mark_answered(conn: sqlite3.Connection, guild_id: str, id_prefix: str) -> str | None:
    row = conn.execute(
        """
        SELECT id FROM prayer_requests
        WHERE guild_id = ? AND id LIKE ? AND answered = 0
        LIMIT 1
        """,
        (guild_id, id_prefix.strip() + "%"),
    ).fetchone()

    if row is None:
        return None

    full_id = row["id"]
    conn.execute(
        "UPDATE prayer_requests SET answered = 1 WHERE id = ?",
        (full_id,),
    )
    conn.commit()
    return full_id


def _delete(conn: sqlite3.Connection, guild_id: str, id_prefix: str) -> bool:
    cur = conn.execute(
        """
        DELETE FROM prayer_requests
        WHERE guild_id = ? AND id LIKE ?
        """,
        (guild_id, id_prefix.strip() + "%"),
    )
    conn.commit()
    return cur.rowcount > 0


def _list_all_open_by_user(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Return {user_id: [request_snippet, ...]} for all open (unanswered) requests."""
    rows = conn.execute(
        """
        SELECT user_id, request FROM prayer_requests
        WHERE answered = 0
        ORDER BY rowid ASC
        """,
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        uid = row["user_id"]
        result.setdefault(uid, []).append(row["request"][:80])
    return result


class PrayerStore:
    """Async façade over the synchronous SQLite helpers."""

    def __init__(self) -> None:
        self._init_lock = asyncio.Lock()
        self._ready = False

    async def _ensure_ready(self) -> None:
        """Idempotent — creates the table on first call."""
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(_run_sync, _init)
            self._ready = True
            log.info("Prayer request DB ready at %s", _DB_PATH)

    async def add(
        self,
        id: str,
        guild_id: str,
        user_id: str,
        request: str,
        anonymous: bool,
        timestamp: str,
    ) -> None:
        """Insert a new prayer request."""
        await self._ensure_ready()
        await asyncio.to_thread(_run_sync, _add, id, guild_id, user_id, request, anonymous, timestamp)

    async def list_open(self, guild_id: str) -> list[dict]:
        """Return all open (unanswered) prayer requests for a guild, oldest-first."""
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _list_open, guild_id)

    async def mark_answered(self, guild_id: str, id_prefix: str) -> str | None:
        """
        Mark the first matching open request as answered.

        Matches by ``id LIKE '{id_prefix}%'`` within the guild.
        Returns the full UUID if found and updated, or None if no match.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _mark_answered, guild_id, id_prefix)

    async def delete(self, guild_id: str, id_prefix: str) -> bool:
        """
        Delete the first matching prayer request in the guild.

        Returns True if a row was deleted, False if no match.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _delete, guild_id, id_prefix)

    async def list_all_open_by_user(self) -> dict[str, list[str]]:
        """
        Return a mapping of user_id → list of request snippets for all open
        (unanswered) requests across all guilds.

        Used by the weekly prayer reminder task.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _list_all_open_by_user)


# ── Singleton ─────────────────────────────────────────────────────────────────

prayer_store = PrayerStore()
