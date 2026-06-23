"""Gemini schema-only AI integration."""

from __future__ import annotations

import json
import os
import re
from json import JSONDecodeError
from typing import Any, Literal

from schemas.bot_schema import (
    BOT_SCHEMA_JSON_SCHEMA,
    SchemaValidationError,
    normalize_bot_schema,
    validate_bot_schema,
)


SCHEMA_SYSTEM_PROMPT = """
Return exactly one valid Telegram bot schema JSON object. No prose, markdown,
comments, code fences, Python, JavaScript, SQL, shell, eval, or unsupported
actions. User bots are declarative JSON only.

Design standard:
- Build a production-ready, professional, complete bot, not a demo or placeholder.
- Finish the requested workflow end-to-end: onboarding, menus, collection,
  validation, persistence, confirmations, admin paths, and fallbacks as relevant.
- Use Telegram-native UX as much as possible: commands, inline buttons with
  callback values, callback triggers, edit/delete messages, admin guards,
  broadcast, scheduler, analytics, database_query, variables, and conditions.
- Prefer buttons/callbacks over asking users to type finite choices.

Top-level keys:
- metadata: required object with name; optional description.
- permissions, database, variables: optional objects.
- flows: required non-empty array.

Flows:
- id: required lower_snake_case string.
- trigger or triggers: string or object. Always include a /start flow.
- steps: required array. Every step needs type.
- Valid trigger objects: {"type":"command|text|button|callback|regex|any",
  "value":"...", "match":"exact|case_insensitive|contains|prefix|regex"}.
- Button values must match a text/button/callback trigger in another flow.

Transitions:
- id names a step inside the current flow.
- next_flow jumps to a flow id. next_step jumps only to a local step id.
- next, on_success, on_failure, then, else may target an existing flow id,
  local step id, "end", or "stop". All references must exist.
- when supports conditions and skips the step if false.

Templates and data:
- Use {{name}} for session data, {{user.name}} for user variables,
  {{global.name}} for bot variables, and {{event.text}},
  {{event.command}}, {{event.type}}, {{telegram_user.id}},
  {{telegram_user.username}} for runtime data.
- Persist real business data with database_query. Do not fake persistence with
  only messages or session variables.

Conditions:
- Use variable/name plus operator/value, or all/any/not.
- Operators: equals, not_equals, contains, exists, missing, greater_than,
  less_than, in, regex.

Step contracts:
- message/send_message: requires text.
- buttons: requires non-empty buttons; optional text. Buttons may be strings,
  {"text":"Label","value":"callback_value"}, or rows of those objects.
- wait_for_input: use prompt and variable for each free-text answer.
- set_variable: requires name and value; scope is session, user, or global.
  Never use save_as on set_variable.
- get_variable: requires name; optional scope and save_as.
- condition: requires variable/name or all/any/not; optional operator, value,
  then, else.
- database_query: no SQL. Actions are set/upsert/save/get/read/delete/list/
  count/exists/increment/append. set/upsert/save require key and value.
  get/read/delete/exists/increment require key. append requires key and item
  or value. list/count need no key. Optional fields: collection, scope, amount,
  limit, save_as, reply. Scope is global or user.
- analytics: requires event_type.
- admin_only: optional telegram_ids and denied_text; put before sensitive steps.
- broadcast: requires text and should be admin_only guarded.
- scheduler: requires delay_seconds and text.
- ai_chat: requires prompt; keep it bounded to the bot's purpose.
- http_request: requires url; optional timeout and save_as.
- edit_message: requires text.
- delete_message: no required fields.

Production patterns:
- Leads: buttons for intent, wait_for_input for name/contact, database_query
  collection leads, analytics lead_created, confirmation, admin review.
- Booking: choose service/date/time with buttons where possible, collect contact,
  save booking record, confirm, schedule reminder if useful.
- FAQ: /start menu, topic buttons, back buttons, concise answers.
- Support: category buttons, collect issue, save ticket with status open,
  urgent condition branch, confirmation.
- Quiz/game: button-based choices or board positions, state variables, result
  branches, replay button. Never say the logic is "basic" or external.
- Admin broadcast: /admin or /broadcast, admin_only, broadcast, analytics.
""".strip()


