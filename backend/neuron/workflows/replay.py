"""Replay workflows — tools, mouse, keyboard, control flow."""

from __future__ import annotations

import time
from typing import Any

from neuron.workflows.types import Workflow, WorkflowStep
from neuron.workflows.vars import eval_condition, loop_count, substitute


def _ok(msg: str, **state: Any) -> dict[str, Any]:
    return {"ok": True, "message": msg, **state}


def _fail(msg: str, **state: Any) -> dict[str, Any]:
    return {"ok": False, "error": msg, **state}


def _exec_tool(name: str, args: dict[str, Any]) -> Any:
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    return tool_registry.execute(name, args or {}, confirmed=True)


def _click_xy(x: int, y: int, button: str = "left") -> Any:
    try:
        import pyautogui
        pyautogui.click(int(x), int(y), button=button)
        return _ok(f"Clicked {button} at {x},{y}")
    except Exception as exc:
        return _fail(str(exc))


def _click_element(el: dict[str, Any]) -> Any:
    name = (el or {}).get("name") or ""
    if not name:
        return None
    try:
        return _exec_tool("click_element", {"name": name})
    except Exception:
        try:
            return _exec_tool("click_ui_element", {"name": name})
        except Exception:
            return None


def run_step(step: WorkflowStep, variables: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    kind = (step.kind or "").lower()
    args = substitute(dict(step.args or {}), variables)

    if kind == "set":
        key = str(args.get("name") or args.get("var") or "").strip()
        if not key:
            return _fail("set requires name")
        variables[key] = args.get("value")
        return _ok(f"Set {key}", variables=dict(variables))

    if kind == "wait":
        ms = float(args.get("ms") or args.get("seconds", 0) * 1000 or 0)
        if args.get("seconds") and not args.get("ms"):
            ms = float(args["seconds"]) * 1000
        ms = max(0, min(ms, 60000))
        if not dry_run and ms:
            time.sleep(ms / 1000.0)
        return _ok(f"Waited {ms:.0f}ms")

    if kind == "loop":
        # while condition OR count
        results = []
        if args.get("while") is not None:
            guard = 0
            max_iter = int(args.get("max") or 50)
            while eval_condition(args.get("while"), variables) and guard < max_iter:
                for child in step.steps:
                    r = run_step(child, variables, dry_run=dry_run)
                    results.append(r)
                    if not r.get("ok") and not args.get("continue_on_error"):
                        return _fail("Loop body failed", results=results)
                guard += 1
                # optional index var
                if args.get("as"):
                    variables[str(args["as"])] = guard
            return _ok(f"While loop x{guard}", results=results)
        n = loop_count(args, variables)
        for i in range(n):
            if args.get("as"):
                variables[str(args["as"])] = i
            for child in step.steps:
                r = run_step(child, variables, dry_run=dry_run)
                results.append(r)
                if not r.get("ok") and not args.get("continue_on_error"):
                    return _fail(f"Loop failed at i={i}", results=results)
        return _ok(f"Looped {n} times", results=results)

    if kind == "if":
        cond = args.get("when", args.get("condition", True))
        body = step.steps if eval_condition(cond, variables) else step.else_steps
        results = []
        for child in body:
            r = run_step(child, variables, dry_run=dry_run)
            results.append(r)
            if not r.get("ok") and not args.get("continue_on_error"):
                return _fail("Branch failed", results=results)
        return _ok("Condition branch done", taken=bool(body is step.steps), results=results)

    if dry_run:
        return _ok(f"dry:{kind}", args=args)

    if kind == "mouse":
        el = args.get("element") or {}
        hit = _click_element(el) if el else None
        if hit is not None:
            return _ok("Clicked element", result=str(hit)[:200])
        return _click_xy(int(args.get("x") or 0), int(args.get("y") or 0), str(args.get("button") or "left"))

    if kind == "key":
        return _wrap(_exec_tool("press_key", {"key": str(args.get("key") or "")}))

    if kind == "hotkey":
        keys = str(args.get("keys") or args.get("key") or "").replace("+", " ")
        return _wrap(_exec_tool("hotkey", {"keys": keys}))

    if kind == "type":
        return _wrap(_exec_tool("type_text", {"text": str(args.get("text") or "")}))

    if kind == "app":
        return _wrap(_exec_tool("open_app", {"name": str(args.get("name") or args.get("app") or "")}))

    if kind == "focus":
        name = str(args.get("app") or args.get("name") or "")
        try:
            return _wrap(_exec_tool("focus_app", {"name": name}))
        except Exception:
            return _wrap(_exec_tool("open_app", {"name": name}))

    if kind == "clipboard":
        op = str(args.get("op") or "set").lower()
        if op == "get":
            text = _read_clipboard()
            var = str(args.get("as") or "clipboard")
            variables[var] = text
            return _ok("Clipboard read", text=text[:200])
        text = str(args.get("text") or "")
        _write_clipboard(text)
        return _ok("Clipboard set")

    if kind == "browser":
        url = str(args.get("url") or args.get("site") or "")
        if not url:
            return _fail("browser step needs url")
        try:
            return _wrap(_exec_tool("browser_navigate", {"url": url}))
        except Exception:
            return _wrap(_exec_tool("open_website", {"site": url}))

    if kind == "tool":
        tool = str(args.get("tool") or args.get("name") or "")
        targs = dict(args.get("args") or {})
        # allow flat extra keys
        for k, v in args.items():
            if k not in ("tool", "name", "args"):
                targs.setdefault(k, v)
        return _wrap(_exec_tool(tool, targs))

    return _fail(f"Unknown step kind: {kind}")


def _wrap(result: Any) -> dict[str, Any]:
    # ToolResult-like
    ok = True
    msg = str(result)
    if hasattr(result, "ok"):
        ok = bool(result.ok)
        msg = getattr(result, "message", None) or getattr(result, "say", None) or msg
    elif isinstance(result, dict):
        ok = bool(result.get("ok", True))
        msg = str(result.get("message") or result.get("error") or msg)
    return _ok(msg[:300]) if ok else _fail(msg[:300])


def _read_clipboard() -> str:
    try:
        import ctypes
        from ctypes import wintypes  # noqa: F401

        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr) or ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def _write_clipboard(text: str) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        if not user32.OpenClipboard(0):
            return
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            ptr = kernel32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        pass


def replay(
    workflow: Workflow,
    *,
    variables: dict[str, Any] | None = None,
    dry_run: bool = False,
    start_index: int = 0,
    end_index: int | None = None,
) -> dict[str, Any]:
    vars_rt = dict(workflow.variables or {})
    if variables:
        vars_rt.update(variables)
    steps = list(workflow.steps or [])
    if end_index is not None:
        steps = steps[:end_index]
    steps = steps[max(0, start_index) :]
    results = []
    for i, step in enumerate(steps):
        r = run_step(step, vars_rt, dry_run=dry_run)
        results.append({"i": start_index + i, "kind": step.kind, **{k: v for k, v in r.items() if k != "results"}})
        if not r.get("ok") and not dry_run:
            return {
                "ok": False,
                "error": r.get("error") or f"Failed at step {start_index + i}",
                "failed_at": start_index + i,
                "results": results,
                "variables": vars_rt,
            }
    return {
        "ok": True,
        "message": f"Replayed {len(steps)} steps" + (" (dry)" if dry_run else ""),
        "results": results,
        "variables": vars_rt,
        "workflow_id": workflow.id,
    }
