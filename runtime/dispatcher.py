"""Workflow/state-machine dispatcher."""

from __future__ import annotations

import json
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord
from plugins.base import PluginContext
from plugins.registry import PluginRegistry
from runtime.sessions import SessionStore
from schemas.bot_schema import validate_bot_schema


class WorkflowDispatcher:
    """Executes schema flows as state machines for one deployed bot."""

    def __init__(self, database: Database, registry: PluginRegistry) -> None:
        self.database = database
        self.registry = registry
        self.sessions = SessionStore(database)

    async def dispatch(self, bot: BotRecord, client: Any, message: Any) -> None:
        schema = json.loads(bot.schema_json)
        validate_bot_schema(schema, set(self.registry.plugins))
        event_message = getattr(message, "message", message)
        user_id = int(message.from_user.id)
        text = _message_text(message)
        current_flow, current_step, data = await self.sessions.load(bot.id, user_id)

        waiting_variable = data.pop("_waiting_variable", None)
        if waiting_variable and text:
            data[str(waiting_variable)] = text

        flow = _find_flow(schema, text, current_flow)
        if flow is None:
            return

        start_index = current_step if current_flow == flow["id"] else 0
        await self.database.record_event(bot.id, "message")
        next_step = await self._run_steps(bot, client, event_message, user_id, flow, start_index, data)
        await self.sessions.save(bot.id, user_id, flow["id"] if next_step is not None else None, next_step or 0, data)

    async def _run_steps(
        self,
        bot: BotRecord,
        client: Any,
        message: Any,
        user_id: int,
        flow: dict[str, Any],
        start_index: int,
        data: dict[str, Any],
    ) -> int | None:
        steps = flow["steps"]
        index = start_index
        while index < len(steps):
            step = steps[index]
            context = PluginContext(
                bot_id=bot.id,
                user_id=user_id,
                client=client,
                message=message,
                session_data=data,
                services={"database": self.database},
            )
            plugin = self.registry.get(str(step["type"]))
            result = await plugin.execute(step, context)
            data.update(result.get("data", {}))
            if result.get("stop"):
                return None
            if variable := result.get("variable"):
                data["_waiting_variable"] = variable
            if result.get("wait"):
                return index + 1
            if result.get("skip_next"):
                index += 2
            else:
                index += 1
        return None


def _message_text(message: Any) -> str:
    if getattr(message, "text", None):
        return str(message.text)
    if getattr(message, "data", None):
        return str(message.data)
    return ""


def _find_flow(schema: dict[str, Any], text: str, current_flow: str | None) -> dict[str, Any] | None:
    flows = schema["flows"]
    for flow in flows:
        trigger = str(flow["trigger"])
        if trigger == text or (trigger.startswith("/") and text.split(maxsplit=1)[0] == trigger):
            return flow
    if current_flow:
        return next((flow for flow in flows if flow["id"] == current_flow), None)
    return None
