"""Example custom plugin.

Drop a module in ``plugins/`` and expose a ``plugin`` object. The runtime will
auto-load it, but schemas still must refer to its declared name.
"""

from __future__ import annotations

from typing import Any

from plugins.base import PluginContext


class UppercaseReplyPlugin:
    name = "uppercase_reply"
    version = "1.0.0"
    config_schema = {"type": "object", "required": ["text"]}

    async def execute(self, config: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        await context.message.reply_text(str(config["text"]).upper())
        return {}


plugin = UppercaseReplyPlugin()
