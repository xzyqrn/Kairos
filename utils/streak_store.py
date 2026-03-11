"""
utils/streak_store.py — SQLite-backed devotion streak store.

Replaces data/streaks.json with a proper relational table so concurrent
writes are safe.

Streaks are global per user (not per guild) — matching the original design.
The /streaks leaderboard filters by guild-member IDs in Python.

Storage: data/history.db  ← shared with conversation history

Usage::

    from utils.streak_store import streak_store

    entry = await streak_store.get(user_id="123")
    await streak_store.upsert(user_id="123", current_streak=5,
                              longest_streak=10, total_devotions=20,
                              last_date="2026-03-07")
    guild_data = await streak_store.get_many(["123", "456"])
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("kairos.streak_store")

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"

_DDL = """
CREATE TABLE IF NOT EXISTS streaks (
    user_id         TEXT    PRIMARY KEY,
    current_streak  INTEGER NOT NULL DEFAULT 0,
    longest_streak  INTEGER NOT NULL DEFAULT 0,
    total_devotions INTEGER NOT NULL DEFAULT 0,
    last_date       TEXT
);
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


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "current_streak": row["current_streak"],
        "longest_streak": row["longest_streak"],
        "total_devotions": row["total_devotions"],
        "last_date": row["last_date"],
    }


def _get(conn: sqlite3.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        "SELECT current_streak, longest_streak, total_devotions, last_date FROM streaks WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def _upsert(
    conn: sqlite3.Connection,
    user_id: str,
    current_streak: int,
    longest_streak: int,
    total_devotions: int,
    last_date: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO streaks (user_id, current_streak, longest_streak, total_devotions, last_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, current_streak, longest_streak, total_devotions, last_date),
    )
    conn.commit()


def _get_many(conn: sqlite3.Connection, user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    placeholders = ",".join("?" * len(user_ids))
    rows = conn.execute(
        f"SELECT user_id, current_streak, longest_streak, total_devotions, last_date FROM streaks WHERE user_id IN ({placeholders})",
        user_ids,
    ).fetchall()
    return {row["user_id"]: _row_to_dict(row) for row in rows}


class StreakStore:
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
                log.info("Streak DB ready at %s", _DB_PATH)

    async def get(self, user_id: str) -> dict | None:
        """
        Return the streak stats for a user, or None if they have no record yet.

        Returned dict has keys: current_streak, longest_streak, total_devotions, last_date.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _get, user_id)

    async def upsert(
        self,
        user_id: str,
        current_streak: int,
        longest_streak: int,
        total_devotions: int,
        last_date: str,
    ) -> None:
        """Insert or replace the streak record for a user."""
        await self._ensure_ready()
        await asyncio.to_thread(
            _run_sync, _upsert, user_id, current_streak, longest_streak, total_devotions, last_date
        )

    async def get_many(self, user_ids: list[str]) -> dict[str, dict]:
        """
        Return streak stats for a list of user IDs.

        Returns a mapping of user_id → stats dict. Users with no record are
        omitted from the result (not included with zeroed stats).
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _get_many, user_ids)


# ── Singleton ─────────────────────────────────────────────────────────────────

streak_store = StreakStore()
