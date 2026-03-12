"""
utils/scheduler_store.py — Persistent per-guild scheduler settings.

Stores per-server daily verse time and last sent date in JSON so schedules
survive bot restarts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiofiles

_ROOT_DIR = Path(__file__).resolve().parent.parent
_STORE_PATH = _ROOT_DIR / "data" / "scheduler_config.json"
_DEFAULT_DAILY_TIME = "07:00"


def _normalize_time(raw: str) -> str:
    parts = raw.split(":")
    if len(parts) != 2:
        return _DEFAULT_DAILY_TIME
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return _DEFAULT_DAILY_TIME
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return _DEFAULT_DAILY_TIME
    return f"{hour:02d}:{minute:02d}"


class SchedulerStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @staticmethod
    def _guild_key(guild_id: str) -> str:
        clean = str(guild_id).strip()
        if clean.startswith("guild_"):
            return clean
        return f"guild_{clean}"

    async def _ensure_file(self) -> None:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _STORE_PATH.exists():
            return
        async with aiofiles.open(_STORE_PATH, "w", encoding="utf-8") as target:
            await target.write("{}")

    async def _read_all(self) -> dict[str, Any]:
        await self._ensure_file()
        async with aiofiles.open(_STORE_PATH, encoding="utf-8") as source:
            raw = (await source.read()).strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def _write_all(self, payload: dict[str, Any]) -> None:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(_STORE_PATH, "w", encoding="utf-8") as target:
            await target.write(json.dumps(payload, indent=2))

    async def get_daily_time(self, guild_id: str) -> tuple[int, int]:
        data = await self._read_all()
        entry = data.get(self._guild_key(guild_id), {})
        raw = _DEFAULT_DAILY_TIME
        if isinstance(entry, dict):
            raw = _normalize_time(str(entry.get("daily_time", _DEFAULT_DAILY_TIME)))
        hour_str, minute_str = raw.split(":")
        return (int(hour_str), int(minute_str))

    async def set_daily_time(self, guild_id: str, hour: int, minute: int) -> str:
        formatted = _normalize_time(f"{hour:02d}:{minute:02d}")
        guild_key = self._guild_key(guild_id)
        async with self._lock:
            data = await self._read_all()
            entry = data.get(guild_key)
            if not isinstance(entry, dict):
                entry = {}
            entry["daily_time"] = formatted
            data[guild_key] = entry
            await self._write_all(data)
        return formatted

    async def was_daily_sent(self, guild_id: str, on_date: str) -> bool:
        data = await self._read_all()
        entry = data.get(self._guild_key(guild_id), {})
        if not isinstance(entry, dict):
            return False
        return str(entry.get("last_daily_sent", "")) == on_date

    async def mark_daily_sent(self, guild_id: str, on_date: str) -> None:
        guild_key = self._guild_key(guild_id)
        async with self._lock:
            data = await self._read_all()
            entry = data.get(guild_key)
            if not isinstance(entry, dict):
                entry = {}
            entry["last_daily_sent"] = on_date
            data[guild_key] = entry
            await self._write_all(data)


scheduler_store = SchedulerStore()
