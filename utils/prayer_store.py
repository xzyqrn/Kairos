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
    matches = await prayer_store.find_matches(guild_id="123", id_prefix="abcd1234", answered=False)
    matched = await prayer_store.mark_answered(guild_id="123", request_id="abcd1234-full")
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
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "guild_id": row["guild_id"],
        "user_id": row["user_id"],
        "request": row["request"],
        "anonymous": bool(row["anonymous"]),
        "timestamp": row["timestamp"],
        "answered": bool(row["answered"]),
    }


def _escape_like(value: str) -> str:
    """Escape SQLite LIKE wildcards so prefix matching stays literal."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _find_matches(
    conn: sqlite3.Connection,
    guild_id: str,
    id_prefix: str,
    answered: bool | None,
) -> list[dict]:
    prefix = id_prefix.strip()
    if not prefix:
        return []

    query = """
        SELECT id, guild_id, user_id, request, anonymous, timestamp, answered
        FROM prayer_requests
        WHERE guild_id = ? AND id LIKE ? ESCAPE '\\'
    """
    params: list[str | int] = [guild_id, _escape_like(prefix) + "%"]
    if answered is not None:
        query += " AND answered = ?"
        params.append(1 if answered else 0)
    query += " ORDER BY rowid ASC"

    rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_dict(row) for row in rows]


def _mark_answered(conn: sqlite3.Connection, guild_id: str, request_id: str) -> bool:
    cur = conn.execute(
        """
        UPDATE prayer_requests
        SET answered = 1
        WHERE guild_id = ? AND id = ? AND answered = 0
        """,
        (guild_id, request_id),
    )
    conn.commit()
    return cur.rowcount > 0


def _delete(conn: sqlite3.Connection, guild_id: str, request_id: str) -> bool:
    """Delete exactly one request identified by its full UUID."""
    cur = conn.execute(
        "DELETE FROM prayer_requests WHERE guild_id = ? AND id = ?",
        (guild_id, request_id),
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
            if not self._ready:
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

    async def find_matches(
        self,
        guild_id: str,
        id_prefix: str,
        answered: bool | None = None,
    ) -> list[dict]:
        """
        Return prayer requests in a guild whose IDs start with ``id_prefix``.

        When ``answered`` is False, only open requests are returned. When True,
        only answered requests are returned. When None, both are considered.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _find_matches, guild_id, id_prefix, answered)

    async def mark_answered(self, guild_id: str, request_id: str) -> bool:
        """Mark one exact open request as answered."""
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _mark_answered, guild_id, request_id)

    async def delete(self, guild_id: str, request_id: str) -> bool:
        """Delete one exact prayer request in the guild."""
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _delete, guild_id, request_id)

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
