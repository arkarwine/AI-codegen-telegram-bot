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


SCHEMA_REFINEMENT_PASSES = 3


SCHEMA_SYSTEM_PROMPT = """
Return exactly one valid Telegram bot schema JSON object. No prose, markdown,
comments, code fences, Python, JavaScript, SQL, shell, eval, or unsupported
actions. User bots are declarative JSON only.

Design standard:
- You are building a real Telegram bot. The schema must describe Telegram bot
  behavior, Telegram messages, Telegram commands, and Telegram callback buttons.
- Build a production-ready, professional, complete Telegram bot, not a demo,
  placeholder, toy, or "basic implementation".
- User prompts may be short. Expand and extend them with sensible product ideas,
  complete workflows, useful defaults, existing best-practice patterns, admin
  features, analytics, persistence, and polished Telegram UX.
- Finish the requested workflow end-to-end: onboarding, menus, collection,
  validation, persistence, confirmations, admin paths, and fallbacks as relevant.
- Message text should be informative and elaborate enough to guide the user:
  explain choices, next steps, confirmations, errors, and summaries clearly.
- Use tasteful emojis in Telegram messages and button labels for clarity,
  hierarchy, emotion, and scannability. Do not overuse them.
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
- Prefix callback groups must be explicit: if buttons use pos_1, pos_2, pos_3,
  use {"type":"callback","value":"pos_","match":"prefix"}.

Transitions:
- id names a step inside the current flow.
- next_flow jumps to a flow id. next_step jumps only to a local step id.
- next, on_success, on_failure, then, else may target an existing flow id,
  local step id, "end", or "stop". All references must exist.
- when supports conditions and skips the step if false.

Templates and data:
- Use {{name}} or {{session.name}} for session data, {{user.name}} for user
  variables, {{global.name}} for bot variables, and {{event.text}},
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
  {"text":"Label","value":"callback_value"}, or rows of those objects. Button
  objects may use color/colour/style: primary, success, danger, warning, info,
  blue, green, red, yellow, orange, purple, neutral, dark. Telegram has no true
  per-button background colors, so the runtime renders color intent with
  colored emoji markers. Use colors/styles on important callback buttons.
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
- ai_chat: requires prompt; optional save_as and reply. Use save_as when later
  steps need the AI result.
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


SCHEMA_REFINEMENT_SYSTEM_PROMPT = f"""
{SCHEMA_SYSTEM_PROMPT}

Refinement task:
- You are improving an already valid generated Telegram bot schema.
- Keep faith with the original user's prompt, intent, domain, and goal.
- Do not replace the idea with a different bot.
- Extend, refine, and improve completeness, Telegram UX, copy quality,
  persistence, analytics, admin flows, callback buttons, and edge cases.
- Preserve working flow ids and triggers when possible, unless changing them is
  clearly needed for correctness.
