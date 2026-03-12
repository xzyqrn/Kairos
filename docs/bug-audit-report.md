# Bug Audit Report

This audit focused on stabilizing the existing quality gate first, then fixing runtime risks in listener, scheduler, and config-driven flows.

## Findings

### P1: Mention chat had no cooldown protection
- Status: Fixed
- Reproduction path: Mention Kairos repeatedly in a guild channel; the bot would process each message immediately because the non-slash listener path never called the in-memory cooldown helper.
- Likely root cause: Mention chat was moved into `cogs/chat_listener.py`, but the listener did not carry over the dedicated non-slash cooldown contract from `utils/rate_limiter.py`.
- Preventing test: `tests/test_cog_chat.py::TestChatMentionRateLimit::test_rate_limited_mentions_reply_without_calling_ai`

### P1: Mention chat could respond to other bots and create reply loops
- Status: Fixed
- Reproduction path: Another bot mentions Kairos in a guild channel; Kairos would treat it as a normal user message because only self-messages were ignored.
- Likely root cause: The listener guarded against `self.bot.user` only, not all bot-authored messages.
- Preventing test: `tests/test_cog_chat.py::TestChatMentionRateLimit::test_bot_authors_are_ignored`

### P2: Prayer wall posting assumed every configured/current channel was message-sendable
- Status: Fixed
- Reproduction path: Configure a stale channel ID or invoke `/prayer_wall` from a non-sendable channel context; the code would rely on broad union types and could fail later on `send()`/`mention`.
- Likely root cause: Channel lookup results from Discord were not narrowed before use, so both runtime safety and static typing depended on optimistic assumptions.
- Preventing tests:
  - `tests/test_welcome_wall.py::TestPrayerWall::test_missing_configured_channel_returns_error`
  - `tests/test_welcome_wall.py::TestPrayerWall::test_non_sendable_current_channel_returns_error`

### P2: Scheduler duplicate-send protection lacked a direct regression test
- Status: Fixed
- Reproduction path: A future refactor could accidentally post the daily verse twice on the same date because the `was_daily_sent()` guard was not directly covered.
- Likely root cause: Existing scheduler tests covered matching times and misses, but not the already-sent branch.
- Preventing test: `tests/test_cog_scheduler.py::TestRunDueDailyVerses::test_skips_when_daily_verse_was_already_sent`

### P3: Test suite drifted from the current chat architecture
- Status: Fixed
- Reproduction path: Run `pytest`; the old tests patched `cogs.chat.Chat.on_message`, even though mention-chat behavior now lives in `cogs/chat_listener.py`.
- Likely root cause: The implementation moved, but the tests kept targeting the old ownership boundary.
- Preventing tests: the updated `tests/test_cog_chat.py` now exercises `cogs/chat_listener.py` directly.
