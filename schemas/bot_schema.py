"""Bot schema contract and validator.

Schemas are declarative only. The runtime rejects arbitrary actions and only
dispatches steps whose ``type`` maps to an enabled, predefined plugin.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Final


BUILTIN_STEP_TYPES: Final[set[str]] = {
    "send_message",
    "message",
    "buttons",
    "edit_message",
    "delete_message",
    "wait_for_input",
    "condition",
    "set_variable",
    "get_variable",
    "database_query",
    "data_transform",
    "http_request",
    "ai_chat",
    "scheduler",
    "broadcast",
    "admin_only",
    "analytics",
}

BOT_SCHEMA_JSON_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["metadata", "flows"],
    "properties": {
        "metadata": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
        },
        "permissions": {"type": "object"},
        "database": {"type": "object"},
        "variables": {"type": "object"},
        "flows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "steps"],
                "properties": {
                    "id": {"type": "string"},
                    "trigger": {},
                    "triggers": {"type": "array", "items": {}},
                    "description": {"type": "string"},
                    "permissions": {"type": "object"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string", "enum": sorted(BUILTIN_STEP_TYPES)},
                                "text": {"type": "string"},
                                "buttons": {"type": "array", "items": {}},
                                "variable": {"type": "string"},
                                "name": {"type": "string"},
                                "collection": {"type": "string"},
                                "action": {"type": "string"},
                                "key": {"type": "string"},
                                "value": {},
                                "item": {},
                                "amount": {"type": "number"},
                                "limit": {"type": "number"},
                                "reply": {"type": "boolean"},
                                "source_variable": {"type": "string"},
                                "index_variable": {"type": "string"},
                                "index": {},
                                "source": {},
                                "pattern": {"type": "string"},
                                "group": {},
                                "needle": {},
                                "default": {},
                                "template": {"type": "string"},
                                "choices": {"type": "array", "items": {}},
                                "lines": {"type": "array", "items": {}},
                                "empty": {"type": "string"},
                                "event_type": {"type": "string"},
                                "trigger": {"type": "string"},
                                "equals": {},
                                "operator": {"type": "string"},
                                "then": {"type": "string"},
                                "else": {"type": "string"},
                                "url": {"type": "string"},
                                "timeout": {"type": "number"},
                                "prompt": {"type": "string"},
                                "delay_seconds": {"type": "number"},
                                "scope": {"type": "string"},
                                "color": {"type": "string"},
                                "colour": {"type": "string"},
                                "style": {"type": "string"},
                                "telegram_ids": {"type": "array", "items": {"type": "number"}},
                                "denied_text": {"type": "string"},
                                "include_self": {"type": "boolean"},
                                "next": {"type": "string"},
                                "next_flow": {"type": "string"},
                                "next_step": {"type": "string"},
                                "on_success": {"type": "string"},
                                "on_failure": {"type": "string"},
                                "when": {},
                                "end": {"type": "boolean"},
                                "stop": {"type": "boolean"},
                                "save_as": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}


class SchemaValidationError(ValueError):
    """Raised when a bot schema is not deployable."""


def normalize_bot_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a deployable schema with safe aliases and obvious step types filled in.

    This is for AI/import ergonomics only. The runtime still executes only steps
    that pass ``validate_bot_schema`` and resolve to registered plugin actions.
    """

    normalized = deepcopy(schema)
    flows = normalized.get("flows")
    if not isinstance(flows, list):
        return normalized
    flow_ids = {
        flow.get("id")
        for flow in flows
        if isinstance(flow, dict) and isinstance(flow.get("id"), str)
    }
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        _normalize_flow_triggers(flow)
        if "trigger" not in flow and "triggers" not in flow and flow.get("id") == "start":
            flow["trigger"] = "/start"
        steps = flow.get("steps")
        if not isinstance(steps, list):
            continue
        step_ids = {
            step.get("id")
            for step in steps
            if isinstance(step, dict) and isinstance(step.get("id"), str)
        }
        for step in steps:
            if not isinstance(step, dict):
                continue
            _normalize_step_fields(step)
            if step.get("type") is not None:
                _normalize_transition_targets(step, flow_ids, step_ids)
                continue
            if "buttons" in step:
                step["type"] = "buttons"
            elif "text" in step:
                step["type"] = "message"
            elif "variable" in step:
                step["type"] = "wait_for_input"
            elif "event_type" in step:
                step["type"] = "analytics"
            _normalize_transition_targets(step, flow_ids, step_ids)
    return normalized


