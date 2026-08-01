"""Plugin manager public API — list / reload / docs / bootstrap."""

from __future__ import annotations

from typing import Any

from neuron.plugins import loader


def bootstrap() -> list[dict[str, Any]]:
    loaded = loader.load_all()
    return [p.to_dict() for p in loaded]


def list_plugins() -> list[dict[str, Any]]:
    return loader.list_plugins()


def reload(plugin_id: str) -> dict[str, Any]:
    p = loader.reload_plugin(plugin_id)
    if p is None:
        return {"ok": False, "error": f"Unknown plugin {plugin_id}"}
    return {"ok": p.enabled, "plugin": p.to_dict(), "error": p.load_error}


def docs(plugin_id: str) -> str:
    p = loader.get_plugin(plugin_id)
    if not p:
        return f"Plugin {plugin_id} not loaded."
    from pathlib import Path
    readme = Path(p.root) / (p.manifest.docs or "README.md")
    if readme.is_file():
        return readme.read_text(encoding="utf-8")[:4000]
    return p.manifest.description or p.manifest.name


def tool_plugins_list(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    return ok("Installed plugins.", state={"plugins": list_plugins(), "intents": loader.intents_index()})


def tool_plugin_reload(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    pid = str(args.get("id") or args.get("plugin") or "").strip()
    if not pid:
        return fail("Need plugin id.")
    result = reload(pid)
    if result.get("ok"):
        return ok(f"Reloaded {pid}.", state=result)
    return fail(result.get("error") or "Reload failed.", state=result)


def tool_plugin_docs(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    pid = str(args.get("id") or args.get("plugin") or "").strip()
    if not pid:
        return fail("Need plugin id.")
    return ok(docs(pid), state={"id": pid})
