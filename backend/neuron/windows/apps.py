"""Phase 2 app control — open / close / focus / min / max / list."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from neuron.windows import state as win_state
from neuron.windows.resolve import resolve
from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[win-apps] {msg}", flush=True)


def _name(args: dict) -> str:
    return (
        args.get("name")
        or args.get("application")
        or args.get("app")
        or args.get("title")
        or ""
    ).strip()


def get_running_apps(args: dict | None = None) -> ToolResult:
    try:
        procs = win_state.list_running_processes(80)
        wins = win_state.list_top_windows(25)
        return ok(
            "Running: " + (", ".join(procs[:40]) if procs else "none"),
            state={"processes": procs, "windows": [w.get("title") for w in wins]},
            method="psutil+uia",
        )
    except Exception as exc:
        return fail(f"Couldn't list apps: {exc}")


def focus_app(args: dict | None = None) -> ToolResult:
    args = args or {}
    name = _name(args)
    if not name:
        return fail("Need an app name.")
    before = win_state.snapshot(name)
    resolved = resolve(name)
    _log(f"focus {resolved.canonical!r} (query={resolved.query!r})")

    # 1) UIA / Win32 by title
    wins = win_state.find_app_windows(resolved)
    if wins:
        hwnd = int(wins[0].get("hwnd") or 0)
        if win_state.focus_hwnd(hwnd):
            time.sleep(0.25)
            after = win_state.snapshot(name)
            fg = (after.get("foreground") or {}).get("title") or ""
            return ok(
                f"Focused {resolved.canonical}.",
                state={"before": before, "after": after, "resolved": resolved.canonical, "hwnd": hwnd},
                method="win32+uia",
            )
        # UIA SetActive via actions helper
        try:
            import actions
            if actions._focus_window_by_title(resolved.canonical) or actions._focus_window_by_title(resolved.query):
                after = win_state.snapshot(name)
                return ok(
                    f"Focused {resolved.canonical}.",
                    state={"before": before, "after": after, "resolved": resolved.canonical},
                    method="uia",
                )
        except Exception:
            pass

    # 2) pywinauto
    try:
        from pywinauto import Application
        for hint in resolved.title_hints:
            try:
                app = Application(backend="uia").connect(title_re=f"(?i).*{hint}.*", timeout=2)
                win = app.top_window()
                win.set_focus()
                after = win_state.snapshot(name)
                return ok(
                    f"Focused {resolved.canonical}.",
                    state={"before": before, "after": after, "resolved": resolved.canonical},
                    method="pywinauto",
                )
            except Exception:
                continue
    except Exception as exc:
        _log(f"pywinauto focus skip: {exc}")

    return fail(
        f"Couldn't find a window for {resolved.canonical}.",
        state={"before": before, "resolved": resolved.canonical},
    )


def open_app(args: dict | None = None) -> ToolResult:
    args = args or {}
    name = _name(args)
    auto_learn = bool(args.get("auto_learn", True))
    wait_s = float(args.get("wait_seconds") or 12)
    if not name:
        return fail("Need an app name.")

    # Reuse website / command-phrase guards from actions
    try:
        import actions
        key = name.strip().lower().strip(" .!?")
        if key in actions.WEB_SERVICES or key in ("yt",):
            return fail(f"'{name}' is a website — use open_website.")
        if actions._looks_like_command_phrase(key):
            return fail(f"'{name}' looks like a command, not an app name.")
    except Exception:
        pass

    resolved = resolve(name)
    before = win_state.snapshot(name)
    _log(f"open {resolved.canonical!r} launch={resolved.launch_target!r}")

    # Already running → focus + verify
    if win_state.app_is_running(resolved):
        fr = focus_app({"name": resolved.canonical})
        if fr.success:
            fr.message = f"{resolved.canonical} was already open - focused it."
            fr.state["launched"] = False
            return fr

    method = ""
    try:
        import actions
        target = resolved.launch_target
        # URI (ms-settings:)
        if str(target).endswith(":"):
            os.startfile(target)
            method = "shell-uri"
        else:
            exe = actions._resolve_exe(target) if hasattr(actions, "_resolve_exe") else None
            if exe:
                subprocess.Popen([exe])
                method = "win32-exe"
            elif len(resolved.query.split()) <= 3:
                # Start Menu last resort (existing reliable path)
                actions.open_from_start_menu(resolved.query or resolved.canonical)
                method = "startmenu"
            else:
                return fail(
                    f"I don't know how to launch '{name}'.",
                    state={"before": before, "resolved": resolved.canonical},
                )
        if auto_learn and hasattr(actions, "_schedule_learn_safe"):
            try:
                actions._schedule_learn_safe(resolved.canonical)
            except Exception:
                pass
    except Exception as exc:
        return fail(str(exc), state={"before": before, "resolved": resolved.canonical}, method=method)

    # Wait + verify window
    win = win_state.wait_for_app_window(resolved, timeout=wait_s)
    after = win_state.snapshot(name)
    if win:
        hwnd = int(win.get("hwnd") or 0)
        if hwnd:
            win_state.focus_hwnd(hwnd)
        return ok(
            f"Opened {resolved.canonical}.",
            state={
                "before": before,
                "after": after,
                "resolved": resolved.canonical,
                "window": win,
                "launched": True,
                "verified": True,
            },
            method=method,
        )

    # Soft success: process may exist without matching title yet
    if win_state.app_is_running(resolved):
        return ok(
            f"Started {resolved.canonical} (window title not confirmed yet).",
            state={
                "before": before,
                "after": after,
                "resolved": resolved.canonical,
                "launched": True,
                "verified": False,
            },
            method=method,
        )

    return fail(
        f"Launched {resolved.canonical} but couldn't verify a window within {wait_s:.0f}s.",
        state={"before": before, "after": after, "resolved": resolved.canonical, "verified": False},
        method=method,
    )


def close_app(args: dict | None = None) -> ToolResult:
    args = args or {}
    name = _name(args)
    before = win_state.snapshot(name)
    if not name:
        try:
            import actions
            actions.window("close")
            return ok("Closed foreground window.", state={"before": before}, method="hotkey")
        except Exception as exc:
            return fail(str(exc), state={"before": before})

    resolved = resolve(name)
    _log(f"close {resolved.canonical!r}")

    # Prefer existing close_app (handles controlled browser + taskkill)
    try:
        import actions
        msg = actions.close_app(resolved.canonical)
        time.sleep(0.4)
        after = win_state.snapshot(name)
        still = win_state.find_app_windows(resolved)
        success = not still
        if success:
            return ok(
                msg if isinstance(msg, str) else f"Closed {resolved.canonical}.",
                state={"before": before, "after": after, "resolved": resolved.canonical, "verified": True},
                method="uia+process",
            )
        return ok(
            msg if isinstance(msg, str) else f"Close requested for {resolved.canonical}.",
            state={"before": before, "after": after, "resolved": resolved.canonical, "verified": False},
            method="uia+process",
        )
    except Exception as exc:
        return fail(str(exc), state={"before": before, "resolved": resolved.canonical})


def _window_show(args: dict, show_cmd: int, label: str) -> ToolResult:
    args = args or {}
    name = _name(args)
    before = win_state.snapshot(name)
    resolved = resolve(name) if name else None
    hwnd = 0
    if resolved:
        wins = win_state.find_app_windows(resolved)
        if wins:
            hwnd = int(wins[0].get("hwnd") or 0)
    if not hwnd:
        hwnd = win_state.find_window_hwnd(name)
    if not hwnd:
        fg = win_state.get_foreground()
        hwnd = int(fg.get("hwnd") or 0)
    if not hwnd:
        # hotkey fallback on whatever is focused
        try:
            import actions
            actions.window("minimize" if "min" in label else "maximize")
            after = win_state.snapshot(name)
            return ok(f"{label} (hotkey).", state={"before": before, "after": after}, method="hotkey")
        except Exception as exc:
            return fail(str(exc), state={"before": before})

    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(hwnd, show_cmd)
        win_state.focus_hwnd(hwnd)
        time.sleep(0.2)
        after = win_state.snapshot(name)
        return ok(
            f"{label} {resolved.canonical if resolved else 'window'}.",
            state={"before": before, "after": after, "hwnd": hwnd},
            method="win32",
        )
    except Exception as exc:
        return fail(str(exc), state={"before": before, "hwnd": hwnd})


def minimize_app(args: dict | None = None) -> ToolResult:
    # SW_MINIMIZE = 6
    return _window_show(args or {}, 6, "Minimized")


def maximize_app(args: dict | None = None) -> ToolResult:
    # SW_MAXIMIZE = 3
    return _window_show(args or {}, 3, "Maximized")
