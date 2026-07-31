"""Execute planned tool steps via the registry. Never plans — only runs."""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

from neuron.brain import tool_registry
from neuron.brain.normalize import normalize_args, normalize_plan
from neuron.safety import policy


class ExecutionResult:
    def __init__(self):
        self.outcomes: list[str] = []
        self.errors: list[str] = []
        self.unknown: list[str] = []
        self.failed_step: dict | None = None
        self.needs_confirm: dict | None = None
        self.steps_run: list[dict] = []


def _default_timeout() -> float:
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8"))
        return float((cfg.get("agent") or {}).get("tool_timeout_seconds", 45) or 45)
    except Exception:
        return 45.0


def _run_tool_in_thread(fn, args: dict):
    """Worker entry: COM/UIA must be initialized per-thread on Windows."""
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread(debug=False):
            return fn(args)
    except Exception:
        # If uiautomation isn't available, still try the tool (non-UIA paths).
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
            try:
                return fn(args)
            finally:
                ctypes.windll.ole32.CoUninitialize()
        except Exception:
            return fn(args)


def _run_with_timeout(fn, args: dict, timeout: float):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_run_tool_in_thread, fn, args)
        return fut.result(timeout=timeout)


def execute_plan(plan: dict | list | None, *, confirmed: bool = False, timeout: float | None = None) -> ExecutionResult:
    result = ExecutionResult()
    plan = normalize_plan(plan)
    steps = plan.get("steps") or []
    timeout = float(timeout if timeout is not None else _default_timeout())

    for step in steps:
        name = (step.get("action") or "").strip()
        args = normalize_args(step.get("args") or {})
        step = {"action": name, "args": args}
        if not name:
            continue
        try:
            from neuron.speech import interrupt as interrupt_mod
            if interrupt_mod.interrupted():
                msg = "Interrupted."
                result.errors.append(msg)
                result.failed_step = step
                result.steps_run.append({
                    "action": name, "args": args, "ok": False, "out": msg, "interrupted": True,
                })
                print(f"[executor] interrupted before {name}", flush=True)
                break
        except Exception:
            pass
        spec = tool_registry.get(name)
        if not spec:
            msg = f"Unknown tool: {name} (only registered tools may execute)"
            result.unknown.append(name)
            result.errors.append(msg)
            result.failed_step = step
            result.steps_run.append({
                "action": name, "args": args, "ok": False, "out": msg,
            })
            print(f"[executor] unknown tool (rejected): {name}", flush=True)
            break

        ok_args, arg_err, coerced = tool_registry.validate_args(name, args)
        if not ok_args:
            result.errors.append(arg_err or f"Invalid args for {name}")
            result.failed_step = step
            result.steps_run.append({
                "action": name, "args": args, "ok": False, "out": arg_err,
            })
            print(f"[executor] invalid args {name}: {arg_err}", flush=True)
            break
        args = coerced
        step = {"action": spec.name, "args": args}
        name = spec.name

        allowed, reason = policy.allow(name, args, confirmed=confirmed or bool(args.get("confirmed")))
        if not allowed:
            tier = "blocked"
            try:
                tier = policy.classify(name, args).tier
            except Exception:
                pass
            if tier == "blocked" or (
                not policy.requires_confirm(name, args) and "blocked" in (reason or "").lower()
            ):
                result.errors.append(reason or f"Blocked: {name}")
                result.failed_step = step
                print(f"[executor] BLOCKED {name}: {reason}", flush=True)
                break
            if policy.requires_confirm(name, args) or "confirm" in (reason or "").lower():
                from neuron.safety import confirm as confirm_mod
                payload = confirm_mod.request_confirm(name, args, reason)
                result.needs_confirm = payload
                result.errors.append(reason or f"Confirmation required for {name}")
                result.failed_step = step
                print(f"[executor] confirm required ({tier}): {name}", flush=True)
                break
            result.errors.append(reason or f"Blocked: {name}")
            result.failed_step = step
            print(f"[executor] blocked: {name} — {reason}", flush=True)
            break

        t0 = time.time()
        print(f"[executor] run {name}({args})", flush=True)
        try:
            out = _run_with_timeout(spec.handler, args, timeout)
            elapsed = time.time() - t0
            # Phase 2 ToolResult → structured log + spoken string
            structured = None
            if hasattr(out, "to_dict") and callable(out.to_dict):
                try:
                    structured = out.to_dict()
                except Exception:
                    structured = None
                if hasattr(out, "success") and not bool(out.success):
                    err = getattr(out, "error", None) or str(out)
                    result.errors.append(err)
                    result.failed_step = step
                    result.steps_run.append({
                        "action": name, "args": args, "ok": False,
                        "out": err, "ms": int(elapsed * 1000), "result": structured,
                    })
                    print(f"[executor] FAIL {name}: {err}", flush=True)
                    try:
                        from neuron.memory.store import log_tool_run
                        log_tool_run(name, args, ok=False, detail=err[:300])
                    except Exception:
                        pass
                    break
                out = str(out)
            entry = {
                "action": name,
                "args": args,
                "ok": True,
                "out": str(out)[:500] if out is not None else "",
                "ms": int(elapsed * 1000),
            }
            if structured is not None:
                entry["result"] = structured
            result.steps_run.append(entry)
            if isinstance(out, str) and out.strip():
                result.outcomes.append(out.strip())
            print(f"[executor] ok {name} in {elapsed:.2f}s", flush=True)
            try:
                from neuron.memory.store import log_tool_run
                log_tool_run(name, args, ok=True, detail=str(out)[:300] if out else "")
            except Exception:
                pass
        except concurrent.futures.TimeoutError:
            msg = f"Tool {name} timed out after {timeout:.0f}s"
            result.errors.append(msg)
            result.failed_step = step
            result.steps_run.append({"action": name, "args": args, "ok": False, "out": msg})
            print(f"[executor] TIMEOUT {name}", flush=True)
            try:
                from neuron.memory.store import log_tool_run
                log_tool_run(name, args, ok=False, detail=msg)
            except Exception:
                pass
            break
        except Exception as exc:
            result.errors.append(str(exc))
            result.failed_step = step
            result.steps_run.append({"action": name, "args": args, "ok": False, "out": str(exc)})
            print(f"[executor] FAIL {name}: {exc}", flush=True)
            try:
                from neuron.memory.store import log_tool_run
                log_tool_run(name, args, ok=False, detail=str(exc)[:300])
            except Exception:
                pass
            break
    return result
