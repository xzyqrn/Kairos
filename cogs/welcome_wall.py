"""
cogs/welcome_wall.py — Welcome messages & Prayer Wall.

Commands:
  /set_welcome_channel [channel]  — Set where welcome messages go (Admin)
  /set_prayer_wall_channel [channel] — Set where prayer wall posts go (Admin)
  /prayer_wall                     — Post current open requests as a public wall

Listeners:
  on_member_join — Sends a welcome message when new members join
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils.prayer_store import prayer_store
from utils.rate_limiter import handle_cooldown_error

log = logging.getLogger("kairos.welcome_wall")

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "welcome_wall.json"


async def _load_config() -> dict:
    """Load welcome/wall config from JSON."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        import aiofiles
        async with aiofiles.open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


async def _save_config(config: dict) -> None:
    """Save welcome/wall config to JSON."""
    import aiofiles
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        await f.write(json.dumps(config, indent=2))


class WelcomeWall(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Welcome Message ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Send a welcome message when a new member joins."""
        config = await _load_config()
        guild_config = config.get(str(member.guild.id), {})
        channel_id = guild_config.get("welcome_channel")

        if not channel_id:
            return

        channel = member.guild.get_channel(int(channel_id))
        if not channel:
            return

        embed = discord.Embed(
            title=f"🕊️ Welcome to {member.guild.name}!",
            description=(
                f"Hey {member.mention}! We're so glad you're here. 💙\n\n"
                "Here are some things you can do:\n"
                "• `/verse` — Look up any Bible verse\n"
                "• `/devotion` — Get a daily devotional\n"
                "• `/prayer_request` — Share a prayer request\n"
                "• `/dailyverse` — See today's verse\n\n"
                "May this community be a blessing to you! 🙏"
            ),
            color=discord.Color.from_rgb(74, 144, 226),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Failed to send welcome message for %s: %s", member.id, exc)

    # ── /set_welcome_channel ──────────────────────────────────────────────────

    @app_commands.command(
        name="set_welcome_channel",
        description="Set the channel where Kairos welcomes new members.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel to send welcome messages to")
    async def set_welcome_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return

        config = await _load_config()
        guild_key = str(interaction.guild_id)
        config.setdefault(guild_key, {})["welcome_channel"] = str(channel.id)
        await _save_config(config)

        await interaction.response.send_message(
            f"✅ Welcome messages will now be sent to {channel.mention}.",
            ephemeral=True,
        )

    # ── /set_prayer_wall_channel ──────────────────────────────────────────────

    @app_commands.command(
        name="set_prayer_wall_channel",
        description="Set the channel where prayer wall posts appear.",
    )
    @app_commands.describe(channel="The channel for public prayer wall posts")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def set_prayer_wall_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return

        config = await _load_config()
        guild_key = str(interaction.guild_id)
        config.setdefault(guild_key, {})["prayer_wall_channel"] = str(channel.id)
        await _save_config(config)

        await interaction.response.send_message(
            f"✅ Prayer wall will now post to {channel.mention}.",
            ephemeral=True,
        )

    # ── /prayer_wall ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="prayer_wall",
        description="Post open prayer requests to the public prayer wall.",
    )
    async def prayer_wall(self, interaction: discord.Interaction) -> None:
        """Post the current open prayer requests as a public embed."""
        if not interaction.guild_id:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return

        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        config = await _load_config()
        guild_config = config.get(guild_id, {})
        wall_channel_id = guild_config.get("prayer_wall_channel")

        # Use configured channel or the current channel
        if wall_channel_id:
            wall_channel = interaction.guild.get_channel(int(wall_channel_id))
            if not wall_channel:
                await interaction.followup.send(
                    "❌ The configured prayer wall channel wasn't found. "
                    "Use `/set_prayer_wall_channel` to set a new one."
                )
                return
        else:
            wall_channel = interaction.channel

        open_reqs = await prayer_store.list_open(guild_id)

        if not open_reqs:
            await interaction.followup.send(
                "🙏 No open prayer requests right now. Use `/prayer_request` to share one!"
            )
            return

        # Build the wall embed
        embed = discord.Embed(
            title="🙏 Prayer Wall",
            description=(
                f"**{len(open_reqs)}** open prayer request(s). "
                "React with 🙏 to show support.\n"
                "Use `/prayer_request` to add your own."
            ),
            color=discord.Color.from_rgb(138, 43, 226),
        )

        for req in open_reqs[:10]:  # Limit to 10 to avoid hitting embed limits
            req_id = str(req.get("id", "?"))[:8]
            user_id = req.get("user_id", "?")
            anon = req.get("anonymous", False)
            submitter = "Anonymous" if anon else f"<@{user_id}>"
            text = req.get("request", "")[:300]

            embed.add_field(
                name=f"#{req_id}",
                value=f"{text}\n— {submitter}",
                inline=False,
            )

        if len(open_reqs) > 10:
            embed.set_footer(text=f"Showing 10 of {len(open_reqs)} requests")

        try:
            if wall_channel == interaction.channel:
                msg = await interaction.followup.send(embed=embed, wait=True)
            else:
                msg = await wall_channel.send(embed=embed)
                await interaction.followup.send(
                    f"✅ Prayer wall posted to {wall_channel.mention}!"
                )

            # Add 🙏 reaction for engagement
            await msg.add_reaction("🙏")
        except discord.HTTPException as exc:
            log.warning("Failed to post prayer wall: %s", exc)

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if await handle_cooldown_error(interaction, error):
            return
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ You need Administrator permission to use this command."
        else:
            msg = f"❌ `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeWall(bot))
