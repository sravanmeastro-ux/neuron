"""Shared helpers for domain skills."""

from __future__ import annotations

from typing import Any

from neuron.windows.result import ToolResult, fail, ok


def as_result(value: Any, *, method: str = "skill") -> ToolResult:
    """Normalize strings / ToolResult / exceptions into ToolResult."""
    if isinstance(value, ToolResult):
        return value
    if isinstance(value, Exception):
        return fail(str(value), method=method)
    if value is None:
        return ok("Done.", method=method)
    text = str(value)
    low = text.lower()
    if any(
        x in low
        for x in (
            "couldn't",
            "could not",
            "failed",
            "not found",
            "isn't available",
            "isn't open",
            "need a ",
            "no monitors",
            "denied",
        )
    ):
        return fail(text, method=method)
    return ok(text, method=method)


def arg(args: dict | None, *keys: str, default: Any = "") -> Any:
    args = args or {}
    for k in keys:
        if k in args and args[k] not in (None, ""):
            return args[k]
    return default


def handler(fn):
    """Wrap a skill(fn) so the tool registry can call it with a dict."""

    def _h(args: dict | None = None):
        try:
            return fn(args or {})
        except Exception as exc:
            return fail(str(exc), method="skill")

    return _h
