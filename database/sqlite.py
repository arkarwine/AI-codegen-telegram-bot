"""Async SQLite access layer."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiosqlite

from database.migrations import migrate
from models.entities import AnalyticsEvent, BotRecord, SessionRecord, User


class Database:
    """Small repository layer shared by both services."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await migrate(self.db)

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    def _conn(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("Database is not connected")
        return self.db

    async def upsert_user(self, telegram_id: int, username: str | None) -> User:
        db = self._conn()
        await db.execute(
            """
            INSERT INTO users (telegram_id, username) VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
            """,
            (telegram_id, username),
        )
        await db.commit()
        row = await self._fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return _user(row)

    async def create_bot(
        self,
        owner_id: int,
        name: str,
        username: str | None,
        token: str,
        schema: dict[str, Any],
        enabled: bool = False,
    ) -> BotRecord:
        db = self._conn()
        cursor = await db.execute(
            """
            INSERT INTO bots (owner_id, name, username, token, enabled, schema_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (owner_id, name, username, token, int(enabled), json.dumps(schema, separators=(",", ":"))),
        )
        await db.commit()
        return await self.get_bot(int(cursor.lastrowid))  # type: ignore[arg-type]

    async def update_bot_schema(self, bot_id: int, schema: dict[str, Any]) -> None:
        await self._conn().execute(
            "UPDATE bots SET schema_json = ? WHERE id = ?",
            (json.dumps(schema, separators=(",", ":")), bot_id),
        )
        await self._conn().commit()

    async def set_bot_enabled(self, bot_id: int, enabled: bool) -> None:
        await self._conn().execute("UPDATE bots SET enabled = ? WHERE id = ?", (int(enabled), bot_id))
        await self._conn().commit()

    async def delete_bot(self, bot_id: int, owner_id: int) -> bool:
        cursor = await self._conn().execute(
            "DELETE FROM bots WHERE id = ? AND owner_id = ?", (bot_id, owner_id)
        )
        await self._conn().commit()
        return cursor.rowcount > 0

    async def list_user_bots(self, owner_id: int) -> list[BotRecord]:
        rows = await self._fetchall("SELECT * FROM bots WHERE owner_id = ? ORDER BY id", (owner_id,))
        return [_bot(row) for row in rows]

    async def list_runtime_bots(self) -> list[BotRecord]:
        rows = await self._fetchall("SELECT * FROM bots ORDER BY id")
        return [_bot(row) for row in rows]

    async def get_bot(self, bot_id: int) -> BotRecord:
        row = await self._fetchone("SELECT * FROM bots WHERE id = ?", (bot_id,))
        return _bot(row)

    async def get_session(self, bot_id: int, user_id: int) -> SessionRecord:
        db = self._conn()
        await db.execute(
            """
            INSERT OR IGNORE INTO sessions (bot_id, user_id, session_data_json)
            VALUES (?, ?, '{}')
            """,
            (bot_id, user_id),
        )
        await db.commit()
        row = await self._fetchone(
            "SELECT * FROM sessions WHERE bot_id = ? AND user_id = ?", (bot_id, user_id)
        )
        return _session(row)

    async def save_session(
        self,
        bot_id: int,
        user_id: int,
        current_flow: str | None,
        current_step: int,
        data: dict[str, Any],
    ) -> None:
        await self._conn().execute(
            """
            UPDATE sessions
            SET current_flow = ?, current_step = ?, session_data_json = ?
            WHERE bot_id = ? AND user_id = ?
            """,
            (current_flow, current_step, json.dumps(data), bot_id, user_id),
        )
        await self._conn().commit()

    async def record_event(self, bot_id: int, event_type: str) -> None:
        await self._conn().execute(
            "INSERT INTO analytics (bot_id, event_type) VALUES (?, ?)", (bot_id, event_type)
        )
        await self._conn().commit()

    async def analytics_counts(self, bot_id: int) -> dict[str, int]:
        rows = await self._fetchall(
            "SELECT event_type, COUNT(*) AS count FROM analytics WHERE bot_id = ? GROUP BY event_type",
            (bot_id,),
        )
        return {str(row["event_type"]): int(row["count"]) for row in rows}

    async def _fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row:
        cursor = await self._conn().execute(sql, tuple(params))
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(sql)
        return row

    async def _fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        cursor = await self._conn().execute(sql, tuple(params))
        return list(await cursor.fetchall())


def _user(row: aiosqlite.Row) -> User:
    return User(int(row["id"]), int(row["telegram_id"]), row["username"], str(row["created_at"]))


def _bot(row: aiosqlite.Row) -> BotRecord:
    return BotRecord(
        id=int(row["id"]),
        owner_id=int(row["owner_id"]),
        name=str(row["name"]),
        username=row["username"],
        token=str(row["token"]),
        enabled=bool(row["enabled"]),
        schema_json=str(row["schema_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _session(row: aiosqlite.Row) -> SessionRecord:
    return SessionRecord(
        id=int(row["id"]),
        bot_id=int(row["bot_id"]),
        user_id=int(row["user_id"]),
        current_flow=row["current_flow"],
        current_step=int(row["current_step"]),
        session_data_json=str(row["session_data_json"]),
    )
