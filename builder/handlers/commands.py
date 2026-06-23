"""Kurigram command handlers for Telegram-only management."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from builder.services.bot_service import BuilderService


HELP = """
Commands:
/createbot <name>|<token>|<prompt>
/editbot <bot_id>|<instruction>
/deletebot <bot_id>
/mybots
/viewschema <bot_id>
/enable <bot_id>
/disable <bot_id>
/analytics <bot_id>
/exportschema <bot_id>
/importschema <name>|<token>|<json>
""".strip()


def register_handlers(app: Any, service: BuilderService) -> None:
    from pyrogram import filters

    @app.on_message(filters.command("start"))
    async def start(_: Any, message: Any) -> None:
        await service.user(message.from_user.id, message.from_user.username)
        await message.reply_text("AI Bot Builder is ready.\n\n" + HELP)

    @app.on_message(filters.command("createbot"))
    async def createbot(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            name, token, prompt = _payload(message).split("|", 2)
            bot = await service.create_bot_from_prompt(user, name.strip(), None, token.strip(), prompt.strip())
            await message.reply_text(f"Created bot #{bot.id}. Use /enable {bot.id} to deploy it.")
        except Exception as exc:
            await message.reply_text(f"Create failed: {exc}")

    @app.on_message(filters.command("editbot"))
    async def editbot(_: Any, message: Any) -> None:
        try:
            bot_id, instruction = _payload(message).split("|", 1)
            await service.edit_bot(int(bot_id), instruction.strip())
            await message.reply_text("Schema updated and queued for hot reload.")
        except Exception as exc:
            await message.reply_text(f"Edit failed: {exc}")

    @app.on_message(filters.command("deletebot"))
    async def deletebot(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        deleted = await service.database.delete_bot(int(_payload(message)), user.id)
        await message.reply_text("Deleted." if deleted else "Bot not found.")

    @app.on_message(filters.command("mybots"))
    async def mybots(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        bots = await service.database.list_user_bots(user.id)
        lines = [f"#{bot.id} {bot.name} enabled={bot.enabled}" for bot in bots]
        await message.reply_text("\n".join(lines) or "No bots yet.")

    @app.on_message(filters.command("viewschema"))
    async def viewschema(_: Any, message: Any) -> None:
        bot = await service.database.get_bot(int(_payload(message)))
        await message.reply_text(_chunk(bot.schema_json))

    @app.on_message(filters.command("enable"))
    async def enable(_: Any, message: Any) -> None:
        await service.database.set_bot_enabled(int(_payload(message)), True)
        await message.reply_text("Enabled. Runtime Engine will hot-reload it.")

    @app.on_message(filters.command("disable"))
    async def disable(_: Any, message: Any) -> None:
        await service.database.set_bot_enabled(int(_payload(message)), False)
        await message.reply_text("Disabled. Runtime Engine will stop it.")

    @app.on_message(filters.command("analytics"))
    async def analytics(_: Any, message: Any) -> None:
        counts = await service.database.analytics_counts(int(_payload(message)))
        await message.reply_text(json.dumps(counts, indent=2))

    @app.on_message(filters.command("exportschema"))
    async def exportschema(_: Any, message: Any) -> None:
        bot = await service.database.get_bot(int(_payload(message)))
        document = BytesIO(bot.schema_json.encode("utf-8"))
        document.name = f"bot-{bot.id}-schema.json"
        await message.reply_document(document)

    @app.on_message(filters.command("importschema"))
    async def importschema(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            name, token, raw_json = _payload(message).split("|", 2)
            bot = await service.import_schema(user, name.strip(), token.strip(), raw_json)
            await message.reply_text(f"Imported bot #{bot.id}.")
        except Exception as exc:
            await message.reply_text(f"Import failed: {exc}")


def _payload(message: Any) -> str:
    return str(message.text).split(maxsplit=1)[1].strip()


def _chunk(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[:limit] + "\n..."
