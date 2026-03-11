"""
utils/quiz_store.py — SQLite-backed quiz score store.

Replaces data/quiz_scores.json with a proper relational table so concurrent
writes are safe and leaderboard queries are efficient.

Storage: data/history.db  ← shared with conversation history

Usage::

    from utils.quiz_store import quiz_store

    entry = await quiz_store.record_answer(guild_id="123", user_id="456",
                                           display_name="Alice", correct=True)
    rows  = await quiz_store.get_leaderboard(guild_id="123", limit=10)
    await quiz_store.reset_guild(guild_id="123")
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("kairos.quiz_store")

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"

_POINTS_PER_CORRECT = 10

_DDL = """
CREATE TABLE IF NOT EXISTS quiz_scores (
    guild_id     TEXT    NOT NULL,
    user_id      TEXT    NOT NULL,
    display_name TEXT    NOT NULL,
    score        INTEGER NOT NULL DEFAULT 0,
    correct      INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_quiz_guild
    ON quiz_scores(guild_id);
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


def _record_answer(
    conn: sqlite3.Connection,
    guild_id: str,
    user_id: str,
    display_name: str,
    correct: bool,
) -> dict:
    # Ensure the row exists
    conn.execute(
        """
        INSERT OR IGNORE INTO quiz_scores (guild_id, user_id, display_name, score, correct, total)
        VALUES (?, ?, ?, 0, 0, 0)
        """,
        (guild_id, user_id, display_name),
    )
    # Always update display_name and increment totals
    if correct:
        conn.execute(
            """
            UPDATE quiz_scores
            SET display_name = ?,
                score        = score + ?,
                correct      = correct + 1,
                total        = total + 1
            WHERE guild_id = ? AND user_id = ?
            """,
            (display_name, _POINTS_PER_CORRECT, guild_id, user_id),
        )
    else:
        conn.execute(
            """
            UPDATE quiz_scores
            SET display_name = ?,
                total        = total + 1
            WHERE guild_id = ? AND user_id = ?
            """,
            (display_name, guild_id, user_id),
        )
    conn.commit()

    row = conn.execute(
        "SELECT display_name, score, correct, total FROM quiz_scores WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return {
        "name": row["display_name"],
        "score": row["score"],
        "correct": row["correct"],
        "total": row["total"],
    }


def _get_leaderboard(conn: sqlite3.Connection, guild_id: str, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT user_id, display_name, score, correct, total
        FROM quiz_scores
        WHERE guild_id = ?
        ORDER BY score DESC
        LIMIT ?
        """,
        (guild_id, limit),
    ).fetchall()
    return [
        {
            "user_id": r["user_id"],
            "name": r["display_name"],
            "score": r["score"],
            "correct": r["correct"],
            "total": r["total"],
        }
        for r in rows
    ]


def _reset_guild(conn: sqlite3.Connection, guild_id: str) -> None:
    conn.execute("DELETE FROM quiz_scores WHERE guild_id = ?", (guild_id,))
    conn.commit()


class QuizStore:
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
                log.info("Quiz score DB ready at %s", _DB_PATH)

    async def record_answer(
        self,
        guild_id: str,
        user_id: str,
        display_name: str,
        correct: bool,
    ) -> dict:
        """
        Record a quiz answer for a user in a guild.

        Creates the row if it doesn't exist, then increments score/correct/total.
        Returns the updated stats dict with keys: name, score, correct, total.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _record_answer, guild_id, user_id, display_name, correct)

    async def get_leaderboard(self, guild_id: str, limit: int = 10) -> list[dict]:
        """
        Return up to *limit* rows for a guild, sorted by score descending.

        Each row has keys: user_id, name, score, correct, total.
        Returns an empty list if no scores exist yet.
        """
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _get_leaderboard, guild_id, limit)

    async def reset_guild(self, guild_id: str) -> None:
        """Delete all quiz scores for the given guild."""
        await self._ensure_ready()
        await asyncio.to_thread(_run_sync, _reset_guild, guild_id)


# ── Singleton ─────────────────────────────────────────────────────────────────

quiz_store = QuizStore()
