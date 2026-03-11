"""
cogs/streaks.py — Devotion Streak Tracker.

Commands:
  /mystats  — Personal streak, longest streak, total devotions
  /streaks  — Top 10 devotion streaks in the server

Logic:
  - Streak increments when /devotion or /dailyverse is used on a given day
  - Reset if a full calendar day is skipped
  - Milestones at 7, 30, 100 days → congratulations message sent to the user

Storage: data/history.db (streaks table)
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.streak_store import streak_store

log = logging.getLogger("kairos.streaks")

_MILESTONES = {7, 30, 100}


# ── Cog ───────────────────────────────────────────────────────────────────────

class Streaks(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Public API (called by bible.py) ───────────────────────────────────────

    async def record_devotion(self, user_id: str) -> dict[str, Any]:
        """
        Increment the streak for a user.

        Called by bible.py after /devotion or /dailyverse.
        Handles streak logic (consecutive days, resets, milestones).

        Args:
            user_id: The Discord user ID as a string.

        Returns:
            The updated stats dict with keys: current_streak, longest_streak,
            total_devotions, last_date.
        """
        today = datetime.date.today().isoformat()
        entry = await streak_store.get(user_id) or {
            "current_streak": 0,
            "longest_streak": 0,
            "total_devotions": 0,
            "last_date": None,
        }

        last_date_str: str | None = entry.get("last_date")

        if last_date_str == today:
            # Already recorded today — no change
            return entry

        milestone_hit: int | None = None

        if last_date_str is not None:
            last_date = datetime.date.fromisoformat(last_date_str)
            delta = (datetime.date.today() - last_date).days

            if delta == 1:
                # Consecutive day
                entry["current_streak"] = entry.get("current_streak", 0) + 1
            elif delta > 1:
                # Missed a day — reset streak
                entry["current_streak"] = 1
            # delta == 0 handled above
        else:
            entry["current_streak"] = 1

        entry["total_devotions"] = entry.get("total_devotions", 0) + 1
        entry["last_date"] = today
        entry["longest_streak"] = max(
            entry.get("longest_streak", 0),
            entry["current_streak"],
        )

        if entry["current_streak"] in _MILESTONES:
            milestone_hit = entry["current_streak"]

        await streak_store.upsert(
            user_id=user_id,
            current_streak=entry["current_streak"],
            longest_streak=entry["longest_streak"],
            total_devotions=entry["total_devotions"],
            last_date=entry["last_date"],
        )

        if milestone_hit is not None:
            await self._send_milestone_dm(user_id, milestone_hit)

        return entry

    async def _send_milestone_dm(self, user_id: str, days: int) -> None:
        """Send a congratulations DM when a milestone is reached."""
        messages = {
            7:   ("🔥 7-Day Streak!", "You've been in the Word for **7 days in a row!** That's an amazing start — keep it up! \"Blessed is the man... whose delight is in the law of the LORD.\" — Psalm 1:1-2"),
            30:  ("🏆 30-Day Streak!", "**30 days of devotions! 🎉** You're building a real habit of seeking God daily. \"Draw near to God, and he will draw near to you.\" — James 4:8"),
            100: ("💎 100-Day Streak!", "**100 DAYS!! 🎊** You are an absolute inspiration! Your faithfulness is a testimony. \"Well done, good and faithful servant.\" — Matthew 25:23"),
        }

        title, body = messages.get(days, (f"{days}-Day Streak!", f"Congratulations on a {days}-day streak!"))

        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            embed = discord.Embed(title=title, description=body, color=discord.Color.gold())
            embed.set_footer(text="Kairos — Streak Milestone 🕊️")
            await user.send(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            log.warning("Could not send milestone DM to user %s: %s", user_id, exc)

    # ── /mystats ──────────────────────────────────────────────────────────────

    @app_commands.command(name="mystats", description="View your personal devotion streak and statistics.")
    async def mystats(self, interaction: discord.Interaction) -> None:
        """
        Display the calling user's personal devotion streak, longest streak,
        total devotions, and next milestone progress.

        Response is ephemeral (only visible to the requesting user).

        Args:
            interaction: The Discord interaction context.
        """
        await interaction.response.defer(ephemeral=True)

        entry = await streak_store.get(str(interaction.user.id))

        if not entry:
            await interaction.followup.send(
                "📊 No devotion stats yet!\n"
                "Use `/devotion` or `/dailyverse` to start your streak. 🔥",
                ephemeral=True,
            )
            return

        current = entry.get("current_streak", 0)
        longest = entry.get("longest_streak", 0)
        total = entry.get("total_devotions", 0)
        last_date = entry.get("last_date", "—")

        # Determine streak status
        if last_date != "—" and last_date is not None:
            delta = (datetime.date.today() - datetime.date.fromisoformat(last_date)).days
            if delta == 0:
                status = "🔥 Active — you've already done your devotion today!"
            elif delta == 1:
                status = "⚡ Active — do your devotion today to keep the streak!"
            else:
                status = f"💔 Broken — last devotion was {delta} day(s) ago."
        else:
            status = "Not started yet."

        # Next milestone
        next_milestone = next(
            (m for m in sorted(_MILESTONES) if m > current), None
        )
        next_milestone_text = (
            f"{next_milestone - current} day(s) to **{next_milestone}**-day milestone! 🎯"
            if next_milestone else "🏆 You've hit all milestones!"
        )

        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name}'s Devotion Stats",
            color=discord.Color.orange(),
        )
        embed.add_field(name="🔥 Current Streak", value=f"**{current}** day(s)", inline=True)
        embed.add_field(name="🏆 Longest Streak", value=f"**{longest}** day(s)", inline=True)
        embed.add_field(name="📖 Total Devotions", value=f"**{total}**", inline=True)
        embed.add_field(name="📅 Last Devotion", value=last_date or "—", inline=True)
        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(name="Next Milestone", value=next_milestone_text, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /streaks ──────────────────────────────────────────────────────────────

    @app_commands.command(name="streaks", description="View the top 10 devotion streaks in this server.")
    async def streaks(self, interaction: discord.Interaction) -> None:
        """
        Display the top 10 devotion streaks among members of this server,
        sorted by current streak length.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        # Filter to guild members only
        member_ids = [str(m.id) for m in interaction.guild.members]
        guild_data = await streak_store.get_many(member_ids)

        if not guild_data:
            await interaction.followup.send(
                "📊 No streak data for this server's members yet. Start with `/devotion` or `/dailyverse`!"
            )
            return

        sorted_users = sorted(
            guild_data.items(),
            key=lambda kv: kv[1].get("current_streak", 0),
            reverse=True,
        )[:10]

        embed = discord.Embed(
            title="🔥 Top 10 Devotion Streaks",
            color=discord.Color.orange(),
        )
        medals = ["🥇", "🥈", "🥉"]

        for rank, (user_id, stats) in enumerate(sorted_users, start=1):
            medal = medals[rank - 1] if rank <= 3 else f"**{rank}.**"
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else f"User {user_id}"
            current = stats.get("current_streak", 0)
            longest = stats.get("longest_streak", 0)
            total = stats.get("total_devotions", 0)
            embed.add_field(
                name=f"{medal} {name}",
                value=f"🔥 {current}-day streak · 🏆 Best: {longest} · 📖 Total: {total}",
                inline=False,
            )

        embed.set_footer(text="Keep showing up — every day counts! 💙")
        await interaction.followup.send(embed=embed)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        msg = f"❌ `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Streaks(bot))