- Return the entire improved schema JSON object, not a patch or explanation.
""".strip()


class AiSchemaService:
    """Creates, modifies, explains, and validates schemas without producing code."""

    model = "gemini-3.1-flash-lite"

    async def create_schema(self, user_prompt: str) -> dict[str, Any]:
        return await self._generate(user_prompt, allow_fallback=True, refine=True)

    async def modify_schema(self, schema: dict[str, Any], user_prompt: str) -> dict[str, Any]:
        payload = json.dumps({"existing_schema": schema, "request": user_prompt})
        return await self._generate(payload, allow_fallback=False, refine=True)

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

    async def _generate(self, contents: str, allow_fallback: bool, refine: bool) -> dict[str, Any]:
        os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
        from google import genai
        from google.genai import types

        client = genai.Client()
        try:
            data = await self._generate_valid_schema(
                client=client,
                types=types,
                contents=contents,
                system_instruction=SCHEMA_SYSTEM_PROMPT,
                repair_original=contents,
            )
            if refine:
                data = await self._refine_schema(client, types, contents, data)
            return data
        except (JSONDecodeError, SchemaValidationError, ValueError) as exc:
            validation_error: Exception = exc

        if allow_fallback:
            fallback = _fallback_schema(contents)
            validate_bot_schema(fallback)
            return fallback
        raise ValueError(f"Gemini returned an invalid bot schema: {validation_error}") from validation_error

    async def _generate_valid_schema(
        self,
        client: Any,
        types: Any,
        contents: str,
        system_instruction: str,
        repair_original: str,
    ) -> dict[str, Any]:
        validation_error: Exception | None = None
        current_contents = contents
        for attempt in range(2):
            response = client.models.generate_content(
                model=self.model,
                contents=current_contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
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
                current_contents = _repair_prompt(repair_original, parsed, exc)
        raise ValueError(f"Gemini returned an invalid bot schema: {validation_error}") from validation_error

    async def _refine_schema(
        self,
        client: Any,
        types: Any,
        original_contents: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        refined = schema
        for pass_number in range(1, _refinement_pass_count() + 1):
            payload = _refinement_prompt(original_contents, refined, pass_number)
            try:
                refined = await self._generate_valid_schema(
                    client=client,
                    types=types,
                    contents=payload,
                    system_instruction=SCHEMA_REFINEMENT_SYSTEM_PROMPT,
                    repair_original=payload,
                )
            except (JSONDecodeError, SchemaValidationError, ValueError):
                continue
        return refined


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
                "If the user prompt is short, expand it into a complete Telegram bot with useful flows.",
                "Use informative Telegram message text and tasteful emojis.",
                "Use buttons/callbacks for finite choices instead of plain-text menus.",
                "Use button color/style fields for important callback buttons.",
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


def _refinement_pass_count() -> int:
    raw_value = os.getenv("SCHEMA_REFINEMENT_PASSES", str(SCHEMA_REFINEMENT_PASSES))
    try:
        value = int(raw_value)
    except ValueError:
        return SCHEMA_REFINEMENT_PASSES
    return max(0, min(value, 5))


def _refinement_prompt(original_contents: str, schema: dict[str, Any], pass_number: int) -> str:
    focus = _refinement_focus(pass_number)
    return json.dumps(
        {
            "task": "Extend, refine, and improve this generated Telegram bot schema.",
            "pass_number": pass_number,
            "original_user_prompt_or_request": original_contents,
            "current_valid_schema": schema,
            "strict_rules": [
                "Return only the complete improved schema JSON object.",
                "Keep faith with the original user's prompt, goal, domain, and audience.",
                "Do not remove requested behavior unless it is invalid or unsafe.",
                "Do not invent executable code, SQL, shell commands, or unsupported plugins.",
                "Keep the bot deployable with the supported schema contract.",
            ],
            "improvement_focus": focus,
        },
        ensure_ascii=False,
    )


def _refinement_focus(pass_number: int) -> list[str]:
    focuses = [
        [
            "Expand short prompts into complete Telegram bot workflows.",
            "Add missing menus, callbacks, back/restart paths, and helpful onboarding.",
            "Make messages more informative, polished, and emoji-friendly.",
        ],
        [
            "Improve persistence with database_query for leads, tickets, bookings, scores, or records.",
            "Add analytics milestones and admin-only management flows where useful.",
            "Use user/global/session variables deliberately and consistently.",
        ],
        [
            "Improve Telegram-native UX: colored button styles, callback triggers, finite-choice buttons.",
            "Tighten transitions, conditions, validation prompts, confirmations, and error handling.",
            "Remove placeholder language and make the bot feel production-ready.",
        ],
    ]
    return focuses[(pass_number - 1) % len(focuses)]


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
                        "text": f"{name} is ready. I created a safe Telegram fallback bot because the requested advanced schema could not be validated. Use Help for the next step.",
                    },
                    {
                        "type": "buttons",
                        "text": "Choose what you would like to do next:",
                        "buttons": [
                            {"text": "Help", "value": "help", "color": "primary"},
                            {"text": "Restart", "value": "/start", "color": "neutral"},
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