def _normalize_flow_triggers(flow: dict[str, Any]) -> None:
    trigger = flow.get("trigger")
    if isinstance(trigger, dict):
        _normalize_trigger(trigger)

    triggers = flow.get("triggers")
    if not isinstance(triggers, list):
        return
    for item in triggers:
        if isinstance(item, dict):
            _normalize_trigger(item)


def _normalize_trigger(trigger: dict[str, Any]) -> None:
    trigger_type = str(trigger.get("type", "text"))
    value = trigger.get("value")
    if (
        trigger_type in {"button", "callback"}
        and "match" not in trigger
        and isinstance(value, str)
        and _looks_like_prefix_trigger(value)
    ):
        trigger["match"] = "prefix"


def _looks_like_prefix_trigger(value: str) -> bool:
    return value.endswith(("_", ":", ".", "/", "-"))


def _normalize_step_fields(step: dict[str, Any]) -> None:
    step_type = step.get("type")
    if step_type in {"message", "send_message"} and isinstance(step.get("buttons"), list):
        step["type"] = "buttons"
        step_type = "buttons"
    if step_type == "set_variable":
        if not isinstance(step.get("name"), str) and isinstance(step.get("save_as"), str):
            step["name"] = step.pop("save_as")
        if "value" not in step and isinstance(step.get("name"), str):
            step["value"] = True
    if step_type == "database_query":
        action = str(step.get("action", "set" if "value" in step else "get"))
        if action in {"set", "upsert", "save"} and not isinstance(step.get("key"), str):
            if isinstance(step.get("save_as"), str):
                step["key"] = step["save_as"]
            elif isinstance(step.get("name"), str):
                step["key"] = step["name"]
            elif isinstance(step.get("variable"), str):
                step["key"] = step["variable"]
    if step_type == "data_transform":
        action = str(step.get("action", "")).lower()
        if (
            action == "replace_at"
            and "source_variable" in step
            and "source" in step
            and "value" not in step
            and "item" not in step
        ):
            step["value"] = step.pop("source")


