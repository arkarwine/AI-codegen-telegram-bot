"""Builder-side bot management service."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord, User
from schemas.bot_schema import normalize_bot_schema, validate_bot_schema
from services.ai import AiSchemaService


class BuilderService:
    """Coordinates user, schema, bot, analytics, and import/export actions."""

    def __init__(
        self,
        database: Database,
        ai: AiSchemaService,
        telegram_api_id: int,
        telegram_api_hash: str,
        owner_telegram_id: int | None = None,
    ) -> None:
        self.database = database
        self.ai = ai
        self.telegram_api_id = telegram_api_id
        self.telegram_api_hash = telegram_api_hash
        self.owner_telegram_id = owner_telegram_id

    async def user(self, telegram_id: int, username: str | None) -> User:
        return await self.database.upsert_user(telegram_id, username)

    async def create_bot_from_prompt(
        self,
        user: User,
        name: str,
        token: str,
        prompt: str,
    ) -> BotRecord:
        username = await self.validate_bot_token(token)
        schema = await self.ai.create_schema(prompt)
        return await self.database.create_bot(user.id, name, username, token, schema, enabled=True)

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
        bot = await self.get_user_bot(owner_id, bot_id)
        if enabled:
            username = await self.validate_bot_token(bot.token)
            await self.database.update_bot_identity(bot_id, username)
        await self.database.set_bot_enabled(bot_id, enabled)

    async def analytics_counts(self, owner_id: int, bot_id: int) -> dict[str, int]:
        await self.get_user_bot(owner_id, bot_id)
        return await self.database.analytics_counts(bot_id)

    async def runtime_snapshot(self) -> dict[str, Any]:
        snapshot = await self.database.get_setting("runtime:snapshot")
        return snapshot if isinstance(snapshot, dict) else {}

    def is_platform_admin(self, telegram_id: int) -> bool:
        return self.owner_telegram_id is None or telegram_id == self.owner_telegram_id

    async def import_schema(self, user: User, name: str, token: str, raw_json: str) -> BotRecord:
        schema: dict[str, Any] = json.loads(raw_json)
        schema = normalize_bot_schema(schema)
        validate_bot_schema(schema)
        username = await self.validate_bot_token(token)
        return await self.database.create_bot(user.id, name, username, token, schema, enabled=True)

    async def validate_bot_token(self, token: str) -> str | None:
        """Start a short-lived Telegram bot client and return its username."""

        from pyrogram import Client

        if not token or ":" not in token:
            raise ValueError("Bot token format is invalid.")
        if not self.telegram_api_id or not self.telegram_api_hash:
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required to validate bot tokens.")

        session_dir = Path("sessions") / "token_checks"
        session_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        client = Client(
            f"token_check_{digest}",
            api_id=self.telegram_api_id,
            api_hash=self.telegram_api_hash,
            bot_token=token,
            workdir=str(session_dir),
        )
        started = False
        try:
            await client.start()
            started = True
            me = await client.get_me()
            if not getattr(me, "is_bot", False):
                raise ValueError("Token belongs to a non-bot account.")
            username = getattr(me, "username", None)
            return str(username) if username else None
        except Exception as exc:
            raise ValueError(f"Bot token validation failed: {exc}") from exc
        finally:
            if started:
                await client.stop()
