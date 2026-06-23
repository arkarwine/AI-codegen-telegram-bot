"""Builder Bot service bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path

from builder.handlers.commands import register_handlers
from builder.services.bot_service import BuilderService
from database.sqlite import Database
from services.ai import AiSchemaService
from utils.config import Settings, configure_logging, require


logger = logging.getLogger(__name__)


async def run_builder_bot() -> None:
    from pyrogram import Client

    configure_logging("builder-bot")
    settings = Settings.from_env()
    token = require(settings.builder_bot_token, "BUILDER_BOT_TOKEN")
    session_dir = Path("sessions")
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.info("starting with database=%s", settings.database_path)
    database = Database(settings.database_path)
    await database.connect()
    app = Client(
        "builder_bot",
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        bot_token=token,
        workdir=str(session_dir),
    )
    register_handlers(app, BuilderService(database, AiSchemaService()))
    started = False
    try:
        await app.start()
        started = True
        logger.info("builder bot is running")
        await __import__("asyncio").Event().wait()
    finally:
        logger.info("stopping")
        if started:
            await app.stop()
        await database.close()
