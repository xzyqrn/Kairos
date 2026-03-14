from __future__ import annotations

from pathlib import Path

import pytest

import utils.channel_memory_store as memory_module
from utils.channel_memory_store import ChannelMemoryStore


@pytest.fixture()
def store(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "history.db"
    monkeypatch.setattr(memory_module, "_DB_PATH", db_path)
    return ChannelMemoryStore()


class TestChannelMemoryStore:
    async def test_upsert_then_get_returns_summary(self, store):
        await store.upsert_summary(
            guild_id="g1",
            channel_id="c1",
            summary="They have been discussing forgiveness and reconciliation.",
            last_message_id=10,
            updated_at="2026-03-14T12:00:00Z",
        )

        result = await store.get_summary("g1", "c1", now="2026-03-14T12:05:00Z")

        assert result is not None
        assert result.summary == "They have been discussing forgiveness and reconciliation."
        assert result.last_message_id == 10

    async def test_stale_summary_is_purged(self, store):
        await store.upsert_summary(
            guild_id="g1",
            channel_id="c1",
            summary="Old summary",
            last_message_id=10,
            updated_at="2026-02-01T12:00:00Z",
        )

        result = await store.get_summary("g1", "c1", now="2026-03-14T12:00:00Z")

        assert result is None

    async def test_older_message_id_does_not_overwrite_newer_summary(self, store):
        await store.upsert_summary(
            guild_id="g1",
            channel_id="c1",
            summary="Newer summary",
            last_message_id=20,
            updated_at="2026-03-14T12:00:00Z",
        )
        await store.upsert_summary(
            guild_id="g1",
            channel_id="c1",
            summary="Older summary",
            last_message_id=19,
            updated_at="2026-03-14T12:01:00Z",
        )

        result = await store.get_summary("g1", "c1", now="2026-03-14T12:05:00Z")

        assert result is not None
        assert result.summary == "Newer summary"
        assert result.last_message_id == 20

    async def test_clear_channel_removes_summary(self, store):
        await store.upsert_summary(
            guild_id="g1",
            channel_id="c1",
            summary="Summary",
            last_message_id=20,
            updated_at="2026-03-14T12:00:00Z",
        )

        deleted = await store.clear_channel("g1", "c1")

        assert deleted == 1
        assert await store.get_summary("g1", "c1", now="2026-03-14T12:05:00Z") is None
