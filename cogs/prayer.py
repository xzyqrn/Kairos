"""
cogs/prayer.py — Prayer Request Tracker.

Commands:
  /pray_request [request] [anonymous] — Submit a prayer request
  /pray_list                           — Paginated view of open requests
  /pray_answered [id]                  — Mark your own request (or Admin) as answered
  /pray_clear [id]                     — Delete a request (Admin only)

Weekly reminder: every Sunday 09:00 PHT, DM users with open requests.
Storage: data/history.db (prayer_requests table)
"""

from __future__ import annotations

import datetime
import logging
import re
import uuid

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.prayer_store import prayer_store
from utils.rate_limiter import cooldown, handle_cooldown_error

log = logging.getLogger("kairos.prayer")

_PHT = datetime.timezone(datetime.timedelta(hours=8))
_REMINDER_TIME = datetime.time(hour=9, minute=0, tzinfo=_PHT)
_PAGE_SIZE = 5
_REQUEST_ID_PREFIX = re.compile(r"^[0-9a-fA-F-]+$")


# ── Paginator view ────────────────────────────────────────────────────────────

class PrayerListView(discord.ui.View):
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
                "This list belongs to someone else.", ephemeral=True
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_pages(requests: list[dict]) -> list[discord.Embed]:
    """
    Build a list of paginated Discord embeds from a pre-filtered list of open
    prayer requests.

    Args:
        requests: Open (unanswered) prayer request dicts for a single guild.

    Returns:
        A list of discord.Embed pages (at least one page even if empty).
    """
    if not requests:
        return [
            discord.Embed(
                title="🙏 Prayer Requests",
                description="No open prayer requests right now. Be the first to submit one!",
                color=discord.Color.purple(),
            )
        ]

    pages: list[discord.Embed] = []
    total_pages = (len(requests) + _PAGE_SIZE - 1) // _PAGE_SIZE

    for page_num in range(total_pages):
        chunk = requests[page_num * _PAGE_SIZE:(page_num + 1) * _PAGE_SIZE]
        embed = discord.Embed(
            title="🙏 Open Prayer Requests",
            color=discord.Color.purple(),
        )
        embed.set_footer(text=f"Page {page_num + 1}/{total_pages} · {len(requests)} open request(s)")

        for req in chunk:
            req_id = str(req.get("id", "?"))[:8]  # show first 8 chars of UUID
            user_id = req.get("user_id", "?")
            anon = req.get("anonymous", False)
            ts = req.get("timestamp", "")[:10]

            name = f"#{req_id} · {ts}"
            submitter = "Anonymous 🙈" if anon else f"<@{user_id}>"
            value = f"{req.get('request', '')[:200]}\n— {submitter}"
            embed.add_field(name=name, value=value, inline=False)

        pages.append(embed)

    return pages


def _is_valid_request_prefix(prefix: str) -> bool:
    return bool(_REQUEST_ID_PREFIX.fullmatch(prefix))


# ── Cog ───────────────────────────────────────────────────────────────────────

