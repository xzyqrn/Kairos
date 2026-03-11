"""
tests/test_quiz_store.py — Unit tests for utils/quiz_store.py (QuizStore)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utils.quiz_store as quiz_module
from utils.quiz_store import _POINTS_PER_CORRECT, QuizStore

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path: Path, monkeypatch):
    """Return a fresh QuizStore backed by a temp DB."""
    db_path = tmp_path / "quiz_test.db"
    monkeypatch.setattr(quiz_module, "_DB_PATH", db_path)
    s = QuizStore()
    return s


# ── TestRecordAnswer ──────────────────────────────────────────────────────────

class TestRecordAnswer:
    async def test_correct_answer_adds_points(self, store):
        result = await store.record_answer("g1", "u1", "Alice", correct=True)
        assert result["score"] == _POINTS_PER_CORRECT
        assert result["correct"] == 1
        assert result["total"] == 1

    async def test_wrong_answer_no_points(self, store):
        result = await store.record_answer("g1", "u1", "Alice", correct=False)
        assert result["score"] == 0
        assert result["correct"] == 0
        assert result["total"] == 1

    async def test_cumulative_score_accumulates(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        await store.record_answer("g1", "u1", "Alice", correct=True)
        result = await store.record_answer("g1", "u1", "Alice", correct=False)
        assert result["score"] == _POINTS_PER_CORRECT * 2
        assert result["correct"] == 2
        assert result["total"] == 3

    async def test_display_name_updated_on_each_answer(self, store):
        await store.record_answer("g1", "u1", "OldName", correct=True)
        result = await store.record_answer("g1", "u1", "NewName", correct=True)
        assert result["name"] == "NewName"

    async def test_different_users_independent(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        result_u2 = await store.record_answer("g1", "u2", "Bob", correct=False)
        result_u1 = await store.record_answer("g1", "u1", "Alice", correct=True)
        assert result_u1["score"] == _POINTS_PER_CORRECT * 2
        assert result_u2["score"] == 0

    async def test_different_guilds_independent(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        result = await store.record_answer("g2", "u1", "Alice", correct=False)
        assert result["score"] == 0


# ── TestLeaderboard ───────────────────────────────────────────────────────────

class TestLeaderboard:
    async def test_empty_guild_returns_empty_list(self, store):
        rows = await store.get_leaderboard("g1")
        assert rows == []

    async def test_leaderboard_sorted_by_score_descending(self, store):
        await store.record_answer("g1", "u1", "Low", correct=False)
        await store.record_answer("g1", "u2", "High", correct=True)
        rows = await store.get_leaderboard("g1")
        assert rows[0]["name"] == "High"
        assert rows[1]["name"] == "Low"

    async def test_leaderboard_respects_limit(self, store):
        for i in range(5):
            await store.record_answer("g1", f"u{i}", f"User{i}", correct=True)
        rows = await store.get_leaderboard("g1", limit=3)
        assert len(rows) == 3

    async def test_leaderboard_contains_required_keys(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        rows = await store.get_leaderboard("g1")
        assert set(rows[0].keys()) >= {"user_id", "name", "score", "correct", "total"}

    async def test_leaderboard_excludes_other_guilds(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        await store.record_answer("g2", "u2", "Bob", correct=True)
        rows = await store.get_leaderboard("g1")
        assert all(r["user_id"] == "u1" for r in rows)


# ── TestResetGuild ────────────────────────────────────────────────────────────

class TestResetGuild:
    async def test_reset_clears_guild_scores(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        await store.reset_guild("g1")
        rows = await store.get_leaderboard("g1")
        assert rows == []

    async def test_reset_does_not_affect_other_guilds(self, store):
        await store.record_answer("g1", "u1", "Alice", correct=True)
        await store.record_answer("g2", "u2", "Bob", correct=True)
        await store.reset_guild("g1")
        rows = await store.get_leaderboard("g2")
        assert len(rows) == 1

    async def test_reset_empty_guild_no_error(self, store):
        # Should not raise even if guild has no scores
        await store.reset_guild("g_nonexistent")
