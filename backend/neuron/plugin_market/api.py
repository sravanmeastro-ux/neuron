"""Plugin Host API — developer-facing surface for third-party plugins."""

from __future__ import annotations

from typing import Any

HOST_API_VERSION = "1.0.0"


class NeuronPluginAPI:
    """Stable host API injected conceptually for plugin authors."""

    version = HOST_API_VERSION

    def log(self, message: str, *, level: str = "INFO") -> None:
        print(f"[plugin:{level}] {message}", flush=True)

    def get_config(self, plugin_id: str) -> dict[str, Any]:
        from neuron.plugins import loader
        p = loader.get_plugin(plugin_id)
        return dict(p.config) if p else {}

    def call_tool(self, name: str, args: dict[str, Any] | None = None, *, confirmed: bool = False) -> Any:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        return tool_registry.execute(name, args or {}, confirmed=confirmed)

    def list_tools(self) -> list[str]:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        specs = getattr(tool_registry, "_REGISTRY", {}) or {}
        return sorted(specs.keys())

    def neuron_version(self) -> str:
        from neuron.plugins.loader import NEURON_VERSION
        return NEURON_VERSION

    def has_permission(self, plugin_id: str, capability: str) -> bool:
        from neuron.plugin_market.trust import is_granted
        return is_granted(plugin_id, capability)

    def reload(self, plugin_id: str) -> dict[str, Any]:
        from neuron.plugins import manager
        return manager.reload(plugin_id)


def get_api() -> NeuronPluginAPI:
    return NeuronPluginAPI()


def api_docs() -> str:
    return (
        f"NEURON Plugin Host API v{HOST_API_VERSION}\n"
        "- api.log(msg)\n"
        "- api.get_config(plugin_id)\n"
        "- api.call_tool(name, args)\n"
        "- api.list_tools()\n"
        "- api.neuron_version()\n"
        "- api.has_permission(plugin_id, capability)\n"
        "- api.reload(plugin_id)\n"
        "Manifest: plugin.json with actions, intents, permissions, dependencies, api_version.\n"
    )
