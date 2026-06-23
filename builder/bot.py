"""Builder Bot service bootstrap."""

from __future__ import annotations

from builder.handlers.commands import register_handlers
from builder.services.bot_service import BuilderService
from database.sqlite import Database
from services.ai import AiSchemaService
from utils.config import Settings, require


async def run_builder_bot() -> None:
    from pyrogram import Client

    settings = Settings.from_env()
    token = require(settings.builder_bot_token, "BUILDER_BOT_TOKEN")
    database = Database(settings.database_path)
    await database.connect()
    app = Client(
        "builder_bot",
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        bot_token=token,
        workdir="sessions",
    )
    register_handlers(app, BuilderService(database, AiSchemaService()))
    try:
        await app.start()
        await __import__("asyncio").Event().wait()
    finally:
        await app.stop()
        await database.close()
