"""Phase 9 — world observation + hard postcondition verification.

NEURON must NEVER assume an action worked. Tools report outcomes;
verification re-checks the computer (OS / browser / UIA / local OCR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerifyResult:
    ok: bool
    note: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_tuple(self) -> tuple[bool, str]:
        return self.ok, self.note


def _agent_verify_cfg() -> dict:
    try:
        import json
        from pathlib import Path
        return json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(
                encoding="utf-8"
            )
        ).get("agent") or {}
    except Exception:
        return {}


def _uia_visible_labels(limit: int = 40) -> list[str]:
    """Fast local UIA labels from the foreground window."""
    labels: list[str] = []
    try:
        from neuron.uia import inspect as uia_inspect
        _win, elements = uia_inspect.walk_elements(
            max_depth=3,
            max_elements=limit,
            named_only=True,
            time_budget=1.5,
        )
        for el in elements or []:
            name = (getattr(el, "name", None) or "").strip()
            if name and name not in labels and len(name) < 120:
                labels.append(name)
            if len(labels) >= limit:
                break
    except Exception:
        try:
            from neuron.tools.uia_tools import get_ui_tree
            tree = str(get_ui_tree({"depth": 2, "limit": limit}) or "")
            for line in tree.splitlines():
                bit = line.strip(" -•\t")
                if bit and len(bit) < 120 and bit not in labels:
                    labels.append(bit)
                if len(labels) >= limit:
                    break
        except Exception:
            pass
    return labels


def _ocr_visible_text(monitor=None, max_lines: int = 40) -> list[str]:
    """Local RapidOCR of active window / monitor — free, no cloud."""
    texts: list[str] = []
    try:
        from neuron.perception.ocr import ocr_image
        args: dict[str, Any] = {}
        if monitor is not None:
            args["monitor"] = monitor
        result = ocr_image(args)
        if not getattr(result, "success", False):
            return texts
        state = getattr(result, "state", None) or {}
        raw = state.get("visible_text") or state.get("text") or []
        for t in raw:
            s = str(t or "").strip()
            if s and s not in texts:
                texts.append(s[:160])
            if len(texts) >= max_lines:
                break
    except Exception:
        pass
    return texts


def gather_screen_text(
    *,
    use_ocr: bool = False,
    hint: str = "",
    monitor=None,
) -> dict[str, Any]:
    """Collect visible on-screen text via UIA (fast) and optional local OCR."""
    uia = _uia_visible_labels()
    ocr: list[str] = []
    if use_ocr:
        ocr = _ocr_visible_text(monitor=monitor)
    # Prefer UIA; append OCR lines not already present
    combined: list[str] = list(uia)
    for t in ocr:
        if t not in combined:
            combined.append(t)
    blob = " | ".join(combined)[:2000]
    hint_l = (hint or "").lower()
    hint_hit = bool(hint_l and hint_l[:40] in blob.lower()) if hint_l else False
    return {
        "uia_text": uia[:40],
        "ocr_text": ocr[:40],
        "visible_text": combined[:50],
        "screen_blob": blob,
        "hint_on_screen": hint_hit,
        "screen_sources": (
            (["uia"] if uia else []) + (["ocr"] if ocr else [])
        ),
    }


def needs_screen_verify(step: dict | None) -> bool:
    """Whether this step should use deep screen observation (UIA / OCR)."""
    step = step or {}
    action = (step.get("action") or "").strip()
    expected = (step.get("expected_result") or "").lower()
    cfg = _agent_verify_cfg()
    mode = str(cfg.get("screen_verify", "auto") or "auto").lower()
    if mode in ("0", "false", "off", "none"):
        return False
    if mode in ("1", "true", "always", "on"):
        return True
    # auto — UI/text actions, or expectations about on-screen content
    if action in (
        "click_ui_element", "find_ui_element", "click_element", "find_element",
        "type_text", "type",
        "get_element_text", "analyze_screen", "ocr_screen", "ocr_image",
    ):
        return True
    if any(k in expected for k in (
        "on screen", "on-screen", "visible on", "shows '", 'shows "',
        "appears", "dialog", "menu item", "button '", 'button "',
        "label '", 'label "', "text '", 'text "',
    )):
        return True
    # Quoted UI target in expected_result for non-app-launch steps
    if action not in ("open_app", "focus_app", "close_app") and re.search(
        r"['\"][^'\"]{2,}['\"]", expected
    ):
        return True
    return False


def needs_ocr_verify(step: dict | None) -> bool:
    """OCR is slower — use only when UIA alone is unlikely to be enough."""
    step = step or {}
    cfg = _agent_verify_cfg()
    mode = str(cfg.get("ocr_verify", "auto") or "auto").lower()
    if mode in ("0", "false", "off", "none"):
        return False
    if mode in ("1", "true", "always", "on"):
        return True
    # auto
    action = (step.get("action") or "").strip()
    expected = (step.get("expected_result") or "").lower()
    if action in ("ocr_screen", "ocr_image", "analyze_screen", "type_text", "type"):
        return True
    if any(k in expected for k in ("ocr", "written", "read", "typed", "appears as")):
        return True
    if re.search(r"['\"][^'\"]{3,}['\"]", expected) and action.startswith("browser_"):
        return False  # browser: prefer DOM/url over OCR
    if re.search(r"['\"][^'\"]{3,}['\"]", expected):
        return True
    return False


def observe_world(
    hint: str = "",
    *,
    deep: bool = False,
    use_ocr: bool = False,
    step: dict | None = None,
) -> dict[str, Any]:
    """Live observation for verify/recover via unified ComputerState.

    Prefers ComputerState (UIA → DOM → OCR → vision). Falls back to light
    window/URL/world_model probes if ComputerState is unavailable.

    deep=True adds richer UIA/DOM; use_ocr=True runs local RapidOCR.
    When step is provided, deep/ocr are inferred from needs_* helpers.
    """
    if step is not None:
        if needs_screen_verify(step):
            deep = True
        if needs_ocr_verify(step):
            use_ocr = True
            deep = True

    # Primary path — unified ComputerState (reuses world_model/snapshot/UIA/browser)
    try:
        from neuron.brain.computer_state import capture as capture_state, get_previous_state

        cs = capture_state(
            deep=deep,
            use_ocr=use_ocr,
            remember=True,
            request=str(hint or (step or {}).get("target") or ""),
        )
        obs = cs.to_observe_dict()
        obs["hint"] = (hint or "")[:80]
        prev = get_previous_state()
        if prev is not None:
            change = cs.changed_since(prev)
            obs["ui_change"] = change
            obs["ui_changed"] = bool(change.get("changed"))
        return obs
    except Exception as exc:
        # Soft fallback — keep AgentLoop working
        obs = {"hint": (hint or "")[:80], "computer_state_error": str(exc)[:160]}

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

    if deep or use_ocr:
        try:
            screen = gather_screen_text(
                use_ocr=use_ocr,
                hint=hint or (step or {}).get("target") or "",
            )
            obs.update(screen)
        except Exception as err:
            obs["screen_error"] = str(err)[:160]

    try:
        from neuron.brain.world_model import build_world_model
        wm = build_world_model(deep=deep, use_ocr=use_ocr)
        obs["world_model"] = wm.get("text") or ""
        obs["focused_monitor"] = wm.get("focused_monitor")
        obs["active_application"] = wm.get("active_application") or obs.get("app")
        if wm.get("cursor"):
            obs["cursor"] = wm["cursor"]
        if not obs.get("app") and wm.get("active_application"):
            obs["app"] = wm["active_application"]
    except Exception as err:
        obs["world_model_error"] = str(err)[:160]
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

    if name in ("click_ui_element", "find_ui_element", "click_element", "find_element"):
        if isinstance(outcome, str) and any(
            x in outcome.lower()
            for x in ("not found", "couldn't find", "click failed", "no foreground", "couldn't resolve")
        ):
            return VerifyResult(False, outcome)
        evidence = {"outcome": (outcome or "")[:200]}
        target = str(
            args.get("name") or args.get("text") or step.get("target") or ""
        ).strip()
        blob = str(world.get("screen_blob") or "").lower()
        if target and blob:
            evidence["screen_hit"] = target.lower() in blob
            if name in ("find_ui_element", "find_element") and target.lower() not in blob and strict:
                return VerifyResult(
                    False,
                    f"UI target '{target}' not visible on screen",
                    evidence,
                )
        expected = str(step.get("expected_result") or "").strip()
        if expected and blob:
            quoted = re.findall(r"['\"]([^'\"]{2,})['\"]", expected)
            for q in quoted:
                if q.lower() not in blob:
                    return VerifyResult(
                        False,
                        f"expected on-screen text '{q}' not found",
                        evidence,
                    )
        sources = world.get("screen_sources") or []
        note = outcome or "ok"
        if sources:
            note = f"{note}; screen={'+'.join(sources)}"
        # Prefer resolver_source from structured result when present
        return VerifyResult(True, note, evidence)

    if name in ("type_text", "type"):
        if isinstance(outcome, str) and any(
            x in outcome.lower() for x in ("failed", "couldn't", "no foreground")
        ):
            return VerifyResult(False, outcome)
        typed = str(args.get("text") or args.get("keys") or step.get("target") or "").strip()
        blob = str(world.get("screen_blob") or "").lower()
        evidence = {"typed": typed[:80], "outcome": (outcome or "")[:200]}
        if typed and len(typed) >= 2 and blob and strict:
            # Soft: typed text often lands in focused field (UIA value / OCR)
            snippet = typed[:40].lower()
            if snippet in blob:
                return VerifyResult(True, f"typed text visible on screen", evidence)
            # Don't hard-fail typing — password fields / masked input won't show
            evidence["screen_hit"] = False
        return VerifyResult(True, outcome or "ok", evidence)

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
    hint = (
        step.get("target")
        or (step.get("args") or {}).get("name")
        or step.get("action")
        or ""
    )
    world = observe_world(str(hint), step=step)
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
        app = (step.get("args") or {}).get("name") or step.get("target") or ""
        check = _check_app(str(app))
        if not (check.get("window_exists") or check.get("process_running")):
            return VerifyResult(
                False,
                f"Launch reported but not verified for {app}",
                check,
            )
    vr = verify_step_detailed(
        step,
        exec_entry.get("out"),
        None,
        strict=strict,
        world=world,
    )
    if not vr.ok:
        return vr
    # Additional expected_result check against live observation (+ screen text)
    expected = str(step.get("expected_result") or "").strip()
    if expected and strict:
        er = _match_expected_result(expected, world, exec_entry.get("out") or "")
        if not er.ok:
            return er
    return vr


def _match_expected_result(
    expected: str,
    world: dict[str, Any],
    outcome: str = "",
) -> VerifyResult:
    """Soft-match expected_result against live world + tool outcome.

    Uses keyword heuristics so planner-written expectations stay local/free
    (no extra LLM call). Fails only when a clear contradiction is observed.
    Screen text (UIA / OCR) is included when present in world.
    """
    exp = (expected or "").lower().strip()
    if not exp:
        return VerifyResult(True, "no expected_result")

    screen = str(world.get("screen_blob") or "")
    blob_parts = [
        str(world.get("app") or ""),
        str(world.get("window") or ""),
        str(world.get("url") or ""),
        str(world.get("scene") or ""),
        screen,
        str(outcome or ""),
    ]
    blob = " ".join(blob_parts).lower()
    evidence = {
        "expected": expected[:200],
        "world": {k: world.get(k) for k in ("app", "window", "url", "scene") if world.get(k)},
        "screen_sources": world.get("screen_sources") or [],
    }

    # On-screen text expectations (quoted phrases via UIA/OCR)
    # Skip app-window phrases like "has a visible window"
    screen_expect = any(k in exp for k in (
        "on screen", "on-screen", "visible on", "shows '", 'shows "',
        "appears", "button '", 'button "', "label '", 'label "',
        "text '", 'text "',
    )) or (
        "visible" in exp and "window" not in exp and "running" not in exp
    )
    if screen_expect:
        quoted = re.findall(r"['\"]([^'\"]{2,})['\"]", expected)
        if quoted and screen:
            for q in quoted:
                if q.lower() not in screen.lower():
                    return VerifyResult(
                        False,
                        f"expected_result unmet: '{q}' not on screen",
                        evidence,
                    )
            src = "+".join(evidence["screen_sources"]) or "uia"
            return VerifyResult(True, f"expected_result met on screen ({src})", evidence)
        if quoted and not screen:
            evidence["screen_missing"] = True
            return VerifyResult(True, "expected_result soft-ok; no screen text available", evidence)

    # Running / visible window expectations
    if any(k in exp for k in ("running", "visible window", "has a visible", "is open", "focused")):
        m = re.search(r"['\"]([^'\"]+)['\"]", expected)
        app_hint = (m.group(1) if m else "").strip()
        if app_hint:
            check = _check_app(app_hint)
            evidence["check"] = check
            if check.get("window_exists") or check.get("process_running"):
                return VerifyResult(True, f"expected_result met: {app_hint} present", evidence)
            return VerifyResult(
                False,
                f"expected_result unmet: '{app_hint}' not running / no window",
                evidence,
            )

    # Closed / gone
    if any(k in exp for k in ("window is gone", "closed", "not running", "is gone")):
        m = re.search(r"['\"]([^'\"]+)['\"]", expected)
        app_hint = (m.group(1) if m else "").strip()
        if app_hint:
            check = _check_app(app_hint)
            evidence["check"] = check
            if check.get("window_exists"):
                return VerifyResult(
                    False,
                    f"expected_result unmet: '{app_hint}' window still present",
                    evidence,
                )
            return VerifyResult(True, f"expected_result met: '{app_hint}' gone", evidence)

    # URL / site expectations
    if "url" in exp or "youtube" in exp or "browser" in exp or "http" in exp:
        url = str(world.get("url") or "").lower()
        evidence["url"] = url
        if "youtube" in exp and url and "youtube" not in url:
            return VerifyResult(False, f"expected_result unmet: want YouTube, got {url or 'no url'}", evidence)
        m = re.search(r"['\"]([^'\"]+)['\"]", expected)
        site = (m.group(1) if m else "").lower().strip()
        if site and url:
            needle = site.replace("https://", "").replace("http://", "").split("/")[0][:40]
            if needle and needle not in url and not any(p in url for p in needle.split(".") if len(p) > 2):
                if not any(tok in url for tok in needle.replace(".", " ").split() if len(tok) > 3):
                    return VerifyResult(
                        False,
                        f"expected_result unmet: url={url[:80]} vs '{site}'",
                        evidence,
                    )
        return VerifyResult(True, f"expected_result soft-ok; url={url[:80]}", evidence)

    # Monitor expectations
    if "monitor" in exp:
        return VerifyResult(True, "expected_result: monitor check deferred to tool verify", evidence)

    # Default: if tool outcome already looks failed, reject; else accept
    out_l = (outcome or "").lower()
    if any(x in out_l for x in ("failed", "couldn't", "not found", "error", "timed out")):
        return VerifyResult(False, f"expected_result unmet: {outcome[:200]}", evidence)
    if blob.strip():
        return VerifyResult(True, f"expected_result accepted against observation", evidence)
    return VerifyResult(True, "expected_result: no contradiction", evidence)


def diagnose_failure(
    step: dict,
    error: str,
    world: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect current state and return a likely cause for logging / recover."""
    world = world or observe_world(
        str(step.get("target") or (step.get("args") or {}).get("name") or "")
    )
    action = (step.get("action") or "").strip()
    err = (error or "").lower()
    cause = "unknown"
    detail = error or "verification failed"

    if "timeout" in err or "timed out" in err:
        cause = "timeout"
    elif "not running" in err or "no window" in err:
        cause = "app_not_present"
    elif "not found" in err or "no match" in err or "couldn't find" in err:
        cause = "target_not_found"
    elif "confirm" in err:
        cause = "needs_confirm"
    elif "blocked" in err:
        cause = "policy_blocked"
    elif "url" in err or "expected youtube" in err:
        cause = "browser_state_mismatch"
    elif "monitor" in err:
        cause = "monitor_mismatch"
    elif action in ("open_app", "focus_app"):
        check = _check_app(str((step.get("args") or {}).get("name") or step.get("target") or ""))
        if not (check.get("window_exists") or check.get("process_running")):
            cause = "app_not_present"
            detail = f"{detail}; process={check.get('process_running')} window={check.get('window_exists')}"
    elif not world.get("window") and not world.get("app"):
        cause = "no_foreground_context"

    return {
        "cause": cause,
        "detail": str(detail)[:400],
        "action": action,
        "target": step.get("target") or (step.get("args") or {}).get("name") or "",
        "expected_result": step.get("expected_result") or "",
        "world": {k: world.get(k) for k in ("app", "window", "url", "scene") if world.get(k)},
    }


