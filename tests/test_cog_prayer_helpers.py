"""
tests/test_cog_prayer_helpers.py — Unit tests for cogs/prayer.py helper functions.

Tests the pure _build_pages() function directly without Discord mocking.
"""

from __future__ import annotations

import discord

from cogs.prayer import _PAGE_SIZE, _build_pages


def _make_req(req_id: str = "abcd-1234", user_id: str = "u1",
              request: str = "Please pray", anonymous: bool = False,
              timestamp: str = "2026-03-07T09:00:00") -> dict:
    return {
        "id": req_id,
        "guild_id": "g1",
        "user_id": user_id,
        "request": request,
        "anonymous": anonymous,
        "timestamp": timestamp,
        "answered": False,
    }


# ── TestBuildPages ────────────────────────────────────────────────────────────

class TestBuildPages:
    def test_empty_list_returns_single_embed(self):
        pages = _build_pages([])
        assert len(pages) == 1
        assert isinstance(pages[0], discord.Embed)

    def test_empty_embed_has_no_open_requests_text(self):
        pages = _build_pages([])
        assert "No open prayer requests" in (pages[0].description or "")

    def test_single_request_returns_one_page(self):
        pages = _build_pages([_make_req()])
        assert len(pages) == 1

    def test_requests_split_into_pages(self):
        reqs = [_make_req(req_id=f"id{i:04d}") for i in range(_PAGE_SIZE + 1)]
        pages = _build_pages(reqs)
        assert len(pages) == 2

    def test_anonymous_request_shown_anonymously(self):
        pages = _build_pages([_make_req(anonymous=True)])
        field_value = pages[0].fields[0].value or ""
        assert "Anonymous" in field_value
        assert "@u1" not in field_value

    def test_non_anonymous_shows_mention(self):
        pages = _build_pages([_make_req(user_id="123456", anonymous=False)])
        field_value = pages[0].fields[0].value or ""
        assert "<@123456>" in field_value

    def test_request_text_truncated_at_200_chars(self):
        long_req = "x" * 300
        pages = _build_pages([_make_req(request=long_req)])
        field_value = pages[0].fields[0].value or ""
        # The value should contain at most 200 chars of the request
        assert "x" * 201 not in field_value
