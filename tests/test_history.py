"""
tests/test_history.py — Unit tests for utils/history.py (HistoryStore)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utils.history as history_module
from utils.history import _MAX_EXCHANGES, HistoryStore

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path: Path, monkeypatch):
    """Return a fresh HistoryStore backed by a temp DB."""
    db_path = tmp_path / "history.db"
    monkeypatch.setattr(history_module, "_DB_PATH", db_path)
    s = HistoryStore()
    return s


# ── Initialisation ─────────────────────────────────────────────────────────────

class TestInit:
    async def test_db_file_created_on_first_use(self, store, tmp_path, monkeypatch):
        monkeypatch.setattr(history_module, "_DB_PATH", tmp_path / "history.db")
        s = HistoryStore()
        await s.get(guild_id="g1", user_id="u1")
        assert (tmp_path / "history.db").exists()


# ── Push & Get ────────────────────────────────────────────────────────────────

class TestPushGet:
    async def test_empty_history_returns_empty_list(self, store):
        result = await store.get(guild_id="g1", user_id="u1")
        assert result == []

    async def test_push_then_get_returns_messages(self, store):
        await store.push("g1", "u1", "Hello bot", "Hello user!")
        msgs = await store.get("g1", "u1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello bot"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Hello user!"

    async def test_messages_returned_oldest_first(self, store):
        await store.push("g1", "u1", "first", "first reply")
        await store.push("g1", "u1", "second", "second reply")
        msgs = await store.get("g1", "u1")
        assert msgs[0]["content"] == "first"
        assert msgs[-1]["content"] == "second reply"

    async def test_content_truncated_to_max_chars(self, store):
        long_msg = "x" * 2000
        await store.push("g1", "u1", long_msg, "reply")
        msgs = await store.get("g1", "u1")
        assert len(msgs[0]["content"]) <= history_module._MAX_CONTENT_CHARS


# ── Pruning ────────────────────────────────────────────────────────────────────

class TestPruning:
    async def test_exceeding_max_exchanges_prunes_oldest(self, store):
        # Push more than _MAX_EXCHANGES exchanges
        for i in range(_MAX_EXCHANGES + 3):
            await store.push("g1", "u1", f"msg {i}", f"reply {i}")

        msgs = await store.get("g1", "u1")
        # Should never exceed _MAX_EXCHANGES * 2 messages
        assert len(msgs) <= _MAX_EXCHANGES * 2

    async def test_most_recent_exchanges_kept(self, store):
        for i in range(_MAX_EXCHANGES + 2):
            await store.push("g1", "u1", f"msg {i}", f"reply {i}")

        msgs = await store.get("g1", "u1")
        # The last message should be from the most recent exchange
        assert msgs[-1]["content"] == f"reply {_MAX_EXCHANGES + 1}"


# ── Isolation ─────────────────────────────────────────────────────────────────

class TestIsolation:
    async def test_different_users_isolated(self, store):
        await store.push("g1", "u1", "user1 msg", "user1 reply")
        await store.push("g1", "u2", "user2 msg", "user2 reply")

        u1 = await store.get("g1", "u1")
        u2 = await store.get("g1", "u2")

        assert all(m["content"] in ("user1 msg", "user1 reply") for m in u1)
        assert all(m["content"] in ("user2 msg", "user2 reply") for m in u2)

    async def test_different_guilds_isolated(self, store):
        await store.push("g1", "u1", "guild1 msg", "guild1 reply")
        await store.push("g2", "u1", "guild2 msg", "guild2 reply")

        g1 = await store.get("g1", "u1")
        g2 = await store.get("g2", "u1")

        assert all("guild1" in m["content"] for m in g1)
        assert all("guild2" in m["content"] for m in g2)


# ── Clear ─────────────────────────────────────────────────────────────────────

class TestClear:
    async def test_clear_removes_all_messages(self, store):
        await store.push("g1", "u1", "hello", "world")
        deleted = await store.clear("g1", "u1")
        assert deleted == 2
        assert await store.get("g1", "u1") == []

    async def test_clear_only_affects_target_user(self, store):
        await store.push("g1", "u1", "u1 msg", "u1 reply")
        await store.push("g1", "u2", "u2 msg", "u2 reply")
        await store.clear("g1", "u1")
        assert await store.get("g1", "u2") != []

    async def test_clear_empty_history_returns_zero(self, store):
        deleted = await store.clear("g1", "u_nobody")
        assert deleted == 0


# ── build_prompt ──────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_no_history_returns_message_only(self, store):
        result = store.build_prompt([], "Hi there!")
        assert result == "Hi there!"

    def test_history_included_in_prompt(self, store):
        history = [
            {"role": "user",      "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = store.build_prompt(history, "What time is it?")
        assert "Hello" in result
        assert "Hi!" in result
        assert "What time is it?" in result

    def test_roles_labelled_correctly(self, store):
        history = [
            {"role": "user",      "content": "user says"},
            {"role": "assistant", "content": "bot says"},
        ]
        result = store.build_prompt(history, "current")
        assert "User: user says" in result
        assert "Kairos: bot says" in result

    def test_current_message_at_end(self, store):
        history = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "reply"}]
        result = store.build_prompt(history, "new question")
        assert result.endswith("new question")
