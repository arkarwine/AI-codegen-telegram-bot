"""Built-in plugin actions.

No plugin evaluates user code. Each action accepts JSON config and calls a
bounded Python implementation owned by the platform.
"""

from __future__ import annotations

import asyncio
from typing import Any

from plugins.base import PluginContext


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
        from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        buttons = [str(item) for item in config.get("buttons", [])]
        rows = [[InlineKeyboardButton(text=label, callback_data=label)] for label in buttons]
        await context.message.reply_text(
            str(config.get("text", "Choose an option:")),
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
        return {"wait": True, "variable": config.get("variable", "last_input")}


class ConditionPlugin:
    name = "condition"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["variable", "equals"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        value = context.session_data.get(str(config["variable"]))
        return {"skip_next": value != config["equals"]}


class SetVariablePlugin:
    name = "set_variable"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["name", "value"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        return {"data": {str(config["name"]): config["value"]}}


class GetVariablePlugin:
    name = "get_variable"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["name"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        value = context.session_data.get(str(config["name"]), "")
        await context.message.reply_text(str(value))
        return {}


class DatabaseQueryPlugin:
    name = "database_query"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["key"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        namespace = context.session_data.setdefault("database", {})
        if "value" in config:
            namespace[str(config["key"])] = config["value"]
            return {"data": {"database": namespace}}
        await context.message.reply_text(str(namespace.get(str(config["key"]), "")))
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
            model=str(config.get("model", "gemini-3.1-flash-lite")),
            contents=_render(str(config["prompt"]), context.session_data),
        )
        await context.message.reply_text(response.text or "")
        return {}


class SchedulerPlugin:
    name = "scheduler"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["delay_seconds", "text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        async def later() -> None:
            await asyncio.sleep(float(config["delay_seconds"]))
            await context.message.reply_text(str(config["text"]))

        asyncio.create_task(later())
        return {}


class BroadcastPlugin:
    name = "broadcast"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        await context.message.reply_text(str(config["text"]))
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
        text = text.replace("{{" + key + "}}", str(value))
    return text
