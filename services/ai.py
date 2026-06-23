"""Gemini schema-only AI integration."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from schemas.bot_schema import BOT_SCHEMA_JSON_SCHEMA, normalize_bot_schema, validate_bot_schema


SCHEMA_SYSTEM_PROMPT = """
You generate Telegram bot definitions only as JSON.
Return one JSON object matching the supplied response schema.
Do not return prose, markdown, code, Python, or explanations.
Use only supported step types and declarative fields.
Every flow step must include a "type" field.
Use "message" or "send_message" for text replies and "buttons" for button lists.
Never include executable code, shell commands, eval strings, or Python snippets.
""".strip()


class AiSchemaService:
    """Creates, modifies, explains, and validates schemas without producing code."""

    model = "gemini-3.1-flash-lite"

    async def create_schema(self, user_prompt: str) -> dict[str, Any]:
        return await self._generate(user_prompt)

    async def modify_schema(self, schema: dict[str, Any], user_prompt: str) -> dict[str, Any]:
        payload = json.dumps({"existing_schema": schema, "request": user_prompt})
        return await self._generate(payload)

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

    async def _generate(self, contents: str) -> dict[str, Any]:
        os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "")
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SCHEMA_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=BOT_SCHEMA_JSON_SCHEMA,
            ),
        )
        data = json.loads(response.text or "{}")
        if not isinstance(data, dict):
            raise ValueError("Gemini returned a non-object schema")
        data = normalize_bot_schema(data)
        validate_bot_schema(data)
        return data


AiAction = Literal["create", "modify", "explain", "validate", "suggest"]
