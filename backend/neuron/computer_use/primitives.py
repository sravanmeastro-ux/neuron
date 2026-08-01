"""Low-level computer primitives — wrap actions + new drag/upload."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from neuron.windows.result import fail, ok


def click_xy(x: int, y: int, *, button: str = "left", clicks: int = 1) -> Any:
    try:
        import pyautogui
        pyautogui.click(int(x), int(y), clicks=int(clicks), button=button)
        return ok(f"Clicked ({x},{y}).", state={"x": x, "y": y}, method="pyautogui")
    except Exception as exc:
        return fail(str(exc))


def move_to(x: int, y: int, *, duration: float = 0.15) -> Any:
    try:
        import pyautogui
        pyautogui.moveTo(int(x), int(y), duration=float(duration))
        return ok(f"Moved to ({x},{y}).", method="pyautogui")
    except Exception as exc:
        return fail(str(exc))


def type_text(text: str) -> Any:
    try:
        from neuron.windows import input_ops
        return input_ops.type_text({"text": text})
    except Exception:
        try:
            import actions
            return ok(actions.type_text(text), method="actions")
        except Exception as exc:
            return fail(str(exc))


def press_keys(keys: str) -> Any:
    try:
        from neuron.windows import input_ops
        return input_ops.hotkey({"keys": keys}) if (" " in keys or "+" in keys) else input_ops.press_key({"key": keys})
    except Exception:
        try:
            import actions
            return ok(actions.press_keys(keys), method="actions")
        except Exception as exc:
            return fail(str(exc))


def scroll(direction: str = "down", *, clicks: int = 3) -> Any:
    try:
        from neuron.windows import input_ops
        return input_ops.scroll({"direction": direction, "clicks": clicks})
    except Exception:
        try:
            import actions
            return ok(actions.scroll(direction), method="actions")
        except Exception as exc:
            return fail(str(exc))


def drag_drop(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: float = 0.35,
    button: str = "left",
) -> Any:
    """Drag from (x1,y1) to (x2,y2)."""
    try:
        import pyautogui
        pyautogui.moveTo(int(x1), int(y1), duration=0.1)
        pyautogui.dragTo(int(x2), int(y2), duration=float(duration), button=button)
        return ok(
            f"Dragged ({x1},{y1}) -> ({x2},{y2}).",
            state={"from": [x1, y1], "to": [x2, y2]},
            method="pyautogui",
        )
    except Exception as exc:
        return fail(str(exc))


def upload_file(path: str, *, method: str = "dialog") -> Any:
    """
    Upload / attach a file.
    method=dialog: type path into focused Open/Upload file dialog + Enter.
    method=clipboard: copy path (caller should paste).
    """
    p = Path(path).expanduser()
    if not p.exists() and method == "dialog":
        # Still try typing — dialog may resolve relative paths
        pass
    full = str(p.resolve()) if p.exists() else str(p)
    try:
        if method == "clipboard":
            import pyperclip
            pyperclip.copy(full)
            return ok(f"Path copied: {full}", state={"path": full}, method="clipboard")
        # Focus dialog and type path
        time.sleep(0.2)
        import pyautogui
        pyautogui.hotkey("alt", "n")  # File name field on many Windows dialogs
        time.sleep(0.1)
        pyautogui.typewrite(full, interval=0.01)
        time.sleep(0.1)
        pyautogui.press("enter")
        return ok(f"Submitted file path {p.name}.", state={"path": full}, method="dialog")
    except Exception as exc:
        return fail(str(exc), state={"path": full})


def tool_drag_drop(args: dict | None = None) -> Any:
    args = args or {}
    return drag_drop(
        int(args.get("x1") or args.get("from_x") or 0),
        int(args.get("y1") or args.get("from_y") or 0),
        int(args.get("x2") or args.get("to_x") or 0),
        int(args.get("y2") or args.get("to_y") or 0),
        duration=float(args.get("duration") or 0.35),
        button=str(args.get("button") or "left"),
    )


def tool_upload_file(args: dict | None = None) -> Any:
    args = args or {}
    path = (args.get("path") or args.get("file") or "").strip()
    if not path:
        return fail("Need a file path to upload.")
    return upload_file(path, method=str(args.get("method") or "dialog"))
