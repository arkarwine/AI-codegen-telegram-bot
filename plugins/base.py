"""Plugin interfaces for declarative runtime actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class PluginContext:
    """Runtime context passed to each plugin execution."""

    bot_id: int
    user_id: int
    client: Any
    message: Any
    session_data: dict[str, Any]
    services: dict[str, Any]


class Plugin(Protocol):
    name: str
    version: str
    config_schema: dict[str, Any]

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        """Run one declarative action and return state updates."""
