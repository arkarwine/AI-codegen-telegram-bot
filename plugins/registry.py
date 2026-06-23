"""Plugin auto-loader and registry."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any

from plugins import builtin
from plugins.base import Plugin


class PluginRegistry:
    """Keeps the runtime's allow-list of executable actions."""

    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        self.plugins[plugin.name] = plugin

    def get(self, name: str) -> Plugin:
        if name == "message":
            name = "send_message"
        plugin = self.plugins.get(name)
        if plugin is None:
            raise LookupError(f"plugin is not enabled: {name}")
        return plugin

    def load_builtin(self) -> None:
        for item in (
            builtin.SendMessagePlugin(),
            builtin.ButtonsPlugin(),
            builtin.EditMessagePlugin(),
            builtin.DeleteMessagePlugin(),
            builtin.WaitForInputPlugin(),
            builtin.ConditionPlugin(),
            builtin.SetVariablePlugin(),
            builtin.GetVariablePlugin(),
            builtin.DatabaseQueryPlugin(),
            builtin.HttpRequestPlugin(),
            builtin.AiChatPlugin(),
            builtin.SchedulerPlugin(),
            builtin.BroadcastPlugin(),
            builtin.AdminOnlyPlugin(),
            builtin.AnalyticsPlugin(),
        ):
            self.register(item)

    def auto_load_custom(self, folder: Path) -> None:
        """Import plugins from a folder when they expose ``plugin``."""

        if not folder.exists():
            return
        for module_info in pkgutil.iter_modules([str(folder)]):
            module = importlib.import_module(f"plugins.{module_info.name}")
            plugin: Any = getattr(module, "plugin", None)
            if plugin is not None:
                self.register(plugin)


def build_registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.load_builtin()
    registry.auto_load_custom(Path(__file__).parent)
    return registry
