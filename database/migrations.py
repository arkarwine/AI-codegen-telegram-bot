"""SQLite schema migrations.

The migration runner is intentionally simple: the platform owns one SQLite file
and applies idempotent DDL at service startup.
"""

from __future__ import annotations

import aiosqlite


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    username TEXT,
    token TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    schema_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    current_flow TEXT,
    current_step INTEGER NOT NULL DEFAULT 0,
    session_data_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(bot_id, user_id)
);

CREATE TABLE IF NOT EXISTS plugins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS bots_touch_updated_at
AFTER UPDATE ON bots
BEGIN
    UPDATE bots SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


async def migrate(db: aiosqlite.Connection) -> None:
    """Apply all SQLite migrations."""

    await db.executescript(SCHEMA_SQL)
    await db.commit()
