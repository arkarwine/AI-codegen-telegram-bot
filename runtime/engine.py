"""Runtime Engine service bootstrap."""

from __future__ import annotations

import logging

from database.sqlite import Database
from plugins.registry import build_registry
from runtime.manager import RuntimeManager
from utils.config import Settings, configure_logging


logger = logging.getLogger(__name__)


async def run_runtime_engine() -> None:
    configure_logging("runtime-engine")
    settings = Settings.from_env()
    settings.validate_for_runtime()
    logger.info("starting with database=%s poll_interval=%ss", settings.database_path, settings.runtime_poll_interval_seconds)
    database = Database(settings.database_path)
    await database.connect()
    registry = build_registry()
    logger.info("loaded %s plugin(s): %s", len(registry.plugins), ", ".join(sorted(registry.plugins)))
    manager = RuntimeManager(settings, database, registry)
    try:
        await manager.run_forever()
    finally:
        logger.info("stopping")
        await manager.stop()
        await database.close()
