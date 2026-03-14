from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger("kairos.channel_memory_store")

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"
CHANNEL_MEMORY_RETENTION_DAYS = 14

_DDL = """
CREATE TABLE IF NOT EXISTS channel_memory (
    guild_id        TEXT    NOT NULL,
    channel_id      TEXT    NOT NULL,
    summary         TEXT    NOT NULL,
    last_message_id INTEGER NOT NULL,
    updated_at      TEXT    NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_memory_updated
    ON channel_memory(updated_at);
"""


@dataclass(frozen=True, slots=True)
class ChannelMemoryEntry:
    guild_id: str
    channel_id: str
    summary: str
    last_message_id: int
    updated_at: str


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _retention_cutoff(now: str | None = None) -> str:
    current = (
        datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if now
        else datetime.now(UTC)
    )
    cutoff = current - timedelta(days=CHANNEL_MEMORY_RETENTION_DAYS)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_sync(fn, /, *args):
    conn = sqlite3.connect(_DB_PATH, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    try:
        return fn(conn, *args)
    finally:
        conn.close()


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def _purge_expired(conn: sqlite3.Connection, cutoff: str) -> None:
    conn.execute("DELETE FROM channel_memory WHERE updated_at < ?", (cutoff,))
    conn.commit()


def _row_to_entry(row: sqlite3.Row) -> ChannelMemoryEntry:
    return ChannelMemoryEntry(
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        summary=row["summary"],
        last_message_id=int(row["last_message_id"]),
        updated_at=row["updated_at"],
    )


def _get(conn: sqlite3.Connection, guild_id: str, channel_id: str) -> ChannelMemoryEntry | None:
    row = conn.execute(
        """
        SELECT guild_id, channel_id, summary, last_message_id, updated_at
        FROM channel_memory
        WHERE guild_id = ? AND channel_id = ?
        """,
        (guild_id, channel_id),
    ).fetchone()
    return _row_to_entry(row) if row is not None else None


def _upsert(
    conn: sqlite3.Connection,
    guild_id: str,
    channel_id: str,
    summary: str,
    last_message_id: int,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO channel_memory (guild_id, channel_id, summary, last_message_id, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, channel_id) DO UPDATE SET
            summary = excluded.summary,
            last_message_id = excluded.last_message_id,
            updated_at = excluded.updated_at
        WHERE excluded.last_message_id >= channel_memory.last_message_id
        """,
        (guild_id, channel_id, summary, last_message_id, updated_at),
    )
    conn.commit()


def _clear_channel(conn: sqlite3.Connection, guild_id: str, channel_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM channel_memory WHERE guild_id = ? AND channel_id = ?",
        (guild_id, channel_id),
    )
    conn.commit()
    return cur.rowcount


class ChannelMemoryStore:
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
                log.info("Channel memory DB ready at %s", _DB_PATH)

    async def purge_expired(self, *, now: str | None = None) -> None:
        await self._ensure_ready()
        cutoff = _retention_cutoff(now=now)
        await asyncio.to_thread(_run_sync, _purge_expired, cutoff)

    async def get_summary(
        self,
        guild_id: str,
        channel_id: str,
        *,
        now: str | None = None,
    ) -> ChannelMemoryEntry | None:
        await self._ensure_ready()
        cutoff = _retention_cutoff(now=now)
        await asyncio.to_thread(_run_sync, _purge_expired, cutoff)
        return await asyncio.to_thread(_run_sync, _get, guild_id, channel_id)

    async def upsert_summary(
        self,
        guild_id: str,
        channel_id: str,
        summary: str,
        last_message_id: int,
        *,
        updated_at: str | None = None,
    ) -> None:
        await self._ensure_ready()
        timestamp = updated_at or _utc_now()
        await asyncio.to_thread(
            _run_sync,
            _upsert,
            guild_id,
            channel_id,
            summary,
            last_message_id,
            timestamp,
        )

    async def clear_channel(self, guild_id: str, channel_id: str) -> int:
        await self._ensure_ready()
        return await asyncio.to_thread(_run_sync, _clear_channel, guild_id, channel_id)


channel_memory_store = ChannelMemoryStore()
