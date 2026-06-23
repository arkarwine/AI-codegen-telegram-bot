"""Built-in plugin actions.

No plugin evaluates user code. Each action accepts JSON config and calls a
bounded Python implementation owned by the platform.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from plugins.base import PluginContext


logger = logging.getLogger(__name__)
SCHEDULED_TASKS: set[asyncio.Task[None]] = set()


class SendMessagePlugin:
    name = "send_message"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        await context.message.reply_text(_render(str(config["text"]), context.session_data))
        return {}


class ButtonsPlugin:
    name = "buttons"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["buttons"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        from pyrogram.types import InlineKeyboardMarkup

        rows = _button_rows(config.get("buttons", []), context.session_data)
        await context.message.reply_text(
            _render(str(config.get("text", "Choose an option:")), context.session_data),
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return {}


class EditMessagePlugin:
    name = "edit_message"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        if hasattr(context.message, "edit_text"):
            await context.message.edit_text(str(config["text"]))
        return {}


class DeleteMessagePlugin:
    name = "delete_message"
    version = "1.0.0"
    config_schema = {"type": "object"}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        await context.message.delete()
        return {}


class WaitForInputPlugin:
    name = "wait_for_input"
    version = "1.0.0"
    config_schema = {"type": "object"}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        if prompt := config.get("prompt"):
            await context.message.reply_text(_render(str(prompt), context.session_data))
        return {"wait": True, "variable": config.get("variable", "last_input")}


class ConditionPlugin:
    name = "condition"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["variable"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        value = await _read_variable(config, context)
        matched = _matches(value, config)
        then_target = config.get("then")
        else_target = config.get("else")
        if matched and then_target:
            return {"goto": then_target}
        if not matched and else_target:
            return {"goto": else_target}
        if then_target or else_target:
            return {}
        return {"skip_next": not matched}


class SetVariablePlugin:
    name = "set_variable"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["name", "value"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        name = str(config["name"])
        scope = str(config.get("scope", "session"))
        value = config["value"]
        if scope == "session":
            return {"data": {name: value}}
        await context.services["database"].set_variable(
            context.bot_id,
            scope,
            name,
            value,
            context.user_id if scope == "user" else None,
        )
        return {"scoped_data": {scope: {name: value}}}


class GetVariablePlugin:
    name = "get_variable"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["name"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        value = await _read_variable(config, context)
        if save_as := config.get("save_as"):
            return {"data": {str(save_as): value}}
        await context.message.reply_text(str(value if value is not None else ""))
        return {}


class DatabaseQueryPlugin:
    name = "database_query"
    version = "1.0.0"
    config_schema = {"type": "object"}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        # This intentionally exposes bounded CRUD operations, not raw SQL.
        database = context.services["database"]
        action = str(config.get("action", "set" if "value" in config else "get"))
        collection = str(config.get("collection", "default"))
        scope = str(config.get("scope", "global"))
        user_id = context.user_id if scope == "user" else None
        key = str(config.get("key", ""))

        if action in {"set", "upsert", "save"}:
            _require_key(action, key)
            value = config.get("value")
            await database.upsert_record(context.bot_id, collection, key, value, scope, user_id)
            result: Any = {"key": key, "value": value}
        elif action in {"get", "read"}:
            _require_key(action, key)
            result = await database.get_record(context.bot_id, collection, key, scope, user_id)
        elif action == "delete":
            _require_key(action, key)
            result = await database.delete_record(context.bot_id, collection, key, scope, user_id)
        elif action == "list":
            result = await database.list_records(
                context.bot_id,
                collection,
                scope,
                user_id,
                int(config.get("limit", 50)),
            )
        elif action == "count":
            result = await database.count_records(context.bot_id, collection, scope, user_id)
        elif action == "exists":
            _require_key(action, key)
            result = (
                await database.get_record(context.bot_id, collection, key, scope, user_id)
            ) is not None
        elif action == "increment":
            _require_key(action, key)
            result = await database.increment_record(
                context.bot_id,
                collection,
                key,
                config.get("amount", 1),
                scope,
                user_id,
            )
        elif action == "append":
            _require_key(action, key)
            result = await database.append_record(
                context.bot_id,
                collection,
                key,
                config.get("item", config.get("value")),
                scope,
                user_id,
            )
        else:
            raise ValueError(f"unsupported database action: {action}")

        save_as = config.get("save_as")
        should_reply = bool(config.get("reply", save_as is None and action in {"get", "list", "count", "exists"}))
        if should_reply:
            await context.message.reply_text(_format_database_result(result))
        if save_as:
            return {"data": {str(save_as): result}}
        return {}


class HttpRequestPlugin:
    name = "http_request"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["url"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        # Network egress is deliberately centralized and timeout bounded.
        import urllib.request

        url = str(config["url"])
        timeout = float(config.get("timeout", 5))
        text = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=timeout).read(4096))
        variable = str(config.get("save_as", "http_response"))
        return {"data": {variable: text.decode("utf-8", errors="replace")}}


class AiChatPlugin:
    name = "ai_chat"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["prompt"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        from google import genai

        client = genai.Client()
        response = client.models.generate_content(
            model=str(config.get("model", "gemini-2.5-flash")),
            contents=_render(str(config["prompt"]), context.session_data),
        )
        await context.message.reply_text(response.text or "")
        return {}


class SchedulerPlugin:
    name = "scheduler"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["delay_seconds", "text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        text = _render(str(config["text"]), context.session_data)
        delay_seconds = float(config["delay_seconds"])

        async def later() -> None:
            await asyncio.sleep(delay_seconds)
            await context.message.reply_text(text)

        task = asyncio.create_task(later())
        SCHEDULED_TASKS.add(task)
        task.add_done_callback(_discard_scheduled_task)
        return {}


class BroadcastPlugin:
    name = "broadcast"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        text = _render(str(config["text"]), context.session_data)
        users = await context.services["database"].list_bot_user_ids(context.bot_id)
        sent = 0
        for user_id in users:
            if not config.get("include_self", True) and user_id == context.user_id:
                continue
            try:
                await context.client.send_message(user_id, text)
                sent += 1
            except Exception:
                continue
        await context.message.reply_text(f"Broadcast sent to {sent} user(s).")
        return {}


class AdminOnlyPlugin:
    name = "admin_only"
    version = "1.0.0"
    config_schema = {"type": "object"}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        admins = set(config.get("telegram_ids", []))
        if admins and context.user_id not in admins:
            await context.message.reply_text(str(config.get("denied_text", "Admins only.")))
            return {"stop": True}
        return {}


class AnalyticsPlugin:
    name = "analytics"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["event_type"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        await context.services["database"].record_event(context.bot_id, str(config["event_type"]))
        return {}


def _render(template: str, data: dict[str, Any]) -> str:
    text = template
    for key, value in data.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                text = text.replace("{{" + key + "." + str(nested_key) + "}}", str(nested_value))
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _button_rows(raw_buttons: Any, data: dict[str, Any]) -> list[list[Any]]:
    from pyrogram.types import InlineKeyboardButton

    if not isinstance(raw_buttons, list):
        return []
    source_rows = raw_buttons
    if raw_buttons and not isinstance(raw_buttons[0], list):
        source_rows = [[button] for button in raw_buttons]

    rows: list[list[Any]] = []
    for source_row in source_rows:
        row: list[Any] = []
        if not isinstance(source_row, list):
            source_row = [source_row]
        for item in source_row:
            if isinstance(item, dict):
                label = _render(str(item.get("text", item.get("label", ""))), data)
                value = _render(str(item.get("value", item.get("callback_data", label))), data)
            else:
                label = _render(str(item), data)
                value = label
            if label:
                row.append(InlineKeyboardButton(text=label, callback_data=value))
        if row:
            rows.append(row)
    return rows


def _require_key(action: str, key: str) -> None:
    if not key:
        raise ValueError(f"database action {action} requires key")


def _format_database_result(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


async def _read_variable(config: dict[str, Any], context: PluginContext) -> Any:
    name = str(config["variable"] if "variable" in config else config["name"])
    scope = str(config.get("scope", "session"))
    if scope == "session":
        return _lookup_path(context.session_data, name)
    return await context.services["database"].get_variable(
        context.bot_id,
        scope,
        name,
        context.user_id if scope == "user" else None,
    )


def _lookup_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matches(value: Any, config: dict[str, Any]) -> bool:
    operator = str(config.get("operator", "equals"))
    expected = config.get("equals", config.get("value"))
    try:
        if operator == "equals":
            return value == expected
        if operator == "not_equals":
            return value != expected
        if operator == "contains":
            return str(expected).lower() in str(value).lower()
        if operator == "not_contains":
            return str(expected).lower() not in str(value).lower()
        if operator == "exists":
            return value not in (None, "")
        if operator == "missing":
            return value in (None, "")
        if operator == "greater_than":
            return float(value) > float(expected)
        if operator == "less_than":
            return float(value) < float(expected)
        if operator == "in":
            return isinstance(expected, list) and value in expected
        if operator == "regex":
            return re.search(str(expected), str(value)) is not None
    except (TypeError, ValueError):
        return False
    return False


def _discard_scheduled_task(task: asyncio.Task[None]) -> None:
    SCHEDULED_TASKS.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("scheduled task failed")


async def shutdown_scheduled_tasks() -> None:
    if not SCHEDULED_TASKS:
        return
    tasks = list(SCHEDULED_TASKS)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    SCHEDULED_TASKS.clear()
