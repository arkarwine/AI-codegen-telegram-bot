"""Workflow/state-machine dispatcher."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from database.sqlite import Database
from models.entities import BotRecord
from plugins.base import PluginContext
from plugins.registry import PluginRegistry
from runtime.sessions import SessionStore
from schemas.bot_schema import normalize_bot_schema, validate_bot_schema


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Normalized Telegram update details used by trigger matching and templates."""

    type: str
    text: str
    command: str | None
    user_id: int
    username: str | None


class WorkflowDispatcher:
    """Executes schema flows as state machines for one deployed bot."""

    def __init__(self, database: Database, registry: PluginRegistry) -> None:
        self.database = database
        self.registry = registry
        self.sessions = SessionStore(database)

    async def dispatch(self, bot: BotRecord, client: Any, message: Any) -> None:
        schema = normalize_bot_schema(json.loads(bot.schema_json))
        validate_bot_schema(schema, set(self.registry.plugins))
        event_message = getattr(message, "message", message)
        event = _runtime_event(message)
        user_id = event.user_id
        current_flow, current_step, data = await self.sessions.load(bot.id, user_id)
        _apply_schema_defaults(schema, data)

        waiting_variable = data.pop("_waiting_variable", None)
        if waiting_variable and event.text:
            data[str(waiting_variable)] = event.text

        flow = _find_flow(
            schema,
            event,
            current_flow,
            prefer_current=bool(waiting_variable and event.command is None),
        )
        if flow is None:
            logger.debug(
                "workflow_no_match %s",
                _log_json({"bot_id": bot.id, "user_id": user_id, "event_type": event.type}),
            )
            return

        start_index = current_step if current_flow == flow["id"] else 0
        logger.info(
            "workflow_flow %s",
            _log_json(
                {
                    "bot_id": bot.id,
                    "flow_id": flow["id"],
                    "user_id": user_id,
                    "event_type": event.type,
                    "start_index": start_index,
                }
            ),
        )
        await self.database.record_event(bot.id, "message")
        runtime_data = await self._runtime_data(bot.id, user_id, data, event)
        next_state = await self._run_steps(
            bot,
            client,
            event_message,
            user_id,
            schema,
            flow,
            start_index,
            data,
            runtime_data,
        )
        if next_state is None:
            await self.sessions.save(bot.id, user_id, None, 0, data)
        else:
            await self.sessions.save(bot.id, user_id, next_state[0], next_state[1], data)

    async def _runtime_data(
        self,
        bot_id: int,
        user_id: int,
        session_data: dict[str, Any],
        event: RuntimeEvent,
    ) -> dict[str, Any]:
        runtime_data = dict(session_data)
        runtime_data["session"] = session_data
        runtime_data["event"] = {
            "type": event.type,
            "text": event.text,
            "value": event.text,
            "callback_data": event.text if event.type == "callback" else "",
            "command": event.command or "",
        }
        runtime_data["telegram_user"] = {
            "id": event.user_id,
            "username": event.username or "",
        }
        runtime_data["user"] = await self.database.list_variables(bot_id, "user", user_id)
        runtime_data["global"] = await self.database.list_variables(bot_id, "global")
        return runtime_data

    async def _run_steps(
        self,
        bot: BotRecord,
        client: Any,
        message: Any,
        user_id: int,
        schema: dict[str, Any],
        flow: dict[str, Any],
        start_index: int,
        data: dict[str, Any],
        runtime_data: dict[str, Any],
    ) -> tuple[str, int] | None:
        active_flow = flow
        steps = active_flow["steps"]
        index = start_index
        while index < len(steps):
            raw_step = steps[index]
            if not _condition_matches(raw_step.get("when"), runtime_data):
                index += 1
                continue

            step = _render_config(raw_step, runtime_data)
            context = PluginContext(
                bot_id=bot.id,
                user_id=user_id,
                client=client,
                message=message,
                session_data=runtime_data,
                services={"database": self.database},
            )
            plugin = self.registry.get(str(step["type"]))
            step_log = {
                "bot_id": bot.id,
                "flow_id": active_flow["id"],
                "user_id": user_id,
                "step_index": index,
                "step_id": step.get("id", ""),
                "plugin": plugin.name,
            }
            logger.info("workflow_step_start %s", _log_json(step_log))
            try:
                result = await plugin.execute(step, context) or {}
                success = True
            except Exception:
                success = False
                logger.exception("workflow_step_error %s", _log_json(step_log))
                if target := step.get("on_failure"):
                    jump = _resolve_jump(schema, active_flow, str(target))
                    if jump is None:
                        return None
                    active_flow, steps, index = jump
                    continue
                raise
            logger.info(
                "workflow_step_done %s",
                _log_json({**step_log, "result_keys": sorted(result)}),
            )

            updates = result.get("data", {})
            if isinstance(updates, dict):
                data.update(updates)
                runtime_data.update(updates)
                runtime_data["session"] = data
            _merge_scoped_runtime_data(runtime_data, result.get("scoped_data"))

            if result.get("stop"):
                return None

            if variable := result.get("variable"):
                data["_waiting_variable"] = variable

            if result.get("wait"):
                return active_flow["id"], index + 1

            target = (
                result.get("goto")
                or step.get("next_flow")
                or step.get("next_step")
                or step.get("next")
                or (step.get("on_success") if success else None)
            )
            if step.get("end") or step.get("stop") or target in {"end", "stop"}:
                return None
            if isinstance(target, str) and target:
                jump = _resolve_jump(schema, active_flow, target)
                if jump is None:
                    return None
                active_flow, steps, index = jump
                continue

            if result.get("skip_next"):
                index += 2
            else:
                index += 1
        return None


