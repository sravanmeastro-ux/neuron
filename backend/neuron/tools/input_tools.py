"""Keyboard / mouse input tools (fallback after UIA)."""

from __future__ import annotations

from neuron.windows import input_ops


def press_key(args: dict):
    return input_ops.press_key(args or {})


def hotkey(args: dict):
    return input_ops.hotkey(args or {})


def type_text(args: dict):
    return input_ops.type_text(args or {})


def scroll(args: dict):
    return input_ops.scroll(args or {})


def click(args: dict):
    import actions
    return actions.click(args.get("button") or "left", bool(args.get("double")))
