# Kairos Discord Bot

Kairos is a modular Python Discord bot focused on Christian youth communities.
It supports Bible utilities, prayer workflows, journaling, quizzes, moderation,
and configurable multi-provider AI chat.

## Tech Stack

- Python 3.11+
- `discord.py` for bot and slash commands
- `aiohttp` + provider SDKs for AI calls
- SQLite for conversation history
- `pytest` for tests

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Copy env template:
   `cp .env.example .env`
4. Set required values in `.env`:
   - `DISCORD_TOKEN`
   - Optional: `BIBLE_API_KEY`, `BIBLE_ID`, `DAILY_VERSE_CHANNEL`
5. Run the bot:
   `python main.py`

## Project Structure

- `main.py`: bootstrapping, logging, cog loading, startup checks
- `cogs/`: feature modules (slash commands + listeners)
- `utils/`: shared services and helpers (AI client, locale, history, rate limiting)
- `data/`: runtime JSON state and SQLite DB
- `tests/`: unit tests

## Quality Commands

- Run full local quality gate:
  `./scripts/quality.sh`
- Individual checks:
  - `pytest -q`
  - `ruff check .`
  - `mypy main.py cogs utils tests`
  - `PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m compileall main.py cogs utils tests`

If `ruff` and `mypy` are not installed yet:

`pip install -r requirements-dev.txt`

## CI

GitHub Actions workflow is provided at:

`/.github/workflows/ci.yml`

It runs tests, lint, and type-checks on pushes and pull requests.

## Branch Protection

Recommended branch protection settings are documented in:

`/docs/branch-protection.md`