class AiSchemaService:
    """Creates, modifies, explains, and validates schemas without producing code."""

    model = "gemini-3.1-flash-lite"

    async def create_schema(self, user_prompt: str) -> dict[str, Any]:
        return await self._generate(user_prompt, allow_fallback=True)

    async def modify_schema(self, schema: dict[str, Any], user_prompt: str) -> dict[str, Any]:
        payload = json.dumps({"existing_schema": schema, "request": user_prompt})
        return await self._generate(payload, allow_fallback=False)

    def explain_schema(self, schema: dict[str, Any]) -> str:
        validate_bot_schema(schema)
        flow_count = len(schema["flows"])
        return f"{schema['metadata']['name']} has {flow_count} flow(s)."

    def validate_schema(self, schema: dict[str, Any]) -> None:
        validate_bot_schema(schema)

    def suggest_improvements(self, schema: dict[str, Any]) -> list[str]:
        validate_bot_schema(schema)
        suggestions: list[str] = []
        if not schema.get("permissions"):
            suggestions.append("Add permissions metadata for admin-only or broadcast flows.")
        if not any(step.get("type") == "analytics" for flow in schema["flows"] for step in flow["steps"]):
            suggestions.append("Add analytics steps for important conversions.")
        return suggestions or ["Schema is already concise and deployable."]

    async def _generate(self, contents: str, allow_fallback: bool) -> dict[str, Any]:
        os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
        from google import genai
        from google.genai import types

        client = genai.Client()
        validation_error: Exception | None = None
        current_contents = contents
        for attempt in range(2):
            response = client.models.generate_content(
                model=self.model,
                contents=current_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SCHEMA_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_json_schema=BOT_SCHEMA_JSON_SCHEMA,
                ),
            )
            parsed: Any = None
            try:
                parsed = json.loads(response.text or "{}")
                if not isinstance(parsed, dict):
                    raise ValueError("Gemini returned a non-object schema")
                data = normalize_bot_schema(parsed)
                validate_bot_schema(data)
                return data
            except (JSONDecodeError, SchemaValidationError, ValueError) as exc:
                validation_error = exc
                if attempt == 1:
                    break
                current_contents = _repair_prompt(contents, parsed, exc)

        if allow_fallback:
            fallback = _fallback_schema(contents)
            validate_bot_schema(fallback)
            return fallback
        raise ValueError(f"Gemini returned an invalid bot schema: {validation_error}") from validation_error


def _repair_prompt(
    original_contents: str,
    invalid_schema: Any,
    error: Exception,
) -> str:
    return json.dumps(
        {
            "task": "Repair this bot schema. Return only corrected JSON matching the schema contract.",
            "original_request": original_contents,
            "validation_error": str(error),
            "invalid_schema": invalid_schema,
            "repair_rules": [
                "Return a complete production-ready Telegram schema, not a placeholder.",
                "Use buttons/callbacks for finite choices instead of plain-text menus.",
                "Every step must have a valid type.",
                "set_variable requires name and value; do not use save_as on set_variable.",
                "database_query set/upsert/save requires key and value.",
                "Prefer next_flow when jumping to another flow.",
                "Prefer next_step only for step ids inside the same flow.",
                "For finite-choice interactions, include buttons with callback values.",
            ],
        },
        ensure_ascii=False,
    )


def _fallback_schema(user_prompt: str) -> dict[str, Any]:
    name = _fallback_name(user_prompt)
    return {
        "metadata": {
            "name": name,
            "description": "Safe fallback schema generated after AI validation failed.",
        },
        "permissions": {},
        "database": {},
        "variables": {},
        "flows": [
            {
                "id": "start",
                "trigger": "/start",
                "steps": [
                    {
                        "type": "message",
                        "text": f"{name} is ready. The requested advanced schema could not be generated safely, so this fallback bot was created.",
                    },
                    {
                        "type": "buttons",
                        "text": "Choose an option:",
                        "buttons": [
                            {"text": "Help", "value": "help"},
                            {"text": "Restart", "value": "/start"},
                        ],
                    },
                ],
            },
            {
                "id": "help",
                "trigger": {"type": "callback", "value": "help"},
                "steps": [
                    {
                        "type": "message",
                        "text": "Edit this bot with /editbot and describe the behavior you want in smaller pieces.",
                    }
                ],
            },
        ],
    }


def _fallback_name(user_prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", user_prompt)
    if not words:
        return "Generated Bot"
    ignored = {"create", "a", "an", "the", "bot", "telegram", "for", "with"}
    title_words = [word for word in words[:8] if word.lower() not in ignored]
    if not title_words:
        title_words = words[:3]
    return " ".join(title_words[:4]).title()[:60]


AiAction = Literal["create", "modify", "explain", "validate", "suggest"]
