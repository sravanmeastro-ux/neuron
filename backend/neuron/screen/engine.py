"""Screen Understanding Engine — compose capture/OCR/UIA/VLM/actions.

Enhances existing desktop automation; does not replace FastIntentRouter
or Semantic Understanding. Visual commands only.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.screen import context as screen_ctx
from neuron.screen.detect import build_snapshot
from neuron.screen.ground import ground, ordinal_pick
from neuron.screen.planner import is_visual_command, plan_from_text
from neuron.screen.types import ScreenPlan, ScreenResult, ScreenSnapshot


def _vlm_summary(snap: ScreenSnapshot, question: str = "") -> str:
    try:
        import vision_agent
        if not vision_agent or not vision_agent.is_enabled():
            return ""
        q = question or "Describe the focused window briefly: app name, main buttons, any error text."
        return (vision_agent.answer_screen(q) or "").strip()[:600]
    except Exception:
        return ""


def _click_xy(x: int, y: int) -> str:
    try:
        import actions
        return actions.click(int(x), int(y))
    except Exception:
        import pyautogui
        pyautogui.click(int(x), int(y))
        return f"Clicked at {x},{y}."


def _click_name(name: str) -> tuple[bool, str]:
    """Prefer element_resolver cascade; returns (ok, message)."""
    try:
        from neuron.brain import element_resolver
        r = element_resolver.click({"name": name})
        ok = bool(getattr(r, "success", False))
        return ok, str(r)
    except Exception as exc:
        return False, str(exc)


def observe(*, use_ocr: bool = True, use_vlm: bool = False, question: str = "") -> ScreenSnapshot:
    snap = build_snapshot(use_ocr=use_ocr, use_uia=True)
    if use_vlm:
        t0 = time.perf_counter()
        snap.vlm_summary = _vlm_summary(snap, question)
        snap.timings_ms["vlm_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    screen_ctx.remember_snapshot(snap)
    return snap


def execute_plan(plan: ScreenPlan, snap: ScreenSnapshot) -> ScreenResult:
    t0 = time.perf_counter()
    meta: dict[str, Any] = {"timings_ms": dict(snap.timings_ms)}

    if plan.action == "describe":
        app = snap.application or "unknown"
        title = snap.window_title or "(no title)"
        buttons = ", ".join(e.name for e in snap.buttons()[:8]) or "(none detected)"
        say = f"You're in {app}. Window: {title}. Visible controls: {buttons}."
        if snap.vlm_summary:
            say += " " + snap.vlm_summary[:240]
        meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return ScreenResult(ok=True, say=say, acted=True, snapshot=snap, plan=plan, meta=meta)

    if plan.action == "read":
        text = " | ".join(snap.ocr_text[:30]) or "(no OCR text)"
        if plan.needs_vlm or "error" in (plan.args.get("focus") or ""):
            vlm = snap.vlm_summary or _vlm_summary(snap, "Read any error message on screen.")
            snap.vlm_summary = vlm
            say = vlm or f"On-screen text: {text[:400]}"
        else:
            say = f"On-screen text: {text[:500]}"
        meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return ScreenResult(ok=True, say=say, acted=True, snapshot=snap, plan=plan, meta=meta)

    if plan.action == "open_tab":
        ord_word = str(plan.args.get("ordinal") or "first")
        tabs = [e for e in snap.elements if e.role == "tab"]
        el = ordinal_pick(tabs or snap.elements, ord_word)
        if not el:
            meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return ScreenResult(
                ok=False, say="I couldn't find that tab.", acted=False, snapshot=snap, plan=plan, meta=meta
            )
        msg = _click_xy(*el.center)
        screen_ctx.remember_click(el.name)
        meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return ScreenResult(
            ok=True,
            say=f"Opened tab {el.name or ord_word}. {msg}",
            acted=True,
            snapshot=snap,
            plan=plan,
            grounded=ground(el.name or ord_word, snap),
            meta=meta,
        )

    if plan.action == "scroll":
        until = str(plan.args.get("until") or "")
        direction = str(plan.args.get("direction") or "down")
        max_steps = int(plan.args.get("max_steps") or 8)
        try:
            import actions
            for step in range(max_steps):
                # Re-check OCR/UIA cheaply via name search in current snap then refresh
                g = ground(until, snap) if until else None
                if g and g.element and g.score >= 40:
                    meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    return ScreenResult(
                        ok=True,
                        say=f"Found {until!r} after scrolling.",
                        acted=True,
                        snapshot=snap,
                        plan=plan,
                        grounded=g,
                        meta=meta,
                    )
                actions.scroll(direction)
                time.sleep(0.25)
                snap = build_snapshot(use_ocr=True, use_uia=True)
                screen_ctx.remember_snapshot(snap)
            meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return ScreenResult(
                ok=False,
                say=f"Scrolled {max_steps} times but didn't find {until!r}.",
                acted=True,
                snapshot=snap,
                plan=plan,
                meta=meta,
            )
        except Exception as exc:
            return ScreenResult(ok=False, say=str(exc), acted=False, snapshot=snap, plan=plan, meta=meta)

    if plan.action == "click":
        query = str(plan.args.get("query") or "").strip()
        role_hint = str(plan.args.get("role_hint") or "")
        # 1) Ground against snapshot
        g = ground(query, snap, role_hint=role_hint)
        # 2) Prefer element_resolver (DOM→UIA→OCR) for named clicks
        if query:
            ok, msg = _click_name(query)
            if ok:
                screen_ctx.remember_click(query)
                meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                meta["path"] = "element_resolver"
                return ScreenResult(
                    ok=True, say=msg, acted=True, snapshot=snap, plan=plan, grounded=g, meta=meta
                )
        # 3) Click grounded coords
        if g.element and g.score >= 35:
            x, y = g.element.center
            msg = _click_xy(x, y)
            screen_ctx.remember_click(g.element.name)
            meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            meta["path"] = "grounded_click"
            meta["ground_score"] = g.score
            return ScreenResult(
                ok=True,
                say=f"Clicked {g.element.name or query}. {msg}",
                acted=True,
                snapshot=snap,
                plan=plan,
                grounded=g,
                meta=meta,
            )
        # 4) VLM computer_use fallback
        if plan.needs_vlm or g.score < 35:
            try:
                import vision_agent
                if vision_agent and vision_agent.is_enabled():
                    out = vision_agent.computer_use(f"click {query}")
                    meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    meta["path"] = "vlm_computer_use"
                    return ScreenResult(
                        ok=True, say=str(out), acted=True, snapshot=snap, plan=plan, grounded=g, meta=meta
                    )
            except Exception as exc:
                meta["vlm_error"] = str(exc)
        meta["action_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        alts = ", ".join(a.name for a in (g.alternatives[:3] if g else []))
        say = f"I couldn't confidently click {query!r}."
        if alts:
            say += f" Nearby: {alts}."
        return ScreenResult(ok=False, say=say, acted=False, snapshot=snap, plan=plan, grounded=g, meta=meta)

    return ScreenResult(ok=False, say="No visual action planned.", acted=False, snapshot=snap, plan=plan, meta=meta)


def handle(text: str, *, force: bool = False) -> ScreenResult | None:
    """
    Entry for visual natural-language commands.
    Returns None if not a visual command (caller continues normal routing).
    """
    if not force and not is_visual_command(text):
        return None

    plan = plan_from_text(text)
    if plan.action == "none" and not force:
        return None

    use_vlm = bool(plan.needs_vlm or plan.action in ("read", "describe"))
    # describe app can skip VLM for speed; still allow UIA
    if plan.action == "describe" and plan.args.get("mode") == "app":
        use_vlm = False

    snap = observe(use_ocr=True, use_vlm=use_vlm, question=text)
    screen_ctx.remember_snapshot(snap, query=text)

    if plan.action == "none":
        # Forced observe-only
        return ScreenResult(
            ok=True,
            say=f"I see {snap.application or 'a window'}: {snap.window_title}. "
                f"{len(snap.elements)} UI elements, {len(snap.ocr_text)} OCR lines.",
            acted=True,
            snapshot=snap,
            plan=plan,
            meta={"timings_ms": snap.timings_ms},
        )

    return execute_plan(plan, snap)


def tool_screen_understand(args: dict | None = None) -> Any:
    """ToolRegistry handler."""
    args = args or {}
    text = (args.get("request") or args.get("query") or args.get("goal") or "").strip()
    force = bool(args.get("force", True))
    result = handle(text, force=force)
    if result is None:
        from neuron.windows.result import fail
        return fail("Not a visual command.")
    from neuron.windows.result import ok, fail
    if result.ok:
        return ok(
            result.say,
            state={
                "meta": result.meta,
                "snapshot": result.snapshot.to_dict() if result.snapshot else {},
                "memory": screen_ctx.summary(),
            },
            method="screen_engine",
        )
    return fail(result.say or "Screen understanding failed.", method="screen_engine")
