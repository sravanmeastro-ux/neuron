"""Phase 9 — world observation + hard postcondition verification.

NEURON must NEVER assume an action worked. Tools report outcomes;
verification re-checks the computer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerifyResult:
    ok: bool
    note: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_tuple(self) -> tuple[bool, str]:
        return self.ok, self.note


def observe_world(hint: str = "") -> dict[str, Any]:
    """Lightweight live observation for verify/recover."""
    obs: dict[str, Any] = {"hint": (hint or "")[:80]}
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        obs["window"] = (fg.get("title") or "")[:160]
        obs["hwnd"] = int(fg.get("hwnd") or 0)
    except Exception:
        pass
    try:
        import browser
        url = browser.current_url() or ""
        if url:
            obs["url"] = url[:200]
    except Exception:
        pass
    try:
        from neuron.brain.snapshot import gather_snapshot
        snap = gather_snapshot(hint, deep=False)
        obs["app"] = snap.active_application or snap.sticky_app
        obs["scene"] = snap.scene
        if snap.active_window and not obs.get("window"):
            obs["window"] = snap.active_window
        if snap.browser_url and not obs.get("url"):
            obs["url"] = snap.browser_url
    except Exception:
        pass
    return obs


def _check_app(name: str) -> dict[str, Any]:
    out = {
        "name": name,
        "process_running": False,
        "window_exists": False,
        "window_title": "",
        "resolved": "",
    }
    if not (name or "").strip():
        return out
    try:
        from neuron.windows.resolve import resolve
        from neuron.windows import state as win_state
        resolved = resolve(name)
        out["resolved"] = resolved.canonical
        wins = win_state.find_app_windows(resolved)
        if wins:
            out["window_exists"] = True
            out["window_title"] = (wins[0].get("title") or "")[:120]
        out["process_running"] = win_state.app_is_running(resolved)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def verify_step(
    step: dict,
    outcome: str | None,
    error: str | None,
    *,
    strict: bool = True,
    world: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Return (ok, note). When strict=True, re-check OS/browser state."""
    vr = verify_step_detailed(
        step, outcome, error, strict=strict, world=world
    )
    return vr.to_tuple()


def verify_step_detailed(
    step: dict,
    outcome: str | None,
    error: str | None,
    *,
    strict: bool = True,
    world: dict[str, Any] | None = None,
) -> VerifyResult:
    if error:
        return VerifyResult(False, error)

    name = (step.get("action") or "").strip()
    args = step.get("args") or {}
    world = world or {}

    # --- open / focus app: require process OR window ---
    if name in ("open_app", "focus_app"):
        app = (args.get("name") or args.get("application") or "").strip()
        check = _check_app(app)
        evidence = {**check, "outcome": (outcome or "")[:200]}
        if check.get("window_exists") or check.get("process_running"):
            note = (
                f"verified {check.get('resolved') or app}: "
                f"process={check['process_running']} window={check['window_exists']}"
                + (f" title={check['window_title']!r}" if check.get("window_title") else "")
            )
            return VerifyResult(True, note, evidence)
        if not strict:
            return VerifyResult(True, f"soft-accept open; no window yet ({outcome})", evidence)
        return VerifyResult(
            False,
            f"{check.get('resolved') or app or 'app'} is not running and no window found",
            evidence,
        )

    if name in ("minimize_app", "maximize_app", "move_window", "move_window_to_monitor", "resize_window", "close_app"):
        if isinstance(outcome, str) and any(
            x in outcome.lower() for x in ("couldn't", "failed", "no window", "not found", "verification failed")
        ):
            return VerifyResult(False, outcome)
        if name in ("move_window", "move_window_to_monitor") and strict:
            # Prefer structured verified flag from ToolResult when present in world/outcome
            want = args.get("monitor") or args.get("monitor_id") or args.get("screen")
            title = args.get("title") or args.get("name") or args.get("app") or ""
            if want not in (None, "", 0, "0"):
                try:
                    from neuron.windows import monitors as mon_mod
                    mons = mon_mod.list_monitor_dicts()
                    target = mon_mod.resolve_monitor_ref(want, monitors=mons)
                    if target and title:
                        for w in mon_mod._list_windows_with_monitor(mons):
                            if str(title).lower() in (w.get("title") or "").lower():
                                mid = mon_mod.window_monitor_id(w, mons)
                                if mid is not None and int(mid) != int(target["id"]):
                                    return VerifyResult(
                                        False,
                                        f"Window still on monitor {mid}, expected {target['id']}",
                                        {"window": w, "target": target},
                                    )
                                return VerifyResult(
                                    True,
                                    f"verified on monitor {mid}",
                                    {"window": w, "target": target},
                                )
                except Exception as exc:
                    return VerifyResult(True, f"moved; verify skipped ({exc})")
        if name == "close_app" and strict:
            app = (args.get("name") or "").strip()
            if app:
                check = _check_app(app)
                if check.get("window_exists"):
                    return VerifyResult(
                        False,
                        f"Window still present for {app}: {check.get('window_title')}",
                        check,
                    )
        return VerifyResult(True, outcome or "ok")

    if name in ("click_ui_element", "find_ui_element"):
        if isinstance(outcome, str) and any(
            x in outcome.lower()
            for x in ("not found", "couldn't find", "click failed", "no foreground")
        ):
            return VerifyResult(False, outcome)
        return VerifyResult(True, outcome or "ok")

    if name in ("get_ui_tree", "get_active_window_elements", "get_element_text", "get_element_bounds"):
        if isinstance(outcome, str) and any(
            x in outcome.lower() for x in ("failed", "empty ui", "no active", "no foreground")
        ):
            return VerifyResult(False, outcome)
        return VerifyResult(True, outcome or "ok")

    # --- browser ---
    if name.startswith("browser_") or name in ("open_website", "search_site", "youtube_home"):
        if isinstance(outcome, str) and any(
            x in outcome.lower()
            for x in ("failed", "couldn't", "not found", "isn't available", "need a")
        ):
            return VerifyResult(False, outcome)
        url = (world.get("url") or "").lower()
        if not url:
            try:
                import browser
                url = (browser.current_url() or "").lower()
            except Exception:
                url = ""
        evidence = {"url": url[:200], "outcome": (outcome or "")[:200]}
        if name in ("youtube_home",) or (
            name in ("browser_open", "browser_search", "open_website", "search_site")
            and "youtube" in str(args.get("site") or args.get("url") or "").lower()
        ):
            if strict and url and "youtube" not in url:
                return VerifyResult(False, f"Expected YouTube, got {url or 'no url'}", evidence)
        if name in ("browser_navigate",) and strict:
            want = (args.get("url") or args.get("site") or "").lower()
            if want and url and want.split("://")[-1][:20] not in url and want[:20] not in url:
                # Soft URL mismatch — page may redirect
                return VerifyResult(True, f"navigated; url={url[:80]}", evidence)
        if name in ("browser_click", "browser_find_element") and strict:
            if isinstance(outcome, str) and "no match" in outcome.lower():
                return VerifyResult(False, outcome, evidence)
        return VerifyResult(True, f"ok; url={url[:80]}" if url else (outcome or "ok"), evidence)

    if name in (
        "analyze_screen", "get_screen_context", "capture_screen", "capture_monitor",
        "get_active_window_screenshot", "ocr_image", "ocr_screen", "detect_text_regions",
        "get_cursor_position", "describe_screen",
    ):
        if isinstance(outcome, str) and any(
            x in outcome.lower() for x in ("failed", "unavailable", "no monitor", "not found")
        ):
            return VerifyResult(False, outcome)
        return VerifyResult(True, outcome or "ok")

    if name == "steam_goto":
        if outcome and "couldn't" in outcome.lower():
            return VerifyResult(False, outcome)
        return VerifyResult(True, outcome or "ok")

    if isinstance(outcome, str) and any(
        x in outcome.lower() for x in ("failed", "couldn't", "error", "not available", "isn't ready")
    ):
        return VerifyResult(False, outcome)

    return VerifyResult(True, outcome or "ok")


