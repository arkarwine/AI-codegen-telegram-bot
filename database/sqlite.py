"""Async SQLite access layer."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiosqlite

from database.migrations import migrate
from models.entities import BotRecord, SessionRecord, User


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

    async def list_bot_user_ids(self, bot_id: int) -> list[int]:
        rows = await self._fetchall(
            "SELECT DISTINCT user_id FROM sessions WHERE bot_id = ? ORDER BY user_id",
            (bot_id,),
        )
        return [int(row["user_id"]) for row in rows]

    async def get_setting(self, key: str) -> Any:
        cursor = await self._conn().execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(str(row["value"]))

    async def set_setting(self, key: str, value: Any) -> None:
        await self._conn().execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, json.dumps(value)),
        )
        await self._conn().commit()

    async def get_variable(
        self,
        bot_id: int,
        scope: str,
        name: str,
        user_id: int | None = None,
    ) -> Any:
        return await self.get_setting(_variable_key(bot_id, scope, name, user_id))

    async def set_variable(
        self,
        bot_id: int,
        scope: str,
        name: str,
        value: Any,
        user_id: int | None = None,
    ) -> None:
        await self.set_setting(_variable_key(bot_id, scope, name, user_id), value)

    async def list_variables(
        self,
        bot_id: int,
        scope: str,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        prefix = _variable_key_prefix(bot_id, scope, user_id)
        rows = await self._fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (prefix + "%",),
        )
        values: dict[str, Any] = {}
        for row in rows:
            name = str(row["key"])[len(prefix) :]
            values[name] = json.loads(str(row["value"]))
        return values

    async def upsert_record(
        self,
        bot_id: int,
        collection: str,
        key: str,
        value: Any,
        scope: str = "global",
        user_id: int | None = None,
    ) -> None:
        owner_id = _record_owner(scope, user_id)
        await self._conn().execute(
            """
            INSERT INTO bot_records (bot_id, collection, scope, owner_id, record_key, value_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot_id, collection, scope, owner_id, record_key)
            DO UPDATE SET value_json = excluded.value_json
            """,
            (bot_id, collection, scope, owner_id, key, json.dumps(value)),
        )
        await self._conn().commit()

    async def get_record(
        self,
        bot_id: int,
        collection: str,
        key: str,
        scope: str = "global",
        user_id: int | None = None,
    ) -> Any:
        owner_id = _record_owner(scope, user_id)
        cursor = await self._conn().execute(
            """
            SELECT value_json FROM bot_records
            WHERE bot_id = ? AND collection = ? AND scope = ? AND owner_id = ? AND record_key = ?
            """,
            (bot_id, collection, scope, owner_id, key),
        )
        row = await cursor.fetchone()
        return None if row is None else json.loads(str(row["value_json"]))

    async def delete_record(
        self,
        bot_id: int,
        collection: str,
        key: str,
        scope: str = "global",
        user_id: int | None = None,
    ) -> bool:
        owner_id = _record_owner(scope, user_id)
        cursor = await self._conn().execute(
            """
            DELETE FROM bot_records
            WHERE bot_id = ? AND collection = ? AND scope = ? AND owner_id = ? AND record_key = ?
            """,
            (bot_id, collection, scope, owner_id, key),
        )
        await self._conn().commit()
        return cursor.rowcount > 0

    async def list_records(
        self,
        bot_id: int,
        collection: str,
        scope: str = "global",
        user_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        owner_id = _record_owner(scope, user_id)
        rows = await self._fetchall(
            """
            SELECT record_key, value_json, created_at, updated_at FROM bot_records
            WHERE bot_id = ? AND collection = ? AND scope = ? AND owner_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (bot_id, collection, scope, owner_id, max(1, min(limit, 200))),
        )
        return [
            {
                "key": str(row["record_key"]),
                "value": json.loads(str(row["value_json"])),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def count_records(
        self,
        bot_id: int,
        collection: str,
        scope: str = "global",
        user_id: int | None = None,
    ) -> int:
        owner_id = _record_owner(scope, user_id)
        cursor = await self._conn().execute(
            """
            SELECT COUNT(*) AS count FROM bot_records
            WHERE bot_id = ? AND collection = ? AND scope = ? AND owner_id = ?
            """,
            (bot_id, collection, scope, owner_id),
        )
        row = await cursor.fetchone()
        return 0 if row is None else int(row["count"])

    async def increment_record(
        self,
        bot_id: int,
        collection: str,
        key: str,
        amount: int | float = 1,
        scope: str = "global",
        user_id: int | None = None,
    ) -> int | float:
        current = await self.get_record(bot_id, collection, key, scope, user_id)
        base = current if isinstance(current, (int, float)) and not isinstance(current, bool) else 0
        numeric_amount = float(amount) if isinstance(amount, str) else amount
        value = base + numeric_amount
        await self.upsert_record(bot_id, collection, key, value, scope, user_id)
        return value

    async def append_record(
        self,
        bot_id: int,
        collection: str,
        key: str,
        item: Any,
        scope: str = "global",
        user_id: int | None = None,
    ) -> list[Any]:
        current = await self.get_record(bot_id, collection, key, scope, user_id)
        values = current if isinstance(current, list) else []
        values.append(item)
        await self.upsert_record(bot_id, collection, key, values, scope, user_id)
        return values

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


def _variable_key(bot_id: int, scope: str, name: str, user_id: int | None = None) -> str:
    if scope == "global":
        return f"bot:{bot_id}:global:{name}"
    if scope == "user":
        if user_id is None:
            raise ValueError("user_id is required for user scoped variables")
        return f"bot:{bot_id}:user:{user_id}:{name}"
    raise ValueError(f"unsupported variable scope: {scope}")


def _variable_key_prefix(bot_id: int, scope: str, user_id: int | None = None) -> str:
    if scope == "global":
        return f"bot:{bot_id}:global:"
    if scope == "user":
        if user_id is None:
            raise ValueError("user_id is required for user scoped variables")
        return f"bot:{bot_id}:user:{user_id}:"
    raise ValueError(f"unsupported variable scope: {scope}")


def _record_owner(scope: str, user_id: int | None = None) -> str:
    if scope == "global":
        return ""
    if scope == "user":
        if user_id is None:
            raise ValueError("user_id is required for user scoped records")
        return str(user_id)
    raise ValueError(f"unsupported record scope: {scope}")