def _runtime_event(message: Any) -> RuntimeEvent:
    raw_text = ""
    event_type = "text"
    if getattr(message, "data", None):
        raw_text = str(message.data)
        event_type = "callback"
    elif getattr(message, "text", None):
        raw_text = str(message.text)
        event_type = "text"
    command = raw_text.split(maxsplit=1)[0] if raw_text.startswith("/") else None
    if command:
        event_type = "command"
    from_user = getattr(message, "from_user", None)
    return RuntimeEvent(
        type=event_type,
        text=raw_text,
        command=command,
        user_id=int(getattr(from_user, "id", 0)),
        username=getattr(from_user, "username", None),
    )


def _find_flow(
    schema: dict[str, Any],
    event: RuntimeEvent,
    current_flow: str | None,
    prefer_current: bool = False,
) -> dict[str, Any] | None:
    if prefer_current and current_flow:
        current = next((flow for flow in schema["flows"] if flow["id"] == current_flow), None)
        if current is not None:
            return current
    for flow in schema["flows"]:
        for trigger in _flow_triggers(flow):
            if _trigger_matches(trigger, event):
                return flow
    if current_flow:
        return next((flow for flow in schema["flows"] if flow["id"] == current_flow), None)
    return None


def _flow_triggers(flow: dict[str, Any]) -> list[Any]:
    triggers: list[Any] = []
    if "trigger" in flow:
        triggers.append(flow["trigger"])
    triggers.extend(flow.get("triggers", []))
    return triggers


def _trigger_matches(trigger: Any, event: RuntimeEvent) -> bool:
    if isinstance(trigger, str):
        if trigger.startswith("/"):
            return event.command == trigger
        return event.text == trigger
    if not isinstance(trigger, dict):
        return False
    trigger_type = str(trigger.get("type", "text"))
    if trigger_type == "any":
        return True
    value = str(trigger.get("value", ""))
    match = str(trigger.get("match", "exact"))
    if trigger_type == "command":
        return event.command == value
    if trigger_type == "callback":
        return event.type == "callback" and _text_matches(event.text, value, match)
    if trigger_type == "button":
        return event.type in {"callback", "text"} and _text_matches(event.text, value, match)
    if trigger_type == "regex":
        return re.search(value, event.text) is not None
    return event.type in {"text", "command"} and _text_matches(event.text, value, match)


def _text_matches(text: str, value: str, match: str) -> bool:
    if match == "contains":
        return value.lower() in text.lower()
    if match == "prefix":
        return text.lower().startswith(value.lower())
    if match == "case_insensitive":
        return text.lower() == value.lower()
    if match == "regex":
        return re.search(value, text) is not None
    return text == value


def _apply_schema_defaults(schema: dict[str, Any], data: dict[str, Any]) -> None:
    variables = schema.get("variables", {})
    if isinstance(variables, dict):
        for key, value in variables.items():
            data.setdefault(str(key), value)


def _condition_matches(condition: Any, data: dict[str, Any]) -> bool:
    if condition in (None, {}, []):
        return True
    if isinstance(condition, list):
        return all(_condition_matches(item, data) for item in condition)
    if not isinstance(condition, dict):
        return bool(condition)
    if "all" in condition:
        return all(_condition_matches(item, data) for item in condition["all"])
    if "any" in condition:
        return any(_condition_matches(item, data) for item in condition["any"])
    if "not" in condition:
        return not _condition_matches(condition["not"], data)

    name = str(condition.get("variable", condition.get("name", "")))
    value = _lookup_data(data, name)
    expected = condition.get("equals", condition.get("value"))
    operator = str(condition.get("operator", "equals"))
    try:
        if operator == "equals":
            return value == expected
        if operator == "not_equals":
            return value != expected
        if operator == "contains":
            return str(expected).lower() in str(value).lower()
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


def _render_config(value: Any, data: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_text(value, data)
    if isinstance(value, list):
        return [_render_config(item, data) for item in value]
    if isinstance(value, dict):
        return {key: _render_config(item, data) for key, item in value.items()}
    return value


def _render_text(template: str, data: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _lookup_data(data, match.group(1).strip())
        return "" if value is None else str(value)

    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, template)


def _lookup_data(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _merge_scoped_runtime_data(runtime_data: dict[str, Any], scoped_data: Any) -> None:
    if not isinstance(scoped_data, dict):
        return
    for scope, values in scoped_data.items():
        if not isinstance(values, dict):
            continue
        existing = runtime_data.setdefault(str(scope), {})
        if isinstance(existing, dict):
            existing.update(values)


def _resolve_jump(
    schema: dict[str, Any],
    current_flow: dict[str, Any],
    target: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int] | None:
    for flow in schema["flows"]:
        if flow["id"] == target:
            return flow, flow["steps"], 0
    for index, step in enumerate(current_flow["steps"]):
        if step.get("id") == target:
            return current_flow, current_flow["steps"], index
    return None


def _log_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
