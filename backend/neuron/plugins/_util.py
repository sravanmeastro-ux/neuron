"""Shared helpers for builtin plugins."""

from __future__ import annotations

from typing import Any


def open_app(name: str, *, wait: float = 2.0) -> Any:
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    return tool_registry.execute("open_app", {"name": name, "wait_seconds": wait}, confirmed=True)


def open_website(url: str) -> Any:
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    return tool_registry.execute("open_website", {"url": url}, confirmed=True)


def focus(name: str) -> Any:
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    try:
        return tool_registry.execute("focus_app", {"name": name}, confirmed=True)
    except Exception:
        return open_app(name)


def ok_msg(msg: str, **state) -> Any:
    from neuron.windows.result import ok
    return ok(msg, state=state or {}, method="plugin")
