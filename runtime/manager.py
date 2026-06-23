"""Multi-bot Kurigram manager with SQLite hot reload."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord
from plugins.builtin import shutdown_scheduled_tasks
from plugins.registry import PluginRegistry
from runtime.dispatcher import WorkflowDispatcher
from schemas.bot_schema import normalize_bot_schema, validate_bot_schema
from utils.config import Settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunningBot:
    record: BotRecord
    client: Any
    signature: str


class RuntimeManager:
    """Hosts all enabled bots in one process and reconciles DB changes."""

    def __init__(self, settings: Settings, database: Database, registry: PluginRegistry) -> None:
        self.settings = settings
        self.database = database
        self.registry = registry
        self.dispatcher = WorkflowDispatcher(database, registry)
        self.running: dict[int, RunningBot] = {}
        self.failed_starts: dict[int, tuple[str, float]] = {}
        self.started_at = time.time()
        self._stopping = asyncio.Event()

    async def run_forever(self) -> None:
        logger.info("hot-reload loop started")
        while not self._stopping.is_set():
            await self.reconcile()
            await asyncio.sleep(self.settings.runtime_poll_interval_seconds)

    async def stop(self) -> None:
        self._stopping.set()
        await shutdown_scheduled_tasks()
        for bot_id in list(self.running):
            await self.stop_bot(bot_id)

    async def reconcile(self) -> None:
        records = {record.id: record for record in await self.database.list_runtime_bots()}
        enabled_count = sum(1 for record in records.values() if record.enabled)
        logger.debug("reconcile: total=%s enabled=%s running=%s", len(records), enabled_count, len(self.running))
        for bot_id, running in list(self.running.items()):
            record = records.get(bot_id)
            modified = record is not None and _record_signature(record) != running.signature
            if record is None or not record.enabled or modified:
                reason = "deleted" if record is None else "disabled" if not record.enabled else "modified"
                logger.info("stopping bot id=%s reason=%s", bot_id, reason)
                await self.stop_bot(bot_id)
                if record is None or modified:
                    self.failed_starts.pop(bot_id, None)

        now = asyncio.get_running_loop().time()
        for record in records.values():
            if record.enabled and record.id not in self.running:
                signature = _record_signature(record)
                failed = self.failed_starts.get(record.id)
                if failed and failed[0] == signature and failed[1] > now:
                    continue
                try:
                    await self.start_bot(record)
                    self.failed_starts.pop(record.id, None)
                except Exception as exc:
                    self.failed_starts[record.id] = (signature, now + 60)
                    await self.database.mark_bot_failed(record.id, str(exc))
                    logger.exception(
                        "failed to start bot id=%s name=%s; will retry in about 60 seconds",
                        record.id,
                        record.name,
                    )
        await self._write_snapshot(records)

    async def start_bot(self, record: BotRecord) -> None:
        from pyrogram import Client, filters

        logger.info("starting bot id=%s name=%s username=%s", record.id, record.name, record.username)
        schema = normalize_bot_schema(json.loads(record.schema_json))
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
            try:
                await callback_query.answer()
            except Exception:
                logger.debug("callback answer failed for bot id=%s", record.id, exc_info=True)
            await self.dispatcher.dispatch(record, app, callback_query)

        await client.start()
        await self.database.mark_bot_started(record.id)
        self.running[record.id] = RunningBot(
            record=record,
            client=client,
            signature=_record_signature(record),
        )
        logger.info("bot id=%s is running", record.id)

    async def stop_bot(self, bot_id: int) -> None:
        running = self.running.pop(bot_id, None)
        if running is not None:
            await running.client.stop()
            logger.info("bot id=%s stopped", bot_id)

    async def _write_snapshot(self, records: dict[int, BotRecord]) -> None:
        failed_bots = []
        for bot_id, failed in self.failed_starts.items():
            record = records.get(bot_id)
            failed_bots.append(
                {
                    "id": bot_id,
                    "name": record.name if record else "",
                    "retry_after_monotonic": failed[1],
                }
            )
        await self.database.set_setting(
            "runtime:snapshot",
            {
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "database_path": str(self.settings.database_path),
                "uptime_seconds": time.time() - self.started_at,
                "plugin_count": len(self.registry.plugins),
                "plugins": sorted(self.registry.plugins),
                "running_bot_ids": sorted(self.running),
                "failed_bots": failed_bots,
            },
        )


def _record_signature(record: BotRecord) -> str:
    return f"{record.token}\0{record.schema_json}"
