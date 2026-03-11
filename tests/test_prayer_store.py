"""
tests/test_prayer_store.py — Unit tests for utils/prayer_store.py (PrayerStore)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utils.prayer_store as prayer_module
from utils.prayer_store import PrayerStore

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path: Path, monkeypatch):
    """Return a fresh PrayerStore backed by a temp DB."""
    db_path = tmp_path / "prayer_test.db"
    monkeypatch.setattr(prayer_module, "_DB_PATH", db_path)
    s = PrayerStore()
    return s


def _req(
    id: str = "aaaa-1111",
    guild_id: str = "g1",
    user_id: str = "u1",
    request: str = "Please pray for me",
    anonymous: bool = False,
    timestamp: str = "2026-01-01T09:00:00",
) -> dict:
    return dict(
        id=id,
        guild_id=guild_id,
        user_id=user_id,
        request=request,
        anonymous=anonymous,
        timestamp=timestamp,
    )


# ── TestAdd ───────────────────────────────────────────────────────────────────

class TestAdd:
    async def test_add_creates_record(self, store):
        await store.add(**_req())
        rows = await store.list_open("g1")
        assert len(rows) == 1
        assert rows[0]["request"] == "Please pray for me"

    async def test_add_anonymous_flag_stored(self, store):
        await store.add(**_req(anonymous=True))
        rows = await store.list_open("g1")
        assert rows[0]["anonymous"] is True

    async def test_add_non_anonymous_flag_stored(self, store):
        await store.add(**_req(anonymous=False))
        rows = await store.list_open("g1")
        assert rows[0]["anonymous"] is False

    async def test_add_stores_timestamp(self, store):
        await store.add(**_req(timestamp="2026-03-07T10:00:00"))
        rows = await store.list_open("g1")
        assert rows[0]["timestamp"] == "2026-03-07T10:00:00"

    async def test_multiple_requests_stored_in_order(self, store):
        await store.add(**_req(id="aaa", request="First"))
        await store.add(**_req(id="bbb", request="Second"))
        rows = await store.list_open("g1")
        assert len(rows) == 2
        assert rows[0]["request"] == "First"
        assert rows[1]["request"] == "Second"


# ── TestMarkAnswered ──────────────────────────────────────────────────────────

class TestMarkAnswered:
    async def test_mark_answered_returns_true_for_exact_id(self, store):
        await store.add(**_req(id="aaaa-1111-xxxx"))
        result = await store.mark_answered("g1", "aaaa-1111-xxxx")
        assert result is True

    async def test_mark_answered_removes_from_open_list(self, store):
        await store.add(**_req(id="aaaa-1111"))
        await store.mark_answered("g1", "aaaa-1111")
        rows = await store.list_open("g1")
        assert len(rows) == 0

    async def test_mark_answered_no_match_returns_false(self, store):
        await store.add(**_req(id="aaaa-1111"))
        result = await store.mark_answered("g1", "zzzz-0000")
        assert result is False

    async def test_mark_answered_wrong_guild_returns_false(self, store):
        await store.add(**_req(id="aaaa-1111", guild_id="g1"))
        result = await store.mark_answered("g2", "aaaa-1111")
        assert result is False

    async def test_already_answered_returns_false(self, store):
        await store.add(**_req(id="aaaa-1111"))
        await store.mark_answered("g1", "aaaa-1111")
        result = await store.mark_answered("g1", "aaaa-1111")
        assert result is False


# ── TestFindMatches ───────────────────────────────────────────────────────────

class TestFindMatches:
    async def test_finds_all_prefix_matches_in_order(self, store):
        await store.add(**_req(id="abcd-1111", request="First"))
        await store.add(**_req(id="abcd-2222", request="Second"))

        matches = await store.find_matches("g1", "abcd", answered=False)

        assert [row["id"] for row in matches] == ["abcd-1111", "abcd-2222"]

    async def test_filters_by_answered_status(self, store):
        await store.add(**_req(id="abcd-1111"))
        await store.mark_answered("g1", "abcd-1111")

        open_matches = await store.find_matches("g1", "abcd", answered=False)
        answered_matches = await store.find_matches("g1", "abcd", answered=True)

        assert open_matches == []
        assert [row["id"] for row in answered_matches] == ["abcd-1111"]

    async def test_percent_is_treated_literally(self, store):
        await store.add(**_req(id="abcd-1111"))

        matches = await store.find_matches("g1", "%", answered=False)

        assert matches == []

    async def test_underscore_is_treated_literally(self, store):
        await store.add(**_req(id="abcd-1111"))

        matches = await store.find_matches("g1", "_", answered=False)

        assert matches == []


# ── TestDelete ────────────────────────────────────────────────────────────────

class TestDelete:
    async def test_delete_returns_true_on_match(self, store):
        await store.add(**_req(id="bbbb-2222"))
        deleted = await store.delete("g1", "bbbb-2222")
        assert deleted is True

    async def test_delete_removes_from_list(self, store):
        await store.add(**_req(id="bbbb-2222"))
        await store.delete("g1", "bbbb-2222")
        rows = await store.list_open("g1")
        assert len(rows) == 0

    async def test_delete_no_match_returns_false(self, store):
        deleted = await store.delete("g1", "zzzz-0000")
        assert deleted is False

    async def test_delete_only_affects_target(self, store):
        await store.add(**_req(id="aaaa-1111", request="Keep me"))
        await store.add(**_req(id="bbbb-2222", request="Delete me"))
        await store.delete("g1", "bbbb-2222")
        rows = await store.list_open("g1")
        assert len(rows) == 1
        assert rows[0]["request"] == "Keep me"


# ── TestListAllOpenByUser ─────────────────────────────────────────────────────

class TestListAllOpenByUser:
    async def test_returns_grouped_by_user(self, store):
        await store.add(**_req(id="aaa", user_id="u1", request="Req from u1"))
        await store.add(**_req(id="bbb", user_id="u2", request="Req from u2"))
        result = await store.list_all_open_by_user()
        assert "u1" in result
        assert "u2" in result
        assert result["u1"] == ["Req from u1"]

    async def test_answered_requests_excluded(self, store):
        await store.add(**_req(id="aaa", user_id="u1"))
        await store.mark_answered("g1", "aaa")
        result = await store.list_all_open_by_user()
        assert "u1" not in result

    async def test_snippets_truncated_to_80_chars(self, store):
        long_req = "x" * 200
        await store.add(**_req(id="aaa", user_id="u1", request=long_req))
        result = await store.list_all_open_by_user()
        assert all(len(s) <= 80 for s in result.get("u1", []))
