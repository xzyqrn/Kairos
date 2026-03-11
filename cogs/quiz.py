"""
cogs/quiz.py — Bible Quiz + Leaderboard.

Commands:
  /quiz              — AI generates a 4-option MCQ; 30-second timer; +10 pts per correct answer
  /quiz_leaderboard  — Top 10 per server
  /quiz_reset        — Reset the leaderboard (Admin only)

Storage: data/history.db (quiz_scores table)
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypedDict

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import ai_client
from utils.quiz_store import quiz_store
from utils.rate_limiter import cooldown, guild_rate_limit, handle_cooldown_error

log = logging.getLogger("kairos.quiz")

_QUIZ_TIMEOUT = 30  # seconds
_POINTS_PER_CORRECT = 10
_QUIZ_LETTERS = ("A", "B", "C", "D")


# ── Question parsing ──────────────────────────────────────────────────────────

_LETTER_PATTERN = re.compile(r"^[A-Da-d]$")

_OPTION_PREFIX = re.compile(
    r"^\s*(?:[\(\[]([A-D])[\)\]]|([A-D])[).:\]])\s*(.+?)\s*$",
    re.IGNORECASE,
)


class QuizQuestion(TypedDict):
    question: str
    options: list[str]
    answer: str
    explanation: str


def _split_labeled_option(option: str) -> tuple[str, str] | None:
    """Return a labeled option as ``(letter, text)`` when it uses an A-D prefix."""
    m = _OPTION_PREFIX.match(option)
    if m is None:
        return None
    letter = m.group(1) or m.group(2)
    text = m.group(3).strip()
    if not letter or not text:
        return None
    return (letter.upper(), text)


def _canonicalize_options(options: list[object]) -> list[str] | None:
    """Normalize options into `A. ...` through `D. ...`, rejecting mixed labeling."""
    normalized = [str(option).strip() for option in options]
    if any(not option for option in normalized):
        return None

    labeled = [_split_labeled_option(option) for option in normalized]
    has_labels = [item is not None for item in labeled]

    if all(has_labels):
        letters = [item[0] for item in labeled if item is not None]
        if letters != list(_QUIZ_LETTERS):
            return None
        texts = [item[1] for item in labeled if item is not None]
        return [f"{letter}. {text}" for letter, text in zip(_QUIZ_LETTERS, texts, strict=True)]

    if any(has_labels):
        return None

    return [f"{letter}. {text}" for letter, text in zip(_QUIZ_LETTERS, normalized, strict=True)]


def _parse_question(raw: str) -> QuizQuestion | None:
    """
    Extract and validate a JSON quiz question block from an AI response string.

    The AI is expected to return a JSON object with keys: question, options,
    answer, explanation. This function strips markdown code fences, locates the
    first JSON object in the string, and validates the schema.

    Args:
        raw: The raw string returned by the AI provider.

    Returns:
        A validated dict with keys question, options, answer, explanation,
        or None if the string cannot be parsed or fails validation.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # Find first {...} block
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return None

    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None

    required_keys = {"question", "options", "answer", "explanation"}
    if not required_keys.issubset(obj.keys()):
        return None

    options = obj["options"]
    if not isinstance(options, list) or len(options) != 4:
        return None

    answer = str(obj["answer"]).strip().upper()
    if not _LETTER_PATTERN.match(answer):
        return None

    canonical_options = _canonicalize_options(options)
    if canonical_options is None:
        return None

    return {
        "question": str(obj["question"]),
        "options": canonical_options,
        "answer": answer,
        "explanation": str(obj["explanation"]),
    }


# ── Answer buttons ────────────────────────────────────────────────────────────

class QuizView(discord.ui.View):
    LABELS = list(_QUIZ_LETTERS)

    def __init__(
        self,
        question_data: QuizQuestion,
        guild_id: str,
    ) -> None:
        super().__init__(timeout=_QUIZ_TIMEOUT)
        self.question_data = question_data
        self.guild_id = guild_id
        self.answered_users: set[int] = set()
        self.timed_out_flag = False

        for label in self.LABELS:
            self.add_item(QuizAnswerButton(label))

    async def on_timeout(self) -> None:
        self.timed_out_flag = True
        self.stop()