def validate_bot_schema(schema: dict[str, Any], allowed_step_types: set[str] | None = None) -> None:
    """Validate the deployable subset enforced by the runtime."""

    step_types = allowed_step_types or BUILTIN_STEP_TYPES
    if not isinstance(schema, dict):
        raise SchemaValidationError("schema must be a JSON object")
    metadata = schema.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise SchemaValidationError("metadata.name is required")
    flows = schema.get("flows")
    if not isinstance(flows, list) or not flows:
        raise SchemaValidationError("flows must be a non-empty array")

    flow_ids: set[str] = set()
    for flow in flows:
        if not isinstance(flow, dict):
            raise SchemaValidationError("each flow must be an object")
        flow_id = flow.get("id")
        if not isinstance(flow_id, str) or not flow_id:
            raise SchemaValidationError("flow.id is required")
        if flow_id in flow_ids:
            raise SchemaValidationError(f"duplicate flow id: {flow_id}")
        flow_ids.add(flow_id)
        if "trigger" in flow:
            _validate_trigger(flow_id, flow["trigger"])
        if "triggers" in flow:
            triggers = flow["triggers"]
            if not isinstance(triggers, list) or not triggers:
                raise SchemaValidationError(f"flow {flow_id} triggers must be a non-empty array")
            for trigger in triggers:
                _validate_trigger(flow_id, trigger)
        steps = flow.get("steps")
        if not isinstance(steps, list):
            raise SchemaValidationError(f"flow {flow_id} steps must be an array")
        for index, step in enumerate(steps):
            _validate_step(flow_id, index, step, step_types)

    for flow in flows:
        step_ids = {
            item.get("id")
            for item in flow["steps"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for index, step in enumerate(flow["steps"]):
            _normalize_transition_targets(step, flow_ids, step_ids)
            for key in ("next", "next_flow", "on_success", "on_failure", "then", "else"):
                target = step.get(key)
                if isinstance(target, str) and target and target not in {"end", "stop"}:
                    if target not in flow_ids and target not in step_ids:
                        raise SchemaValidationError(
                            f"{flow['id']}[{index}] references unknown {key}: {target}"
                        )
            next_step = step.get("next_step")
            if isinstance(next_step, str) and next_step not in flow_ids and next_step not in step_ids:
                raise SchemaValidationError(
                    f"{flow['id']}[{index}] references unknown next_step: {next_step}"
                )
    _validate_button_routes(flows)


def _validate_trigger(flow_id: str, trigger: Any) -> None:
    if isinstance(trigger, str):
        if not trigger:
            raise SchemaValidationError(f"flow {flow_id} trigger cannot be empty")
        return
    if not isinstance(trigger, dict):
        raise SchemaValidationError(f"flow {flow_id} trigger must be a string or object")
    trigger_type = trigger.get("type", "text")
    if trigger_type not in {"command", "text", "button", "callback", "regex", "any"}:
        raise SchemaValidationError(f"flow {flow_id} has unsupported trigger type: {trigger_type}")
    if trigger_type != "any" and not isinstance(trigger.get("value"), str):
        raise SchemaValidationError(f"flow {flow_id} trigger.value is required")
    match_type = str(trigger.get("match", "exact"))
    if match_type not in {"exact", "case_insensitive", "contains", "prefix", "regex"}:
        raise SchemaValidationError(f"flow {flow_id} trigger.match is unsupported: {match_type}")
    if trigger_type == "regex" or match_type == "regex":
        _validate_regex(flow_id, "trigger.value", trigger.get("value", ""))


def _validate_step(flow_id: str, index: int, step: Any, allowed_step_types: set[str]) -> None:
    if not isinstance(step, dict):
        raise SchemaValidationError(f"{flow_id}[{index}] step must be an object")
    step_type = step.get("type")
    if step_type == "message":
        step_type = "send_message"
    if step_type not in allowed_step_types:
        raise SchemaValidationError(f"{flow_id}[{index}] has unsupported step type: {step_type}")
    if step_type in {"send_message", "message"} and not isinstance(step.get("text"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] message text is required")
    _validate_templates(flow_id, index, step)
    if "when" in step:
        _validate_condition_object(flow_id, index, step["when"], "when")
    if step_type == "buttons":
        _validate_buttons(flow_id, index, step.get("buttons"))
    if step_type == "wait_for_input" and "variable" in step and not isinstance(step["variable"], str):
        raise SchemaValidationError(f"{flow_id}[{index}] wait_for_input variable must be a string")
    if step_type == "condition" and not isinstance(step.get("variable", step.get("name")), str):
        if not any(key in step for key in ("all", "any", "not")):
            raise SchemaValidationError(f"{flow_id}[{index}] condition requires variable or name")
    if step_type == "condition" and "scope" in step and step["scope"] not in {"session", "user", "global"}:
        raise SchemaValidationError(f"{flow_id}[{index}] condition scope is invalid")
    if step_type == "condition":
        _validate_condition_step(flow_id, index, step)
    if step_type == "set_variable":
        _validate_set_variable_step(flow_id, index, step)
    if step_type == "get_variable":
        if not isinstance(step.get("name"), str):
            raise SchemaValidationError(f"{flow_id}[{index}] get_variable requires name")
        if "scope" in step and step["scope"] not in {"session", "user", "global"}:
            raise SchemaValidationError(f"{flow_id}[{index}] get_variable scope is invalid")
    if step_type == "analytics" and not isinstance(step.get("event_type"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] analytics requires event_type")
    if step_type == "scheduler":
        if not isinstance(step.get("delay_seconds"), int | float) or not isinstance(step.get("text"), str):
            raise SchemaValidationError(
                f"{flow_id}[{index}] scheduler requires numeric delay_seconds and text"
            )
    if step_type == "http_request" and not isinstance(step.get("url"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] http_request requires url")
    if step_type == "ai_chat":
        _validate_ai_chat_step(flow_id, index, step)
    if step_type == "broadcast" and not isinstance(step.get("text"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] broadcast requires text")
    if step_type == "edit_message" and not isinstance(step.get("text"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] edit_message requires text")
    if step_type == "database_query":
        _validate_database_step(flow_id, index, step)
    if step_type == "data_transform":
        _validate_data_transform_step(flow_id, index, step)


def _validate_condition_step(flow_id: str, index: int, step: dict[str, Any]) -> None:
    _validate_condition_object(flow_id, index, step, "condition")


def _validate_condition_object(flow_id: str, index: int, condition: Any, label: str) -> None:
    if not isinstance(condition, dict):
        raise SchemaValidationError(f"{flow_id}[{index}] {label} must be an object")
    if "all" in condition or "any" in condition:
        key = "all" if "all" in condition else "any"
        items = condition[key]
        if not isinstance(items, list) or not items:
            raise SchemaValidationError(f"{flow_id}[{index}] {label}.{key} must be a non-empty array")
        for item_index, item in enumerate(items):
            _validate_condition_object(flow_id, index, item, f"{label}.{key}[{item_index}]")
        return
    if "not" in condition:
        _validate_condition_object(flow_id, index, condition["not"], f"{label}.not")
        return
    if not isinstance(condition.get("variable", condition.get("name")), str):
        raise SchemaValidationError(f"{flow_id}[{index}] {label} requires variable or name")

    operator = str(condition.get("operator", "equals"))
    if operator not in {
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "exists",
        "missing",
        "greater_than",
        "less_than",
        "in",
        "regex",
    }:
        raise SchemaValidationError(f"{flow_id}[{index}] {label} operator is unsupported: {operator}")
    if operator not in {"exists", "missing"} and "value" not in condition and "equals" not in condition:
        raise SchemaValidationError(f"{flow_id}[{index}] {label} operator {operator} requires value")
    if operator == "regex":
        _validate_regex(flow_id, f"{label}.value", condition.get("value", condition.get("equals", "")))


def _normalize_transition_targets(
    step: dict[str, Any],
    flow_ids: set[Any],
    step_ids: set[Any],
) -> None:
    next_step = step.get("next_step")
    if isinstance(next_step, str) and next_step in flow_ids and next_step not in step_ids:
        step.setdefault("next_flow", next_step)
        step.pop("next_step", None)

    next_flow = step.get("next_flow")
    if isinstance(next_flow, str) and next_flow in step_ids and next_flow not in flow_ids:
        step.setdefault("next_step", next_flow)
        step.pop("next_flow", None)


def _validate_set_variable_step(flow_id: str, index: int, step: dict[str, Any]) -> None:
    if not isinstance(step.get("name"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] set_variable requires name")
    if "value" not in step:
        raise SchemaValidationError(f"{flow_id}[{index}] set_variable requires value")
    if "scope" in step and step["scope"] not in {"session", "user", "global"}:
        raise SchemaValidationError(f"{flow_id}[{index}] set_variable scope is invalid")


def _validate_database_step(flow_id: str, index: int, step: dict[str, Any]) -> None:
    action = str(step.get("action", "set" if "value" in step else "get"))
    supported = {"set", "upsert", "save", "get", "read", "delete", "list", "count", "exists", "increment", "append"}
    if action not in supported:
        raise SchemaValidationError(f"{flow_id}[{index}] unsupported database action: {action}")
    if "scope" in step and step["scope"] not in {"global", "user"}:
        raise SchemaValidationError(f"{flow_id}[{index}] database scope must be global or user")
    if action not in {"list", "count"} and not isinstance(step.get("key"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] database action {action} requires key")
    if action in {"set", "upsert", "save"} and "value" not in step:
        raise SchemaValidationError(f"{flow_id}[{index}] database action {action} requires value")
    if action == "append" and "item" not in step and "value" not in step:
        raise SchemaValidationError(f"{flow_id}[{index}] database action append requires item or value")


def _validate_data_transform_step(flow_id: str, index: int, step: dict[str, Any]) -> None:
    action = str(step.get("action", "")).lower()
    supported = {
        "copy",
        "get",
        "template",
        "regex_extract",
        "replace_at",
        "increment",
        "decrement",
        "append",
        "remove",
        "length",
        "random_choice",
        "line_match",
        "contains",
    }
    if action not in supported:
        raise SchemaValidationError(f"{flow_id}[{index}] unsupported data_transform action: {action}")
    output_name = step.get("save_as", step.get("name"))
    if not isinstance(output_name, str) or not output_name.strip():
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform requires save_as or name")
    source_actions = {
        "copy",
        "get",
        "regex_extract",
        "replace_at",
        "increment",
        "decrement",
        "append",
        "remove",
        "length",
        "line_match",
        "contains",
    }
    if action in source_actions and not _has_transform_source(step):
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform {action} requires source")
    if action == "template" and not isinstance(step.get("template"), str):
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform template requires template")
    if action == "regex_extract":
        if not isinstance(step.get("pattern"), str):
            raise SchemaValidationError(f"{flow_id}[{index}] data_transform regex_extract requires pattern")
        _validate_regex(flow_id, f"{index}.data_transform.pattern", step["pattern"])
    if action == "replace_at":
        if "index" not in step and "index_variable" not in step:
            raise SchemaValidationError(f"{flow_id}[{index}] data_transform replace_at requires index")
        if "item" not in step and "value" not in step:
            raise SchemaValidationError(f"{flow_id}[{index}] data_transform replace_at requires item or value")
    if action == "append" and "item" not in step and "value" not in step:
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform append requires item or value")
    if action == "random_choice" and not isinstance(step.get("choices"), list) and not _has_transform_source(step):
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform random_choice requires choices or source")
    if action == "line_match" and not isinstance(step.get("lines"), list):
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform line_match requires lines")
    if action == "contains" and "needle" not in step and "value" not in step:
        raise SchemaValidationError(f"{flow_id}[{index}] data_transform contains requires needle or value")


def _has_transform_source(step: dict[str, Any]) -> bool:
    return any(key in step for key in ("source_variable", "variable", "source", "value"))


def _validate_buttons(flow_id: str, index: int, buttons: Any) -> None:
    if not isinstance(buttons, list) or not buttons:
        raise SchemaValidationError(f"{flow_id}[{index}] buttons must be a non-empty array")
    rows = buttons if isinstance(buttons[0], list) else [buttons]
    valid_count = 0
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            raise SchemaValidationError(f"{flow_id}[{index}] button row {row_index} must be non-empty")
        for button_index, button in enumerate(row):
            label: Any
            value: Any
            if isinstance(button, str):
                label = button
                value = button
            elif isinstance(button, dict):
                label = button.get("text", button.get("label"))
                value = button.get("value", button.get("callback_data", label))
            else:
                raise SchemaValidationError(
                    f"{flow_id}[{index}] button {row_index}.{button_index} must be text or object"
                )
            if not isinstance(label, str) or not label.strip():
                raise SchemaValidationError(f"{flow_id}[{index}] button {row_index}.{button_index} requires text")
            if not isinstance(value, str) or not value.strip():
                raise SchemaValidationError(f"{flow_id}[{index}] button {row_index}.{button_index} requires value")
            encoded_length = len(value.encode("utf-8"))
            if encoded_length > 64:
                raise SchemaValidationError(
                    f"{flow_id}[{index}] button {row_index}.{button_index} value exceeds Telegram 64-byte callback limit"
                )
            valid_count += 1
    if valid_count == 0:
        raise SchemaValidationError(f"{flow_id}[{index}] buttons must contain at least one button")


def _validate_ai_chat_step(flow_id: str, index: int, step: dict[str, Any]) -> None:
    prompt = step.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SchemaValidationError(f"{flow_id}[{index}] ai_chat requires prompt")
    save_as = step.get("save_as")
    if not isinstance(save_as, str) or not save_as:
        return

    state_like_names = {
        "board",
        "board_state",
        "state",
        "game_state",
        "score",
        "scores",
        "counter",
        "count",
        "total",
        "winner",
        "result",
        "status",
    }
    prompt_text = prompt.lower()
    deterministic_terms = {
        "return only",
        "final string",
        "calculate",
        "validate",
        "update",
        "winner",
        "draw",
        "score",
        "counter",
        "board",
        "json",
        "structured",
        "state",
    }
    if save_as.lower() in state_like_names or any(term in prompt_text for term in deterministic_terms):
        raise SchemaValidationError(
            f"{flow_id}[{index}] ai_chat cannot be used for deterministic state transformation; use data_transform, condition, or database_query"
        )


def _validate_templates(flow_id: str, index: int, value: Any) -> None:
    if isinstance(value, str):
        _validate_template_string(flow_id, index, value)
        return
    if isinstance(value, list):
        for item in value:
            _validate_templates(flow_id, index, item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_templates(flow_id, index, item)


def _validate_template_string(flow_id: str, index: int, text: str) -> None:
    for match in re.finditer(r"\{\{\s*([^}]+?)\s*\}\}", text):
        expression = match.group(1).strip()
        if "|" not in expression:
            continue
        if re.fullmatch(r"[^|]+?\s*\|\s*default\(.*\)", expression) is None:
            raise SchemaValidationError(
                f"{flow_id}[{index}] template uses unsupported filter: {expression}"
            )


def _validate_regex(flow_id: str, label: str, pattern: Any) -> None:
    if not isinstance(pattern, str):
        raise SchemaValidationError(f"flow {flow_id} {label} must be a regex string")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise SchemaValidationError(f"flow {flow_id} {label} is invalid regex: {exc}") from exc


def _validate_button_routes(flows: list[Any]) -> None:
    exact_routes: set[str] = set()
    prefix_routes: list[str] = []
    contains_routes: list[str] = []
    regex_routes: list[str] = []

    for flow in flows:
        if not isinstance(flow, dict):
            continue
        triggers = []
        if "trigger" in flow:
            triggers.append(flow["trigger"])
        if isinstance(flow.get("triggers"), list):
            triggers.extend(flow["triggers"])
        for trigger in triggers:
            route = _button_route_from_trigger(trigger)
            if route is None:
                continue
            match_type, value = route
            if match_type in {"exact", "case_insensitive"}:
                exact_routes.add(value if match_type == "exact" else value.lower())
            elif match_type == "prefix":
                prefix_routes.append(value)
            elif match_type == "contains":
                contains_routes.append(value)
            elif match_type == "regex":
                regex_routes.append(value)

    for flow in flows:
        if not isinstance(flow, dict):
            continue
        for index, step in enumerate(flow.get("steps", [])):
            if not isinstance(step, dict) or step.get("type") != "buttons":
                continue
            for value in _button_values(step.get("buttons")):
                if "{{" in value or "}}" in value:
                    continue
                if (
                    value in exact_routes
                    or value.lower() in exact_routes
                    or any(value.startswith(prefix) for prefix in prefix_routes)
                    or any(fragment in value for fragment in contains_routes)
                    or any(re.fullmatch(pattern, value) for pattern in regex_routes)
                ):
                    continue
                raise SchemaValidationError(
                    f"{flow.get('id', '<unknown>')}[{index}] button value has no callback/button route: {value}"
                )


def _button_route_from_trigger(trigger: Any) -> tuple[str, str] | None:
    if not isinstance(trigger, dict):
        return None
    if trigger.get("type", "text") not in {"callback", "button"}:
        return None
    value = trigger.get("value")
    if not isinstance(value, str) or not value:
        return None
    return str(trigger.get("match", "exact")), value


def _button_values(buttons: Any) -> list[str]:
    if not isinstance(buttons, list) or not buttons:
        return []
    rows = buttons if isinstance(buttons[0], list) else [buttons]
    values: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            if isinstance(button, str):
                values.append(button)
            elif isinstance(button, dict):
                value = button.get("value", button.get("callback_data", button.get("text", button.get("label"))))
                if isinstance(value, str):
                    values.append(value)
    return values
