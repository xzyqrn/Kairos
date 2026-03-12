from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

import aiofiles

# ── Optional AI provider packages ────────────────────────────────────────────
# Maps import name → human-readable description + pip install name
_OPTIONAL_DEPS: dict[str, tuple[str, str]] = {
    "anthropic":            ("Claude (Anthropic)",  "anthropic>=0.25.0"),
    "google.generativeai": ("Gemini (Google)",      "google-generativeai>=0.5.0"),
}


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"

JSON_DEFAULTS: dict[str, Any] = {
    "ai_config.json": {},
    "lang_prefs.json": {},
    # prayer_requests.json, quiz_scores.json, streaks.json migrated to SQLite
}

EXPECTED_EXTENSIONS = [
    "cogs.bible",
    "cogs.suggestions",
    "cogs.chat",
    "cogs.chat_listener",
    "cogs.scheduler",
    "cogs.prayer",
    "cogs.quiz",
    "cogs.journal",
    "cogs.streaks",
    "cogs.sermon",
    "cogs.moderation",
    "cogs.ai_admin",
    "cogs.welcome_wall",
]


def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "kairos.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("kairos")


async def ensure_json_file(path: Path, default_payload: Any) -> None:
    if path.exists():
        try:
            async with aiofiles.open(path, encoding="utf-8") as source:
                raw = await source.read()
            if raw.strip():
                json.loads(raw)
                return
        except Exception:
            pass

    async with aiofiles.open(path, "w", encoding="utf-8") as target:
        await target.write(json.dumps(default_payload, indent=2))


async def ensure_project_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    for filename, default_payload in JSON_DEFAULTS.items():
        await ensure_json_file(DATA_DIR / filename, default_payload)


def _probe_optional_deps(logger: logging.Logger) -> None:
    """
    Probe optional AI provider packages at startup and emit clear warnings if
    any are missing, rather than letting ImportError surface mid-command.
    """
    for import_name, (description, pip_name) in _OPTIONAL_DEPS.items():
        try:
            importlib.import_module(import_name)
            logger.info("Optional dep OK: %s (%s)", description, import_name)
        except ImportError:
            logger.warning(
                "Optional dep MISSING: %s — install with: pip install \"%s\"",
                description,
                pip_name,
            )


class KairosBot(commands.Bot):
    def __init__(self, logger: logging.Logger) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guild_messages = True
        intents.dm_messages = True

        super().__init__(command_prefix="!", intents=intents)
        self.logger = logger

    async def setup_hook(self) -> None:
        await ensure_project_files()
        _probe_optional_deps(self.logger)

        # Pre-warm SQLite stores (creates tables if not present — idempotent)
        from utils.prayer_store import prayer_store
        from utils.quiz_store import quiz_store
        from utils.streak_store import streak_store
        await prayer_store._ensure_ready()
        await quiz_store._ensure_ready()
        await streak_store._ensure_ready()

        for extension in EXPECTED_EXTENSIONS:
            extension_path = ROOT_DIR.joinpath(*extension.split(".")).with_suffix(".py")
            if not extension_path.exists():
                self.logger.warning("Skipping missing cog: %s", extension)
                continue

            try:
                await self.load_extension(extension)
                self.logger.info("Loaded cog: %s", extension)
            except Exception as exc:
                self.logger.exception("Failed to load cog %s: %s", extension, exc)

        try:
            synced = await self.tree.sync()
            self.logger.info("Synced %s global slash commands", len(synced))
        except Exception as exc:
            self.logger.exception("Failed to sync slash commands: %s", exc)

    async def on_ready(self) -> None:
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="over the flock 🕊️",
            )
        )
        self.logger.info("Connected as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")


async def run_bot() -> None:
    load_dotenv(ROOT_DIR / ".env")
    logger = configure_logging()
    await ensure_project_files()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in .env")

    bot = KairosBot(logger=logger)
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(run_bot())