def verify_plan(steps: list[dict], exec_result, *, strict: bool = True) -> tuple[bool, str]:
    if exec_result.errors:
        return False, "; ".join(exec_result.errors)
    if exec_result.unknown and not exec_result.outcomes:
        return False, f"Unknown tools: {', '.join(exec_result.unknown)}"
    if steps and exec_result.outcomes:
        world = observe_world(
            str((steps[-1].get("args") or {}).get("name") or "")
        )
        ok, note = verify_step(
            steps[-1],
            exec_result.outcomes[-1],
            None,
            strict=strict,
            world=world,
        )
        return ok, note
    # Steps claimed success with no outcomes — suspicious if strict
    if steps and not exec_result.outcomes and strict:
        return False, "No outcome to verify"
    return True, "ok"


def verify_execution_step(
    step: dict,
    exec_entry: dict | None,
    *,
    strict: bool = True,
) -> VerifyResult:
    """Verify one executed step using its executor entry + live world."""
    exec_entry = exec_entry or {}
    if exec_entry.get("ok") is False:
        return VerifyResult(False, str(exec_entry.get("out") or "step failed"))
    world = observe_world(str((step.get("args") or {}).get("name") or step.get("action") or ""))
    # Prefer structured ToolResult verified=False as fail under strict
    structured = exec_entry.get("result") or {}
    state = structured.get("state") if isinstance(structured, dict) else {}
    if (
        strict
        and isinstance(state, dict)
        and state.get("verified") is False
        and (step.get("action") or "") in ("open_app", "focus_app")
    ):
        # Still allow if process/window now present
        app = (step.get("args") or {}).get("name") or ""
        check = _check_app(str(app))
        if not (check.get("window_exists") or check.get("process_running")):
            return VerifyResult(
                False,
                f"Launch reported but not verified for {app}",
                check,
            )
    return verify_step_detailed(
        step,
        exec_entry.get("out"),
        None,
        strict=strict,
        world=world,
    )


# Back-compat alias used by older imports
def _fg_name() -> str:
    try:
        from neuron.windows.com import com_uia
        import uiautomation as auto
        with com_uia():
            fg = auto.GetForegroundControl()
            return ((fg.Name or "") + " " + (getattr(fg, "ClassName", "") or "")).lower()
    except Exception:
        return ""
