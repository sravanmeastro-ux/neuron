"""Load plugins from disk, register actions, hot-reload."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Any

from neuron.plugins.permissions import check_dependencies, validate_manifest
from neuron.plugins.sdk import LoadedPlugin, PluginManifest

_LOCK = threading.Lock()
_LOADED: dict[str, LoadedPlugin] = {}
_OWNED_TOOLS: dict[str, str] = {}  # tool_name -> plugin_id

BUILTIN_ROOT = Path(__file__).resolve().parent / "builtin"
NEURON_VERSION = "4.10.0"


def plugin_roots() -> list[Path]:
    roots = [BUILTIN_ROOT]
    # Market install directory (production SDK)
    try:
        from neuron.plugin_market.paths import installed_root
        ir = installed_root()
        if ir.is_dir():
            roots.append(ir)
    except Exception:
        pass
    try:
        import json as _json
        from pathlib import Path as P
        cfg = _json.loads(
            (P(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        plug = cfg.get("plugins") or {}
        if plug.get("enabled") is False:
            return []
        extra = plug.get("paths") or []
        for p in extra:
            roots.append(Path(p))
    except Exception:
        pass
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r.resolve()) if r.exists() else str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def discover() -> list[Path]:
    found: list[Path] = []
    for root in plugin_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "plugin.json").is_file():
                found.append(child)
    return found


def _read_manifest(root: Path) -> PluginManifest:
    data = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    return PluginManifest.from_dict(data)


def _load_module(root: Path, name: str = "actions"):
    path = root / f"{name}.py"
    if not path.is_file():
        return None
    mod_name = f"neuron_plugin_{root.name}_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolve_handler(root: Path, handler_ref: str):
    """handler like 'actions:open' → attribute open on actions.py"""
    if ":" not in handler_ref:
        handler_ref = f"actions:{handler_ref}"
    mod_name, attr = handler_ref.split(":", 1)
    mod = _load_module(root, mod_name)
    if mod is None:
        raise ImportError(f"No module {mod_name}.py in {root}")
    fn = getattr(mod, attr, None)
    if fn is None:
        raise AttributeError(f"{mod_name}.{attr} not found")
    return fn


def _make_tool_handler(fn):
    def _h(args: dict | None = None):
        args = args or {}
        try:
            return fn(args)
        except TypeError:
            # allow fn() with no args
            return fn()
    return _h


def load_plugin(root: Path, *, register: bool = True) -> LoadedPlugin:
    manifest = _read_manifest(root)
    loaded = LoadedPlugin(manifest=manifest, root=str(root))
    errs = validate_manifest(manifest)
    dep_errs = check_dependencies(manifest, neuron_version=NEURON_VERSION)
    if errs or dep_errs:
        loaded.enabled = False
        loaded.load_error = "; ".join(errs + dep_errs)
        return loaded

    # Config defaults
    loaded.config = dict(manifest.config.defaults or {})

    handlers: dict = {}
    for action in manifest.actions:
        try:
            fn = _resolve_handler(root, action.handler or "actions:default")
            handlers[action.name] = _make_tool_handler(fn)
        except Exception as exc:
            loaded.enabled = False
            loaded.load_error = f"Handler {action.name}: {exc}"
            return loaded
    loaded.handlers = handlers

    if register:
        _register(loaded)
    with _LOCK:
        _LOADED[manifest.id] = loaded
    return loaded


def _register(loaded: LoadedPlugin) -> None:
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    m = loaded.manifest
    owned: list[str] = []
    for action in m.actions:
        fn = loaded.handlers.get(action.name)
        if not fn:
            continue
        methods = action.control_methods or list(m.permissions.control_methods)
        tool_registry.register(
            action.name,
            fn,
            description=action.description or f"{m.name}: {action.name}",
            args_schema=action.args_schema or {},
            risk=action.risk or "safe",
            overwrite=True,
            planner_visible=m.permissions.planner_visible,
            aliases=action.aliases or None,
            control_methods=methods,
        )
        owned.append(action.name)
        # underscore alias
        und = action.name.replace(".", "_")
        if und != action.name:
            tool_registry.register(
                und,
                fn,
                description=action.description or action.name,
                args_schema=action.args_schema or {},
                risk=action.risk or "safe",
                overwrite=True,
                planner_visible=False,
                control_methods=methods,
            )
            owned.append(und)
        with _LOCK:
            _OWNED_TOOLS[action.name] = m.id
            _OWNED_TOOLS[und] = m.id
    loaded.registered_tools = owned


def unload_plugin(plugin_id: str) -> bool:
    with _LOCK:
        loaded = _LOADED.pop(plugin_id, None)
        if not loaded:
            return False
        tools = [t for t, pid in list(_OWNED_TOOLS.items()) if pid == plugin_id]
        for t in tools:
            _OWNED_TOOLS.pop(t, None)
    try:
        from neuron.brain import tool_registry
        for t in tools:
            if hasattr(tool_registry, "unregister"):
                tool_registry.unregister(t)
            else:
                # Best-effort: overwrite with noop fail
                from neuron.windows.result import fail
                tool_registry.register(
                    t,
                    lambda a, _t=t: fail(f"Plugin unloaded ({_t})"),
                    description="unloaded",
                    overwrite=True,
                    planner_visible=False,
                )
    except Exception:
        pass
    return True


def reload_plugin(plugin_id: str) -> LoadedPlugin | None:
    with _LOCK:
        prev = _LOADED.get(plugin_id)
    if not prev:
        # try rediscover
        for root in discover():
            try:
                m = _read_manifest(root)
                if m.id == plugin_id:
                    return load_plugin(root, register=True)
            except Exception:
                continue
        return None
    unload_plugin(plugin_id)
    return load_plugin(Path(prev.root), register=True)


def load_all() -> list[LoadedPlugin]:
    out: list[LoadedPlugin] = []
    # Dependency order: plugins with fewer plugin-deps first
    roots = discover()
    manifests = []
    for root in roots:
        try:
            manifests.append((_read_manifest(root), root))
        except Exception:
            continue
    manifests.sort(key=lambda x: len(x[0].dependencies.plugins))
    # Simple multi-pass for plugin deps
    pending = list(manifests)
    loaded_ids: set[str] = set()
    for _ in range(len(pending) + 1):
        if not pending:
            break
        next_pending = []
        for man, root in pending:
            need = set(man.dependencies.plugins or [])
            if need - loaded_ids:
                next_pending.append((man, root))
                continue
            lp = load_plugin(root, register=True)
            out.append(lp)
            if lp.enabled:
                loaded_ids.add(man.id)
        if len(next_pending) == len(pending):
            # cycle / missing — load remaining with errors
            for man, root in next_pending:
                out.append(load_plugin(root, register=True))
            break
        pending = next_pending
    return out


def list_plugins() -> list[dict[str, Any]]:
    with _LOCK:
        return [p.to_dict() for p in _LOADED.values()]


def get_plugin(plugin_id: str) -> LoadedPlugin | None:
    return _LOADED.get(plugin_id)


def intents_index() -> list[dict[str, Any]]:
    out = []
    with _LOCK:
        for p in _LOADED.values():
            if not p.enabled:
                continue
            for intent in p.manifest.intents:
                out.append({
                    "plugin": p.manifest.id,
                    "id": intent.id,
                    "aliases": intent.aliases,
                    "prefer": intent.prefer,
                })
    return out
