"""Multi-bot Kurigram manager with SQLite hot reload."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord
from plugins.registry import PluginRegistry
from runtime.dispatcher import WorkflowDispatcher
from schemas.bot_schema import validate_bot_schema
from utils.config import Settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunningBot:
    record: BotRecord
    client: Any


class RuntimeManager:
    """Hosts all enabled bots in one process and reconciles DB changes."""

    def __init__(self, settings: Settings, database: Database, registry: PluginRegistry) -> None:
        self.settings = settings
        self.database = database
        self.registry = registry
        self.dispatcher = WorkflowDispatcher(database, registry)
        self.running: dict[int, RunningBot] = {}
        self._stopping = asyncio.Event()

    async def run_forever(self) -> None:
        logger.info("hot-reload loop started")
        while not self._stopping.is_set():
            await self.reconcile()
            await asyncio.sleep(self.settings.runtime_poll_interval_seconds)

    async def stop(self) -> None:
        self._stopping.set()
        for bot_id in list(self.running):
            await self.stop_bot(bot_id)

    async def reconcile(self) -> None:
        records = {record.id: record for record in await self.database.list_runtime_bots()}
        enabled_count = sum(1 for record in records.values() if record.enabled)
        logger.debug("reconcile: total=%s enabled=%s running=%s", len(records), enabled_count, len(self.running))
        for bot_id, running in list(self.running.items()):
            record = records.get(bot_id)
            if record is None or not record.enabled or record.updated_at != running.record.updated_at:
                reason = "deleted" if record is None else "disabled" if not record.enabled else "modified"
                logger.info("stopping bot id=%s reason=%s", bot_id, reason)
                await self.stop_bot(bot_id)

        for record in records.values():
            if record.enabled and record.id not in self.running:
                await self.start_bot(record)

    async def start_bot(self, record: BotRecord) -> None:
        from pyrogram import Client, filters

        logger.info("starting bot id=%s name=%s username=%s", record.id, record.name, record.username)
        schema = __import__("json").loads(record.schema_json)
        validate_bot_schema(schema, set(self.registry.plugins))
        session_name = f"runtime_bot_{record.id}"
        session_dir = Path("sessions")
        session_dir.mkdir(parents=True, exist_ok=True)
        client = Client(
            session_name,
            api_id=self.settings.telegram_api_id,
            api_hash=self.settings.telegram_api_hash,
            bot_token=record.token,
            workdir=str(session_dir),
        )

        @client.on_message(filters.all)
        async def on_message(app: Any, message: Any) -> None:
            await self.dispatcher.dispatch(record, app, message)

        @client.on_callback_query()
        async def on_callback(app: Any, callback_query: Any) -> None:
            await self.dispatcher.dispatch(record, app, callback_query)

        await client.start()
        self.running[record.id] = RunningBot(record=record, client=client)
        logger.info("bot id=%s is running", record.id)

    async def stop_bot(self, bot_id: int) -> None:
        running = self.running.pop(bot_id, None)
        if running is not None:
            await running.client.stop()
            logger.info("bot id=%s stopped", bot_id)
