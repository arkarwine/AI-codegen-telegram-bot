"""Builder Bot service bootstrap."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from builder.handlers.commands import register_handlers
from builder.services.bot_service import BuilderService
from database.sqlite import Database
from services.ai import AiSchemaService
from utils.config import Settings, configure_logging, require


logger = logging.getLogger(__name__)


BUILDER_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "Show help"),
    ("createbot", "Create a new bot"),
    ("editbot", "Edit a bot schema"),
    ("deletebot", "Delete a bot"),
    ("mybots", "List your bots"),
    ("status", "Show bot status"),
    ("viewschema", "View bot schema"),
    ("enable", "Enable a bot"),
    ("disable", "Disable a bot"),
    ("analytics", "Show bot analytics"),
    ("exportschema", "Export bot schema"),
    ("importschema", "Import a schema"),
    ("runtime", "Show runtime status"),
    ("cancel", "Cancel current flow"),
)


async def run_builder_bot() -> None:
    from pyrogram import Client
    from pyrogram.types import BotCommand

    configure_logging("builder-bot")
    settings = Settings.from_env()
    settings.validate_for_builder()
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
    register_handlers(
        app,
        BuilderService(
            database,
            AiSchemaService(),
            settings.telegram_api_id,
            settings.telegram_api_hash,
            settings.owner_telegram_id,
        ),
    )
    started = False
    try:
        await app.start()
        started = True
        await app.set_bot_commands(
            [BotCommand(command=command, description=description) for command, description in BUILDER_COMMANDS]
        )
        logger.info("builder bot is running")
        await asyncio.Event().wait()
    finally:
        logger.info("stopping")
        if started:
            await app.stop()
        await database.close()
