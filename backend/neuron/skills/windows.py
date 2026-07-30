"""Windows desktop skill workflows."""

from __future__ import annotations

from neuron.skills._util import arg, as_result, handler
from neuron.windows.result import ToolResult, fail


def focus_app(name: str) -> ToolResult:
    n = (name or "").strip()
    if not n:
        return fail("Need an app name.")
    try:
        from neuron.tools import apps as apps_t
        return as_result(apps_t.focus_app({"name": n}), method="windows")
    except Exception as exc:
        return fail(str(exc))


def open_app(name: str) -> ToolResult:
    n = (name or "").strip()
    if not n:
        return fail("Need an app name.")
    try:
        from neuron.tools import apps as apps_t
        return as_result(apps_t.open_app({"name": n}), method="windows")
    except Exception:
        pass
    try:
        import actions
        return as_result(actions.open_app(n), method="windows")
    except Exception as exc:
        return fail(str(exc))


def close_app(name: str) -> ToolResult:
    n = (name or "").strip()
    if not n:
        return fail("Need an app name.")
    try:
        from neuron.tools import apps as apps_t
        return as_result(apps_t.close_app({"name": n}), method="windows")
    except Exception as exc:
        return fail(str(exc))


def move_to_monitor(app_or_title: str, monitor: int | str = 2) -> ToolResult:
    """Move a window onto a target monitor (id / left / right / main / other)."""
    title = (app_or_title or "").strip()
    if not title:
        return fail("Need a window title or app name.")
    try:
        from neuron.tools import windows as win_t
        return as_result(
            win_t.move_window_to_monitor({
                "title": title,
                "name": title,
                "monitor": monitor,
            }),
            method="windows",
        )
    except Exception as exc:
        return fail(str(exc))


def get_monitors() -> ToolResult:
    try:
        from neuron.tools import windows as win_t
        return as_result(win_t.get_monitors({}), method="windows")
    except Exception as exc:
        return fail(str(exc))


def maximize(name: str = "") -> ToolResult:
    try:
        from neuron.tools import apps as apps_t
        return as_result(apps_t.maximize_app({"name": name or ""}), method="windows")
    except Exception as exc:
        return fail(str(exc))


def minimize(name: str = "") -> ToolResult:
    try:
        from neuron.tools import apps as apps_t
        return as_result(apps_t.minimize_app({"name": name or ""}), method="windows")
    except Exception as exc:
        return fail(str(exc))


focus_app_tool = handler(lambda a: focus_app(str(arg(a, "name", "app", "title"))))
open_app_tool = handler(lambda a: open_app(str(arg(a, "name", "app"))))
close_app_tool = handler(lambda a: close_app(str(arg(a, "name", "app"))))
move_to_monitor_tool = handler(
    lambda a: move_to_monitor(
        str(arg(a, "name", "app", "title", "window")),
        arg(a, "monitor", "monitor_id", "screen", default=2),
    )
)
get_monitors_tool = handler(lambda a: get_monitors())
maximize_tool = handler(lambda a: maximize(str(arg(a, "name", "app", default=""))))
minimize_tool = handler(lambda a: minimize(str(arg(a, "name", "app", default=""))))
