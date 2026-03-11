"""
tests/test_journal_storage.py — Unit tests for journal storage paths.
"""

from __future__ import annotations

import pytest

pytest.importorskip("discord")
import cogs.journal as journal


class TestJournalStorage:
    async def test_write_and_read_use_absolute_journal_dir(self, tmp_path, monkeypatch):
        journal_dir = tmp_path / "journal-data"
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setattr(journal, "_JOURNAL_DIR", journal_dir.resolve())
        monkeypatch.chdir(elsewhere)

        entries = [{"id": 1, "timestamp": "2026-03-11T09:00:00+08:00", "entry": "Entry text"}]
        await journal._write_journal("123", entries)

        stored_path = journal_dir / "123.json"
        assert stored_path.exists()
        assert await journal._read_journal("123") == entries
