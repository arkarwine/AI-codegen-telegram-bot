"""SQLite-backed runtime session helpers."""

from __future__ import annotations

import json
from typing import Any

from database.sqlite import Database


class SessionStore:
    """Persists flow state so bots survive runtime restarts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def load(self, bot_id: int, user_id: int) -> tuple[str | None, int, dict[str, Any]]:
        record = await self.database.get_session(bot_id, user_id)
        data = json.loads(record.session_data_json)
        if not isinstance(data, dict):
            data = {}
        return record.current_flow, record.current_step, data

    async def save(
        self,
        bot_id: int,
        user_id: int,
        flow: str | None,
        step: int,
        data: dict[str, Any],
    ) -> None:
        await self.database.save_session(bot_id, user_id, flow, step, data)
