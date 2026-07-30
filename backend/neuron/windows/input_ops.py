"""Phase 2 keyboard / scroll — UIA focus first, pyautogui fallback."""

from __future__ import annotations

from neuron.windows import state as win_state
from neuron.windows.resolve import resolve
from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[win-input] {msg}", flush=True)


def _maybe_focus(args: dict) -> None:
    app = (args.get("app") or args.get("where") or args.get("name") or "").strip()
    if not app:
        return
    try:
        from neuron.windows import apps as wapps
        wapps.focus_app({"name": app})
    except Exception as exc:
        _log(f"focus before input failed: {exc}")


def type_text(args: dict | None = None) -> ToolResult:
    args = args or {}
    text = args.get("text") or ""
    if not text:
        return fail("Need text to type.")
    before = win_state.get_foreground()
    _maybe_focus(args)
    try:
        import actions
        msg = actions.type_text(str(text))
        after = win_state.get_foreground()
        return ok(
            msg if isinstance(msg, str) else f"Typed: {text}",
            state={"before_fg": before, "after_fg": after},
            method="pyautogui",
        )
    except Exception as exc:
        return fail(str(exc), state={"before_fg": before})


def press_key(args: dict | None = None) -> ToolResult:
    args = args or {}
    key = (args.get("key") or args.get("keys") or "").strip()
    if not key:
        return fail("Which key?")
    before = win_state.get_foreground()
    _maybe_focus(args)
    try:
        import actions
        # Single key — avoid treating "control c" as press_key; use hotkey
        parts = key.lower().replace("+", " ").replace(" plus ", " ").split()
        if len(parts) > 1:
            return hotkey({"keys": key, **{k: v for k, v in args.items() if k != "keys"}})
        msg = actions.press_keys(key)
        return ok(
            msg if isinstance(msg, str) else f"Pressed {key}.",
            state={"before_fg": before, "after_fg": win_state.get_foreground()},
            method="pyautogui",
        )
    except Exception as exc:
        return fail(str(exc))


def hotkey(args: dict | None = None) -> ToolResult:
    args = args or {}
    keys = (
        args.get("keys")
        or args.get("key")
        or args.get("combo")
        or ""
    )
    if isinstance(keys, (list, tuple)):
        spoken = " ".join(str(k) for k in keys)
    else:
        spoken = str(keys).strip()
    if not spoken:
        return fail("Need a hotkey combo like 'ctrl c' or 'alt tab'.")
    before = win_state.get_foreground()
    _maybe_focus(args)
    try:
        import actions
        msg = actions.press_keys(spoken)
        return ok(
            msg if isinstance(msg, str) else f"Pressed {spoken}.",
            state={"before_fg": before, "after_fg": win_state.get_foreground(), "keys": spoken},
            method="pyautogui",
        )
    except Exception as exc:
        return fail(str(exc))


def scroll(args: dict | None = None) -> ToolResult:
    args = args or {}
    direction = (args.get("direction") or "down").strip().lower()
    if direction not in ("up", "down", "left", "right"):
        direction = "down"
    app = (args.get("app") or args.get("where") or "").strip()
    before = win_state.get_foreground()
    try:
        import actions
        msg = actions.scroll(direction, app=app)
        return ok(
            msg if isinstance(msg, str) else f"Scrolled {direction}.",
            state={"before_fg": before, "after_fg": win_state.get_foreground(), "app": app},
            method="pyautogui+uia",
        )
    except Exception as exc:
        return fail(str(exc))
