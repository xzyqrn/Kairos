#!/usr/bin/env python3
"""
scripts/migrate_json_to_sqlite.py — One-time migration from JSON files to SQLite.

Run this script ONCE before deploying the updated bot to preserve any existing
live data from the legacy JSON stores.

Usage:
    python scripts/migrate_json_to_sqlite.py

It is safe to run multiple times — all inserts use INSERT OR IGNORE.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "history.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_prayer_requests(conn: sqlite3.Connection) -> int:
    src = DATA / "prayer_requests.json"
    if not src.exists():
        print(f"  [skip] {src.name} not found")
        return 0

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)

    requests = data.get("requests", []) if isinstance(data, dict) else []
    count = 0
    for req in requests:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO prayer_requests
                    (id, guild_id, user_id, request, anonymous, timestamp, answered)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(req["id"]),
                    str(req["guild_id"]),
                    str(req["user_id"]),
                    str(req.get("request", "")),
                    1 if req.get("anonymous") else 0,
                    str(req.get("timestamp", "")),
                    1 if req.get("answered") else 0,
                ),
            )
            count += 1
        except Exception as exc:
            print(f"  [warn] Skipped prayer request {req.get('id', '?')}: {exc}")

    conn.commit()
    return count


def migrate_quiz_scores(conn: sqlite3.Connection) -> int:
    src = DATA / "quiz_scores.json"
    if not src.exists():
        print(f"  [skip] {src.name} not found")
        return 0

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    if not isinstance(data, dict):
        print(f"  [warn] {src.name} has unexpected format, skipping")
        return 0

    for guild_id, users in data.items():
        if not isinstance(users, dict):
            continue
        for user_id, stats in users.items():
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO quiz_scores
                        (guild_id, user_id, display_name, score, correct, total)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        str(user_id),
                        str(stats.get("name", f"User {user_id}")),
                        int(stats.get("score", 0)),
                        int(stats.get("correct", 0)),
                        int(stats.get("total", 0)),
                    ),
                )
                count += 1
            except Exception as exc:
                print(f"  [warn] Skipped quiz score {guild_id}/{user_id}: {exc}")

    conn.commit()
    return count


def migrate_streaks(conn: sqlite3.Connection) -> int:
    src = DATA / "streaks.json"
    if not src.exists():
        print(f"  [skip] {src.name} not found")
        return 0

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    if not isinstance(data, dict):
        print(f"  [warn] {src.name} has unexpected format, skipping")
        return 0

    for user_id, stats in data.items():
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO streaks
                    (user_id, current_streak, longest_streak, total_devotions, last_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(user_id),
                    int(stats.get("current_streak", 0)),
                    int(stats.get("longest_streak", 0)),
                    int(stats.get("total_devotions", 0)),
                    stats.get("last_date"),
                ),
            )
            count += 1
        except Exception as exc:
            print(f"  [warn] Skipped streak for user {user_id}: {exc}")

    conn.commit()
    return count


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Start the bot once first to create the database, then re-run this script.")
        sys.exit(1)

    print(f"Migrating to: {DB_PATH}")
    conn = get_conn()

    try:
        print("\nMigrating prayer_requests.json …")
        n = migrate_prayer_requests(conn)
        print(f"  Inserted {n} prayer request(s)")

        print("\nMigrating quiz_scores.json …")
        n = migrate_quiz_scores(conn)
        print(f"  Inserted {n} quiz score row(s)")

        print("\nMigrating streaks.json …")
        n = migrate_streaks(conn)
        print(f"  Inserted {n} streak row(s)")

        print("\n✅ Migration complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
