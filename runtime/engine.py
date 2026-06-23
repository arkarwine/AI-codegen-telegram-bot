"""Runtime Engine service bootstrap."""

from __future__ import annotations

from database.sqlite import Database
from plugins.registry import build_registry
from runtime.manager import RuntimeManager
from utils.config import Settings


async def run_runtime_engine() -> None:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    await database.connect()
    manager = RuntimeManager(settings, database, build_registry())
    try:
        await manager.run_forever()
    finally:
        await manager.stop()
        await database.close()
