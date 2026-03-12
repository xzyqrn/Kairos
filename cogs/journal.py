"""
cogs/journal.py — Private Devotion Journal.

Commands (all ephemeral — only visible to the user):
  /journal [entry]  — Write a private journal entry (stored per-user)
  /journal_view     — Browse your past entries (paginated, private)
  /journal_clear    — Delete all your journal entries

Storage: data/journal/{user_id}.json
  [ { "id": int, "timestamp": "ISO", "entry": "..." }, ... ]
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import Any

import aiofiles
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("kairos.journal")

_ROOT = Path(__file__).resolve().parent.parent
_JOURNAL_DIR = _ROOT / "data" / "journal"
_PHT = datetime.timezone(datetime.timedelta(hours=8))
_PAGE_SIZE = 3  # entries per page

_write_locks: dict[str, asyncio.Lock] = {}


def _get_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _write_locks:
        _write_locks[user_id] = asyncio.Lock()
    return _write_locks[user_id]


def _user_path(user_id: str) -> Path:
    return _JOURNAL_DIR / f"{user_id}.json"


# ── Storage helpers ───────────────────────────────────────────────────────────

async def _read_journal(user_id: str) -> list[dict[str, Any]]:
    path = _user_path(user_id)
    if not path.exists():
        return []
    async with aiofiles.open(path, encoding="utf-8") as f:
        raw = (await f.read()).strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def _write_journal(user_id: str, entries: list[dict[str, Any]]) -> None:
    path = _user_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with _get_lock(user_id):
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(entries, indent=2))


# ── Paginator ─────────────────────────────────────────────────────────────────

class JournalView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], requester_id: int) -> None:
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self.requester_id = requester_id
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who opened this journal can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


def _build_journal_pages(entries: list[dict[str, Any]], display_name: str) -> list[discord.Embed]:
    if not entries:
        return [
            discord.Embed(
                title="📓 My Journal",
                description="No entries yet. Use `/journal` to write your first one!",
                color=discord.Color.from_rgb(155, 89, 182),
            )
        ]

    # Newest first
    sorted_entries = sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)
    pages: list[discord.Embed] = []
    total_pages = (len(sorted_entries) + _PAGE_SIZE - 1) // _PAGE_SIZE

    for page_num in range(total_pages):
        chunk = sorted_entries[page_num * _PAGE_SIZE:(page_num + 1) * _PAGE_SIZE]
        embed = discord.Embed(
            title=f"📓 {display_name}'s Journal",
            color=discord.Color.from_rgb(155, 89, 182),
        )
        embed.set_footer(
            text=f"Page {page_num + 1}/{total_pages} · {len(entries)} total entries · Only visible to you"
        )
        for entry_data in chunk:
            ts = entry_data.get("timestamp", "")[:10]
            entry_id = entry_data.get("id", "?")
            text = entry_data.get("entry", "")[:500]
            embed.add_field(
                name=f"#{entry_id} · {ts}",
                value=text + ("…" if len(entry_data.get("entry", "")) > 500 else ""),
                inline=False,
            )
        pages.append(embed)

    return pages


# ── Cog ───────────────────────────────────────────────────────────────────────

class Journal(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /journal ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="journal",
        description="Save a private journal entry that only you can see.",
    )
    @app_commands.describe(
        entry="Write your prayer, reflection, or what God is teaching you",
    )
    async def journal(self, interaction: discord.Interaction, entry: str) -> None:
        """
        Write a private devotional journal entry visible only to the calling user.

        Entries are stored per-user in data/journal/{user_id}.json with a
        sequential ID and PHT timestamp. Entries are capped at 2000 characters.

        Args:
            interaction: The Discord interaction context.
            entry: The journal text to save.
        """
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        entries = await _read_journal(user_id)

        new_id = (max((e.get("id", 0) for e in entries), default=0)) + 1
        now = datetime.datetime.now(_PHT)

        new_entry: dict[str, Any] = {
            "id": new_id,
            "timestamp": now.isoformat(),
            "entry": entry[:2000],
        }
        entries.append(new_entry)
        await _write_journal(user_id, entries)

        embed = discord.Embed(
            title="📓 Journal Entry Saved",
            description=entry[:4000],
            color=discord.Color.from_rgb(155, 89, 182),
        )
        embed.add_field(name="Entry #", value=str(new_id), inline=True)
        embed.add_field(name="Date", value=f"{now.strftime('%B')} {now.day}, {now.year}", inline=True)
        embed.set_footer(
            text=f"Total entries: {len(entries)} · Use /journal_view to read past entries · Only you can see this"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /journal_view ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="journal_view",
        description="Read your past private journal entries.",
    )
    async def journal_view(self, interaction: discord.Interaction) -> None:
        """
        Browse the calling user's past journal entries in a paginated ephemeral view.

        Entries are shown newest-first, 3 per page. Navigation buttons allow
        moving between pages. Only the requesting user can see and navigate.

        Args:
            interaction: The Discord interaction context.
        """
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        entries = await _read_journal(user_id)
        pages = _build_journal_pages(entries, interaction.user.display_name)
        view = JournalView(pages, interaction.user.id)

        await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

    # ── /journal_clear ────────────────────────────────────────────────────────

    @app_commands.command(
        name="journal_clear",
        description="Delete all of your private journal entries.",
    )
    async def journal_clear(self, interaction: discord.Interaction) -> None:
        """
        Permanently delete all of the calling user's journal entries.

        This action cannot be undone. Only the calling user's entries are
        affected; other users' journals remain intact.

        Args:
            interaction: The Discord interaction context.
        """
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        entries = await _read_journal(user_id)

        if not entries:
            await interaction.followup.send("📓 You have no journal entries to delete.", ephemeral=True)
            return

        count = len(entries)
        await _write_journal(user_id, [])

        await interaction.followup.send(
            f"🗑️ **{count}** journal entry/entries permanently deleted. "
            "Use `/journal` to start fresh.",
            ephemeral=True,
        )

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        msg = f"❌ `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Journal(bot))
