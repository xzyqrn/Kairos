"""
tests/test_bootstrap.py — Unit tests for startup file/bootstrap helpers in main.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiofiles
import pytest

pytest.importorskip("discord")
from main import ensure_json_file


class TestEnsureJsonFile:
    async def test_creates_missing_file_with_defaults(self, tmp_path: Path):
        path = tmp_path / "new.json"
        payload = {"ok": True}

        await ensure_json_file(path, payload)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == payload

    async def test_preserves_existing_valid_json(self, tmp_path: Path):
        path = tmp_path / "existing.json"
        original = {"value": 1}
        path.write_text(json.dumps(original), encoding="utf-8")

        await ensure_json_file(path, {"value": 2})

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == original

    async def test_rewrites_invalid_json_with_default_payload(self, tmp_path: Path):
        path = tmp_path / "broken.json"
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write("{not-json")

        await ensure_json_file(path, {"fixed": True})

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"fixed": True}