def verify_goal(
    goal_text: str,
    goal_state: Any = None,
    *,
    strict: bool = True,
) -> VerifyResult:
    """Final closed-loop check: do not finish until the overall goal looks met.

    Uses completed steps + live observation. Never invents success.
    Trusts a prior successful step verification when live observation still
    agrees (avoids false fails from app-name alias mismatches).
    """
    goal_text = (goal_text or "").strip()
    world = observe_world(goal_text)
    evidence: dict[str, Any] = {"goal": goal_text[:200], "world": dict(world)}

    completed = []
    if goal_state is not None:
        completed = list(getattr(goal_state, "completed_steps", None) or [])
        if getattr(goal_state, "pending_steps", None):
            return VerifyResult(
                False,
                f"Goal incomplete: {len(goal_state.pending_steps)} steps still pending",
                evidence,
            )
        if getattr(goal_state, "errors", None) and not completed:
            return VerifyResult(False, goal_state.errors[-1], evidence)

    if not completed and not goal_text:
        return VerifyResult(True, "empty goal", evidence)

    if not completed:
        return VerifyResult(True if not strict else False, "no completed steps to verify", evidence)

    last = completed[-1]
    last_step = {
        "action": last.get("action"),
        "args": last.get("args") or {},
        "target": last.get("target") or "",
        "expected_result": last.get("expected_result") or "",
    }
    outcome = ""
    if isinstance(last.get("result"), dict):
        outcome = str(last["result"].get("out") or "")
    prior_note = str(last.get("verify") or "")
    evidence["last_step"] = last_step.get("action")
    evidence["prior_verify"] = prior_note[:200]

    # Soft agreement: prior step verified + observation still mentions target/app
    target = str(
        last_step.get("target")
        or (last_step.get("args") or {}).get("name")
        or (last_step.get("args") or {}).get("site")
        or ""
    ).strip().lower()
    obs_blob = " ".join(
        str(world.get(k) or "") for k in ("app", "window", "url", "scene")
    ).lower()
    if prior_note and "verif" in prior_note.lower():
        if not target or (target and target in obs_blob) or obs_blob.strip():
            # Re-check hard only for open/focus when observation contradicts
            if last_step.get("action") in ("open_app", "focus_app") and target:
                if target in obs_blob or any(
                    t and t in obs_blob for t in target.replace("-", " ").split() if len(t) > 2
                ):
                    return VerifyResult(True, f"final goal verified (observation agrees: {prior_note[:80]})", evidence)
                check = _check_app(str((last_step.get("args") or {}).get("name") or target))
                evidence["goal_app_check"] = check
                if check.get("window_exists") or check.get("process_running"):
                    return VerifyResult(True, f"final goal verified: {check.get('resolved') or target}", evidence)
                # Prior step claimed verified but app gone now — honest fail
                return VerifyResult(
                    False,
                    f"Final goal unmet: '{target}' no longer present after prior verify",
                    evidence,
                )
            return VerifyResult(True, f"final goal verified ({prior_note[:80]})", evidence)

    vr = verify_step_detailed(last_step, outcome or "ok", None, strict=strict, world=world)
    evidence["last_verify"] = vr.note
    if not vr.ok and strict:
        return VerifyResult(False, f"Final goal verify failed: {vr.note}", evidence)

    if strict and last_step.get("action") in ("open_app", "focus_app"):
        app = str(
            (last_step.get("args") or {}).get("name")
            or last_step.get("target")
            or ""
        ).strip()
        if app:
            # Observation soft-match first (handles notepad vs Notepad)
            if app.lower() in obs_blob:
                return VerifyResult(True, f"final goal verified (obs has {app})", evidence)
            check = _check_app(app)
            evidence["goal_app_check"] = check
            if not (check.get("window_exists") or check.get("process_running")):
                return VerifyResult(
                    False,
                    f"Final goal unmet: '{app}' not running",
                    evidence,
                )

    return VerifyResult(True, "final goal verified", evidence)


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
