"""
tests/test_streak_store.py — Unit tests for utils/streak_store.py (StreakStore)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utils.streak_store as streak_module
from utils.streak_store import StreakStore

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path: Path, monkeypatch):
    """Return a fresh StreakStore backed by a temp DB."""
    db_path = tmp_path / "streak_test.db"
    monkeypatch.setattr(streak_module, "_DB_PATH", db_path)
    s = StreakStore()
    return s


# ── TestGetUpsert ─────────────────────────────────────────────────────────────

class TestGetUpsert:
    async def test_get_returns_none_for_unknown_user(self, store):
        result = await store.get("u_unknown")
        assert result is None

    async def test_upsert_creates_record(self, store):
        await store.upsert("u1", current_streak=3, longest_streak=5,
                           total_devotions=10, last_date="2026-03-07")
        result = await store.get("u1")
        assert result is not None
        assert result["current_streak"] == 3
        assert result["longest_streak"] == 5
        assert result["total_devotions"] == 10
        assert result["last_date"] == "2026-03-07"

    async def test_upsert_replaces_existing_record(self, store):
        await store.upsert("u1", current_streak=1, longest_streak=1,
                           total_devotions=1, last_date="2026-01-01")
        await store.upsert("u1", current_streak=5, longest_streak=7,
                           total_devotions=15, last_date="2026-03-07")
        result = await store.get("u1")
        assert result["current_streak"] == 5
        assert result["total_devotions"] == 15

    async def test_result_has_all_expected_keys(self, store):
        await store.upsert("u1", current_streak=1, longest_streak=1,
                           total_devotions=1, last_date="2026-01-01")
        result = await store.get("u1")
        assert set(result.keys()) == {"current_streak", "longest_streak",
                                       "total_devotions", "last_date"}


# ── TestGetMany ───────────────────────────────────────────────────────────────

class TestGetMany:
    async def test_returns_empty_dict_for_empty_list(self, store):
        result = await store.get_many([])
        assert result == {}

    async def test_returns_only_known_users(self, store):
        await store.upsert("u1", current_streak=2, longest_streak=2,
                           total_devotions=2, last_date="2026-03-01")
        result = await store.get_many(["u1", "u_unknown"])
        assert "u1" in result
        assert "u_unknown" not in result

    async def test_returns_correct_data_for_multiple_users(self, store):
        await store.upsert("u1", current_streak=3, longest_streak=3,
                           total_devotions=3, last_date="2026-03-01")
        await store.upsert("u2", current_streak=7, longest_streak=10,
                           total_devotions=20, last_date="2026-03-07")
        result = await store.get_many(["u1", "u2"])
        assert result["u1"]["current_streak"] == 3
        assert result["u2"]["current_streak"] == 7
