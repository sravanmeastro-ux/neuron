"""V3.5 ToolRegistry façade — centralized over neuron.brain.tool_registry.

Reuses existing action handlers. Does not rewrite tools.
"""

from __future__ import annotations

from neuron.brain.tool_registry import (
    ToolSpec,
    all_tools,
    ensure_bootstrapped,
    execute,
    get,
    is_registered,
    names,
    register,
    reset_for_tests,
    resolve_name,
    tools_doc,
    validate_args,
)

# Canonical primitive names expected by V3.5 docs / tests
PRIMITIVES = (
    "open_app",
    "close_app",
    "focus_window",
    "move_window",
    "inspect_screen",
    "find_element",
    "click_element",
    "click",
    "type_text",
    "press_key",
    "hotkey",
    "scroll",
    "open_url",
    "browser_search",
    "read_page",
    "find_file",
    "open_file",
    "wait",
    "verify",
    "speak",
)


def ensure_primitives() -> list[str]:
    """Return which PRIMITIVES are registered (after bootstrap)."""
    ensure_bootstrapped()
    return [n for n in PRIMITIVES if is_registered(n)]


__all__ = [
    "ToolSpec",
    "PRIMITIVES",
    "ensure_primitives",
    "ensure_bootstrapped",
    "register",
    "get",
    "is_registered",
    "all_tools",
    "names",
    "validate_args",
    "execute",
    "resolve_name",
    "tools_doc",
    "reset_for_tests",
]