class Prayer(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._reminder_task.start()

    async def cog_unload(self) -> None:
        self._reminder_task.cancel()

    @staticmethod
    def _ambiguous_request_message(request_id: str, matches: list[dict]) -> str:
        options = ", ".join(f"`{str(match.get('id', ''))[:8]}`" for match in matches[:5])
        suffix = " ..." if len(matches) > 5 else ""
        return (
            f"❌ `{request_id}` matches multiple requests ({options}{suffix}). "
            "Please use more characters."
        )

    # ── /pray_request ─────────────────────────────────────────────────────────

    @app_commands.command(name="prayer_request", description="Submit a prayer request to the community.")
    @app_commands.describe(
        request="Your prayer request",
        anonymous="Post anonymously? (your name won't be shown)",
    )
    @cooldown("prayer_request")
    async def prayer_request(
        self,
        interaction: discord.Interaction,
        request: str,
        anonymous: bool = False,
    ) -> None:
        """
        Submit a prayer request to the guild's shared prayer list.

        Args:
            interaction: The Discord interaction context.
            request: The text of the prayer request (max 1000 characters).
            anonymous: If True, the requester's name is hidden in the list.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        req_id = str(uuid.uuid4())
        await prayer_store.add(
            id=req_id,
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
            request=request[:1000],
            anonymous=anonymous,
            timestamp=datetime.datetime.now(_PHT).isoformat(),
        )

        short_id = req_id[:8]
        submitter = "anonymously" if anonymous else f"as **{interaction.user.display_name}**"

        await interaction.followup.send(
            f"🙏 Your prayer request has been submitted {submitter}.\n"
            f"Request ID: `{short_id}` — use this to mark it answered later.\n"
            f"The community will be praying for you! 💙",
            ephemeral=True,
        )

    # ── /pray_list ────────────────────────────────────────────────────────────

    @app_commands.command(name="prayer_list", description="View open community prayer requests.")
    async def prayer_list(self, interaction: discord.Interaction) -> None:
        """
        Display a paginated list of open prayer requests for this server.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        open_reqs = await prayer_store.list_open(str(interaction.guild_id))
        pages = _build_pages(open_reqs)
        view = PrayerListView(pages, interaction.user.id)

        await interaction.followup.send(embed=pages[0], view=view)

    # ── /pray_answered ────────────────────────────────────────────────────────

    @app_commands.command(name="prayer_answered", description="Mark a prayer request as answered.")
    @app_commands.describe(request_id="The first 8 characters of the request ID")
    async def prayer_answered(self, interaction: discord.Interaction, request_id: str) -> None:
        """
        Mark a prayer request as answered.

        Users can only mark their own requests. Administrators can mark any request.

        Args:
            interaction: The Discord interaction context.
            request_id: The first 8 characters of the UUID assigned to the request.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        prefix = request_id.strip()
        if not prefix:
            await interaction.followup.send("❌ Request ID cannot be empty.", ephemeral=True)
            return
        if not _is_valid_request_prefix(prefix):
            await interaction.followup.send(
                "❌ Request ID can only contain hexadecimal characters and hyphens.",
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.administrator  # type: ignore[union-attr]
        matches = await prayer_store.find_matches(guild_id, prefix, answered=False)

        if not matches:
            await interaction.followup.send(
                f"❌ No open request found with ID starting with `{request_id}`.",
                ephemeral=True,
            )
            return

        if len(matches) > 1:
            await interaction.followup.send(
                self._ambiguous_request_message(prefix, matches),
                ephemeral=True,
            )
            return

        target = matches[0]

        if not is_admin and str(target.get("user_id")) != str(interaction.user.id):
            await interaction.followup.send(
                "❌ You can only mark your own requests as answered.", ephemeral=True
            )
            return

        updated = await prayer_store.mark_answered(guild_id, str(target.get("id", "")))
        if not updated:
            await interaction.followup.send(
                f"❌ No open request found with ID starting with `{request_id}`.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"🎉 Praise God! Request `{str(target.get('id', ''))[:8]}` has been marked as answered. 🙌",
            ephemeral=True,
        )

    # ── /pray_clear ───────────────────────────────────────────────────────────

    @app_commands.command(name="prayer_clear", description="(Admin) Delete a prayer request.")
    @app_commands.describe(request_id="The first 8 characters of the request ID")
    @app_commands.checks.has_permissions(administrator=True)
    async def prayer_clear(self, interaction: discord.Interaction, request_id: str) -> None:
        """
        Permanently delete a prayer request from this server's list.

        Requires Administrator permission. Cannot be undone.

        Args:
            interaction: The Discord interaction context.
            request_id: The first 8 characters of the UUID assigned to the request.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        prefix = request_id.strip()
        if not prefix:
            await interaction.followup.send("❌ Request ID cannot be empty.", ephemeral=True)
            return
        if not _is_valid_request_prefix(prefix):
            await interaction.followup.send(
                "❌ Request ID can only contain hexadecimal characters and hyphens.",
                ephemeral=True,
            )
            return

        matches = await prayer_store.find_matches(str(interaction.guild_id), prefix)
        if not matches:
            await interaction.followup.send(
                f"❌ No request found with ID starting with `{request_id}`.", ephemeral=True
            )
            return

        if len(matches) > 1:
            await interaction.followup.send(
                self._ambiguous_request_message(prefix, matches),
                ephemeral=True,
            )
            return

        target = matches[0]
        deleted = await prayer_store.delete(str(interaction.guild_id), str(target.get("id", "")))

        if not deleted:
            await interaction.followup.send(
                f"❌ No request found with ID starting with `{request_id}`.", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ Request `{str(target.get('id', ''))[:8]}` deleted.", ephemeral=True
        )

    # ── Weekly DM reminder ────────────────────────────────────────────────────

    @tasks.loop(time=_REMINDER_TIME)
    async def _reminder_task(self) -> None:
        now_pht = datetime.datetime.now(_PHT)
        if now_pht.weekday() != 6:  # Sunday
            return

        log.info("Running Sunday prayer request reminder...")
        user_reqs = await prayer_store.list_all_open_by_user()

        for user_id, req_snippets in user_reqs.items():
            user = self.bot.get_user(int(user_id))
            if user is None:
                try:
                    user = await self.bot.fetch_user(int(user_id))
                except discord.NotFound:
                    continue

            count = len(req_snippets)
            try:
                embed = discord.Embed(
                    title="🙏 Your Prayer Requests Are Still Open",
                    description=(
                        f"Hey {user.display_name}! You have **{count}** unanswered prayer request(s).\n\n"
                        "Keep seeking God — He hears every prayer. 💙\n\n"
                        "\"Cast all your anxiety on him because he cares for you.\" — 1 Peter 5:7\n\n"
                        "When God answers, use `/prayer_answered` to celebrate with the community!"
                    ),
                    color=discord.Color.purple(),
                )
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass  # user has DMs disabled

    @_reminder_task.before_loop
    async def _before_reminder(self) -> None:
        await self.bot.wait_until_ready()

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if await handle_cooldown_error(interaction, error):
            return
        if isinstance(error, app_commands.MissingPermissions):
            msg = "❌ Administrator permission required."
        else:
            msg = f"❌ `{error}`"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Prayer(bot))
