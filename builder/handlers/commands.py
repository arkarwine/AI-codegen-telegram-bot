"""Kurigram command handlers for Telegram-only management."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from builder.services.bot_service import BuilderService


MAX_SCHEMA_UPLOAD_BYTES = 512_000


HELP = """
Commands
/createbot
/editbot
/deletebot bot_id
/mybots
/status bot_id
/viewschema bot_id
/enable bot_id
/disable bot_id
/analytics bot_id
/exportschema bot_id
/importschema
/runtime
/cancel
""".strip()


def register_handlers(app: Any, service: BuilderService) -> None:
    from pyrogram import filters

    create_sessions: dict[int, dict[str, str]] = {}
    edit_sessions: dict[int, dict[str, str]] = {}
    import_sessions: dict[int, dict[str, str]] = {}

    @app.on_message(filters.command("start"))
    async def start(_: Any, message: Any) -> None:
        await service.user(message.from_user.id, message.from_user.username)
        await message.reply_text("AI Bot Builder is ready.\n\n" + HELP)

    @app.on_message(filters.command("createbot"))
    async def createbot(_: Any, message: Any) -> None:
        await service.user(message.from_user.id, message.from_user.username)
        create_sessions[message.from_user.id] = {"step": "name"}
        await message.reply_text("Bot name?")

    @app.on_message(filters.command("cancel"))
    async def cancel(_: Any, message: Any) -> None:
        cancelled = any(
            session.pop(message.from_user.id, None) is not None
            for session in (create_sessions, edit_sessions, import_sessions)
        )
        if not cancelled:
            await message.reply_text("Nothing to cancel.")
        else:
            await message.reply_text("Cancelled.")

    @app.on_message(filters.command("editbot"))
    async def editbot(_: Any, message: Any) -> None:
        await service.user(message.from_user.id, message.from_user.username)
        edit_sessions[message.from_user.id] = {"step": "bot_id"}
        await message.reply_text("Bot id to edit?")

    @app.on_message(filters.command("deletebot"))
    async def deletebot(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            deleted = await service.database.delete_bot(int(_payload(message)), user.id)
            await message.reply_text("Deleted." if deleted else "Bot not found.")
        except Exception as exc:
            await message.reply_text(f"Delete failed: {exc}")

    @app.on_message(filters.command("mybots"))
    async def mybots(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        bots = await service.database.list_user_bots(user.id)
        lines = [
            f"#{bot.id} {bot.name} @{bot.username or '-'} enabled={bot.enabled}"
            for bot in bots
        ]
        await message.reply_text("\n".join(lines) or "No bots yet.")

    @app.on_message(filters.command("status"))
    async def status(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            bot = await service.get_user_bot(user.id, int(_payload(message)))
            runtime = await service.runtime_snapshot()
            running = bot.id in set(runtime.get("running_bot_ids", []))
            failed = bot.id in {item.get("id") for item in runtime.get("failed_bots", [])}
            lines = [
                f"Bot #{bot.id}: {bot.name}",
                f"Username: @{bot.username or '-'}",
                f"Enabled: {bot.enabled}",
                f"Running: {running}",
                f"Failed: {failed}",
                f"Updated: {bot.updated_at}",
                f"Last started: {bot.last_started_at or '-'}",
                f"Last failed: {bot.last_failed_at or '-'}",
                f"Last error: {bot.last_error or '-'}",
            ]
            await message.reply_text("\n".join(lines))
        except Exception as exc:
            await message.reply_text(f"Status failed: {exc}")

    @app.on_message(filters.command("viewschema"))
    async def viewschema(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            bot = await service.get_user_bot(user.id, int(_payload(message)))
            await message.reply_text(_chunk(bot.schema_json))
        except Exception as exc:
            await message.reply_text(f"View failed: {exc}")

    @app.on_message(filters.command("enable"))
    async def enable(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            await service.set_bot_enabled(user.id, int(_payload(message)), True)
            await message.reply_text("Enabled. Runtime Engine will hot-reload it.")
        except Exception as exc:
            await message.reply_text(f"Enable failed: {exc}")

    @app.on_message(filters.command("disable"))
    async def disable(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            await service.set_bot_enabled(user.id, int(_payload(message)), False)
            await message.reply_text("Disabled. Runtime Engine will stop it.")
        except Exception as exc:
            await message.reply_text(f"Disable failed: {exc}")

    @app.on_message(filters.command("analytics"))
    async def analytics(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            counts = await service.analytics_counts(user.id, int(_payload(message)))
            await message.reply_text(json.dumps(counts, indent=2))
        except Exception as exc:
            await message.reply_text(f"Analytics failed: {exc}")

    @app.on_message(filters.command("exportschema"))
    async def exportschema(_: Any, message: Any) -> None:
        user = await service.user(message.from_user.id, message.from_user.username)
        try:
            bot = await service.get_user_bot(user.id, int(_payload(message)))
            document = BytesIO(bot.schema_json.encode("utf-8"))
            document.name = f"bot-{bot.id}-schema.json"
            await message.reply_document(document)
        except Exception as exc:
            await message.reply_text(f"Export failed: {exc}")

    @app.on_message(filters.command("importschema"))
    async def importschema(_: Any, message: Any) -> None:
        await service.user(message.from_user.id, message.from_user.username)
        import_sessions[message.from_user.id] = {"step": "name"}
        await message.reply_text("Imported bot name?")

    @app.on_message(filters.command("runtime"))
    async def runtime(_: Any, message: Any) -> None:
        if not service.is_platform_admin(message.from_user.id):
            await message.reply_text("This command is for the platform admin.")
            return
        try:
            snapshot = await service.runtime_snapshot()
            running = snapshot.get("running_bot_ids", [])
            failed = snapshot.get("failed_bots", [])
            lines = [
                "Runtime Engine",
                f"Database: {snapshot.get('database_path', '-')}",
                f"Uptime: {int(float(snapshot.get('uptime_seconds', 0)))}s",
                f"Plugins: {snapshot.get('plugin_count', 0)}",
                f"Running bots: {len(running)} {running}",
                f"Failed bots: {len(failed)}",
                f"Heartbeat: {snapshot.get('heartbeat_at', '-')}",
            ]
            await message.reply_text("\n".join(lines))
        except Exception as exc:
            await message.reply_text(f"Runtime status failed: {exc}")

    @app.on_message(filters.text | filters.document)
    async def continue_createbot(_: Any, message: Any) -> None:
        if message.text and message.text.startswith("/"):
            return
        user_id = message.from_user.id
        if user_id in edit_sessions:
            await _continue_editbot(message, service, edit_sessions)
            return
        if user_id in import_sessions:
            await _continue_importschema(message, service, import_sessions)
            return

        state = create_sessions.get(user_id)
        if state is None:
            return

        text = str(message.text or "").strip()
        if not text:
            await message.reply_text("Please send a non-empty value, or /cancel.")
            return

        step = state["step"]
        if step == "name":
            state["name"] = text
            state["step"] = "token"
            await message.reply_text("Bot token from BotFather?")
            return
        if step == "token":
            state["token"] = text
            state["step"] = "prompt"
            await message.reply_text("Describe what this bot should do.")
            return

        user = await service.user(message.from_user.id, message.from_user.username)
        create_sessions.pop(user_id, None)
        await message.reply_text("Creating schema and validating the bot token...")
        try:
            bot = await service.create_bot_from_prompt(
                user,
                state["name"],
                state["token"],
                text,
            )
            await message.reply_text(
                f"Created bot #{bot.id} @{bot.username or '-'}.\nUse /enable {bot.id} to deploy it."
            )
        except Exception as exc:
            await message.reply_text(f"Create failed: {exc}")


def _payload(message: Any) -> str:
    parts = str(message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        raise ValueError("Missing command arguments.")
    return parts[1].strip()


def _chunk(text: str, limit: int = 3900) -> str:
    return text if len(text) <= limit else text[:limit] + "\n..."


async def _continue_editbot(
    message: Any,
    service: BuilderService,
    sessions: dict[int, dict[str, str]],
) -> None:
    state = sessions[message.from_user.id]
    text = str(message.text or "").strip()
    if not text:
        await message.reply_text("Please send a value, or /cancel.")
        return
    if state["step"] == "bot_id":
        try:
            int(text)
        except ValueError:
            await message.reply_text("Bot id must be a number.")
            return
        state["bot_id"] = text
        state["step"] = "instruction"
        await message.reply_text("What should change?")
        return

    user = await service.user(message.from_user.id, message.from_user.username)
    sessions.pop(message.from_user.id, None)
    await message.reply_text("Updating schema...")
    try:
        await service.edit_bot(user.id, int(state["bot_id"]), text)
        await message.reply_text("Schema updated and queued for hot reload.")
    except Exception as exc:
        await message.reply_text(f"Edit failed: {exc}")


async def _continue_importschema(
    message: Any,
    service: BuilderService,
    sessions: dict[int, dict[str, str]],
) -> None:
    state = sessions[message.from_user.id]
    text = str(message.text or "").strip()
    if state["step"] == "name":
        if not text:
            await message.reply_text("Please send a bot name, or /cancel.")
            return
        state["name"] = text
        state["step"] = "token"
        await message.reply_text("Bot token from BotFather?")
        return
    if state["step"] == "token":
        if not text:
            await message.reply_text("Please send a bot token, or /cancel.")
            return
        state["token"] = text
        state["step"] = "schema"
        await message.reply_text("Paste the JSON schema or upload a .json file.")
        return

    user = await service.user(message.from_user.id, message.from_user.username)
    sessions.pop(message.from_user.id, None)
    await message.reply_text("Validating token and importing schema...")
    try:
        raw_json = await _schema_payload(message)
        bot = await service.import_schema(user, state["name"], state["token"], raw_json)
        await message.reply_text(f"Imported bot #{bot.id} @{bot.username or '-'}.")
    except Exception as exc:
        await message.reply_text(f"Import failed: {exc}")


async def _schema_payload(message: Any) -> str:
    if getattr(message, "document", None) is None:
        text = str(message.text or "").strip()
        if not text:
            raise ValueError("Paste JSON or upload a .json file.")
        return text

    document = message.document
    file_name = str(getattr(document, "file_name", "") or "")
    file_size = int(getattr(document, "file_size", 0) or 0)
    if file_name and not file_name.lower().endswith(".json"):
        raise ValueError("Schema upload must be a .json file.")
    if file_size > MAX_SCHEMA_UPLOAD_BYTES:
        raise ValueError("Schema file is too large.")

    downloaded = await message.download(in_memory=True)
    try:
        downloaded.seek(0)
        content = downloaded.read()
    finally:
        downloaded.close()

    if isinstance(content, str):
        text = content
    else:
        if len(content) > MAX_SCHEMA_UPLOAD_BYTES:
            raise ValueError("Schema file is too large.")
        text = content.decode("utf-8")
    if not text.strip():
        raise ValueError("Schema file is empty.")
    return text
