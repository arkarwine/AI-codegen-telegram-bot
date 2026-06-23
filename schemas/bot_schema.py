"""Bot schema contract and validator.

Schemas are declarative only. The runtime rejects arbitrary actions and only
dispatches steps whose ``type`` maps to an enabled, predefined plugin.
"""

from __future__ import annotations

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
        "variables": {"type": "object"},
        "flows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "trigger", "steps"],
                "properties": {
                    "id": {"type": "string"},
                    "trigger": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
    },
}


class SchemaValidationError(ValueError):
    """Raised when a bot schema is not deployable."""


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
        if not isinstance(flow.get("trigger"), str):
            raise SchemaValidationError(f"flow {flow_id} trigger must be a string")
        steps = flow.get("steps")
        if not isinstance(steps, list):
            raise SchemaValidationError(f"flow {flow_id} steps must be an array")
        for index, step in enumerate(steps):
            _validate_step(flow_id, index, step, step_types)


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
    if step_type == "buttons" and not isinstance(step.get("buttons"), list):
        raise SchemaValidationError(f"{flow_id}[{index}] buttons array is required")