class QuizAnswerButton(discord.ui.Button[QuizView]):
    def __init__(self, letter: str) -> None:
        super().__init__(
            label=letter,
            style=discord.ButtonStyle.primary,
            custom_id=letter,
            row=0,
        )
        self.letter = letter

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return

        if interaction.user.id in view.answered_users:
            await interaction.response.send_message(
                "You already answered this question!", ephemeral=True
            )
            return

        view.answered_users.add(interaction.user.id)
        correct_letter = view.question_data["answer"]
        is_correct = self.letter.upper() == correct_letter

        entry = await quiz_store.record_answer(
            guild_id=view.guild_id,
            user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            correct=is_correct,
        )

        if is_correct:
            msg = (
                f"✅ **Correct, {interaction.user.display_name}!** +{_POINTS_PER_CORRECT} pts "
                f"(Total: {entry['score']})\n\n"
                f"📖 {view.question_data['explanation']}"
            )
        else:
            msg = (
                f"❌ **Not quite, {interaction.user.display_name}.** "
                f"The answer was **{correct_letter}**.\n\n"
                f"📖 {view.question_data['explanation']}"
            )

        await interaction.response.send_message(msg[:2000], ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Quiz(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── /quiz ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="quiz", description="Get an AI-generated Bible trivia question! 30-second timer.")
    @cooldown("quiz")
    @guild_rate_limit()
    async def quiz(self, interaction: discord.Interaction) -> None:
        """
        Generate an AI Bible trivia question with a 30-second timer and
        multiple-choice answer buttons.

        Awards 10 points per correct answer and records scores on the server
        leaderboard. Any server member can answer during the timer window.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        prompt = (
            "Generate a Bible trivia multiple-choice question for ages 13–25.\n"
            "Return ONLY a JSON object with exactly these fields:\n"
            "{\n"
            '  "question": "...",\n'
            '  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],\n'
            '  "answer": "A",\n'
            '  "explanation": "Brief explanation of why this is the answer (1-2 sentences)."\n'
            "}\n"
            "Do not include any text outside the JSON. The answer must be A, B, C, or D."
        )

        try:
            raw = await ai_client.generate_response(
                prompt=prompt,
                guild_id=str(interaction.guild_id),
                user_id=str(interaction.user.id),
            )
        except RuntimeError as exc:
            await interaction.followup.send(f"❌ Could not generate question: `{exc}`")
            return

        q = _parse_question(raw)
        if q is None:
            log.warning("Failed to parse quiz question. Raw: %s", raw[:300])
            await interaction.followup.send(
                "❌ The AI returned an unexpected format. Please try `/quiz` again."
            )
            return

        embed = discord.Embed(
            title="📖 Bible Quiz",
            description=f"**{q['question']}**",
            color=discord.Color.from_rgb(114, 137, 218),
        )
        for option in q["options"]:
            embed.add_field(name="\u200b", value=option, inline=False)
        embed.set_footer(text=f"⏱ {_QUIZ_TIMEOUT} seconds · anyone can answer · +{_POINTS_PER_CORRECT} pts for correct")

        view = QuizView(
            question_data=q,
            guild_id=str(interaction.guild_id),
        )

        msg = await interaction.followup.send(embed=embed, view=view, wait=True)

        # Wait for the view to finish (timeout or all buttons exhausted)
        await view.wait()

        # Edit the message to reveal the answer
        reveal_embed = discord.Embed(
            title="📖 Bible Quiz — Time's Up!",
            description=f"**{q['question']}**",
            color=discord.Color.green(),
        )
        for letter, option in zip(QuizView.LABELS, q["options"], strict=True):
            prefix = "✅ " if letter == q["answer"] else ""
            reveal_embed.add_field(name="\u200b", value=f"{prefix}{option}", inline=False)
        reveal_embed.add_field(
            name="Answer",
            value=f"**{q['answer']}** — {q['explanation']}",
            inline=False,
        )
        answered_count = len(view.answered_users)
        reveal_embed.set_footer(text=f"{answered_count} player(s) answered")

        try:
            await msg.edit(embed=reveal_embed, view=None)
        except discord.HTTPException:
            pass

    # ── /quiz_leaderboard ─────────────────────────────────────────────────────

    @app_commands.command(name="quiz_leaderboard", description="View the top 10 Bible quiz scores for this server.")
    async def quiz_leaderboard(self, interaction: discord.Interaction) -> None:
        """
        Display the top 10 Bible quiz scores for this server, sorted by total
        points with accuracy percentage shown for each player.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer()

        rows = await quiz_store.get_leaderboard(str(interaction.guild_id), limit=10)

        if not rows:
            await interaction.followup.send(
                "📊 No quiz scores yet! Use `/quiz` to be the first on the board."
            )
            return

        embed = discord.Embed(
            title="🏆 Bible Quiz Leaderboard",
            color=discord.Color.gold(),
        )
        medals = ["🥇", "🥈", "🥉"]

        for rank, stats in enumerate(rows, start=1):
            medal = medals[rank - 1] if rank <= 3 else f"**{rank}.**"
            name = stats.get("name", f"User {stats['user_id']}")
            score = stats.get("score", 0)
            correct = stats.get("correct", 0)
            total = stats.get("total", 0)
            accuracy = f"{(correct / total * 100):.0f}%" if total > 0 else "—"

            embed.add_field(
                name=f"{medal} {name}",
                value=f"`{score} pts` · {correct}/{total} correct ({accuracy})",
                inline=False,
            )

        embed.set_footer(text=f"Top {len(rows)} players · /quiz to play")
        await interaction.followup.send(embed=embed)

    # ── /quiz_reset ───────────────────────────────────────────────────────────

    @app_commands.command(name="quiz_reset", description="(Admin) Reset the quiz leaderboard for this server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def quiz_reset(self, interaction: discord.Interaction) -> None:
        """
        Reset the quiz leaderboard for this server, deleting all scores.

        Requires Administrator permission. This action cannot be undone.

        Args:
            interaction: The Discord interaction context.
        """
        if not interaction.guild_id:
            await interaction.response.send_message("Use this inside a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await quiz_store.reset_guild(str(interaction.guild_id))

        await interaction.followup.send("✅ Leaderboard has been reset.", ephemeral=True)

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
    await bot.add_cog(Quiz(bot))
