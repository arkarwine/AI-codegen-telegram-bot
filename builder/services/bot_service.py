"""Builder-side bot management service."""

from __future__ import annotations

import json
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord, User
from schemas.bot_schema import normalize_bot_schema, validate_bot_schema
from services.ai import AiSchemaService


class BuilderService:
    """Coordinates user, schema, bot, analytics, and import/export actions."""

    def __init__(self, database: Database, ai: AiSchemaService) -> None:
        self.database = database
        self.ai = ai

    async def user(self, telegram_id: int, username: str | None) -> User:
        return await self.database.upsert_user(telegram_id, username)

    async def create_bot_from_prompt(
        self,
        user: User,
        name: str,
        username: str | None,
        token: str,
        prompt: str,
    ) -> BotRecord:
        schema = await self.ai.create_schema(prompt)
        return await self.database.create_bot(user.id, name, username, token, schema, enabled=False)

    async def get_user_bot(self, owner_id: int, bot_id: int) -> BotRecord:
        bot = await self.database.get_bot(bot_id)
        if bot.owner_id != owner_id:
            raise LookupError("Bot not found.")
        return bot

    async def edit_bot(self, owner_id: int, bot_id: int, instruction: str) -> None:
        bot = await self.get_user_bot(owner_id, bot_id)
        schema = json.loads(bot.schema_json)
        new_schema = await self.ai.modify_schema(schema, instruction)
        await self.database.update_bot_schema(bot_id, new_schema)

    async def set_bot_enabled(self, owner_id: int, bot_id: int, enabled: bool) -> None:
        await self.get_user_bot(owner_id, bot_id)
        await self.database.set_bot_enabled(bot_id, enabled)

    async def analytics_counts(self, owner_id: int, bot_id: int) -> dict[str, int]:
        await self.get_user_bot(owner_id, bot_id)
        return await self.database.analytics_counts(bot_id)

    async def import_schema(self, user: User, name: str, token: str, raw_json: str) -> BotRecord:
        schema: dict[str, Any] = json.loads(raw_json)
        schema = normalize_bot_schema(schema)
        validate_bot_schema(schema)
        return await self.database.create_bot(user.id, name, None, token, schema, enabled=False)
