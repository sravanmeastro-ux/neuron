"""UI Grounding pipeline — Intent → Focus → Shot → Detect → Ground → Click → Observe → Verify."""

from __future__ import annotations

import time
from typing import Any

from neuron.ui_grounding import capture as cap
from neuron.ui_grounding.detect_ui import detect_elements, elements_as_dicts
from neuron.ui_grounding.match import ground_target, match_near_point
from neuron.ui_grounding.types import GroundingResult
from neuron.ui_grounding.verify import verify_click_result


def _focus_app(app: str | None) -> dict[str, Any]:
    if not app:
        return {"skipped": True}
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        r = tool_registry.execute("focus_app", {"name": app}, confirmed=True, skip_policy=True)
        return {"ok": True, "result": str(r)[:200]}
    except Exception as exc:
        try:
            from neuron.windows import apps as wapps
            return {"ok": True, "result": str(wapps.focus_app({"name": app}))[:200]}
        except Exception as exc2:
            return {"ok": False, "error": f"{exc}; {exc2}"}


def _scroll(direction: str = "down", clicks: int = 3) -> None:
    try:
        from neuron.computer_use import primitives
        primitives.scroll(direction, clicks=clicks)
    except Exception:
        try:
            import pyautogui
            pyautogui.scroll(-clicks if direction == "down" else clicks)
        except Exception:
            pass


def _do_click(x: int, y: int) -> dict[str, Any]:
    try:
        from neuron.computer_use import primitives
        token = primitives.allow_raw_click(True)
        try:
            r = primitives.click_xy(x, y, force=True)
            return {"ok": bool(getattr(r, "success", True)), "msg": str(r)}
        finally:
            primitives.reset_raw_click(token)
    except Exception:
        import pyautogui
        pyautogui.click(int(x), int(y))
        return {"ok": True, "msg": f"Clicked ({x},{y})"}


def run_pipeline(
    intent: str,
    *,
    target: str = "",
    app: str | None = None,
    monitor_id: int | None = None,
    min_confidence: float = 0.35,
    max_retries: int = 3,
    allow_scroll: bool = True,
    expect: str = "",
    dry_run: bool = False,
    x: int | None = None,
    y: int | None = None,
    hint_bbox: list[int] | None = None,
) -> GroundingResult:
    """
    Full grounded UI interaction.
    Never clicks unless a visual match clears the confidence gate.
    """
    tgt = (target or "").strip()
    if not tgt and x is None:
        return GroundingResult(ok=False, error="Need target or coordinates", say="Need a UI target to ground.")

    result = GroundingResult(target=tgt or f"@{x},{y}", meta={"intent": intent})
    result.dpi_scale = cap.ensure_dpi_aware()

    # 1) Focus application (optional but preferred)
    focus = _focus_app(app)
    result.meta["focus"] = focus
    time.sleep(0.15)

    match = None
    shot_meta: dict[str, Any] = {}

    for attempt in range(1, max_retries + 1):
        result.attempts = attempt
        # 2) Screenshot
        shot_meta = cap.capture_for_grounding(monitor_id=monitor_id)
        result.screenshot_path = str(shot_meta.get("path") or "")
        result.monitor = dict(shot_meta.get("monitor") or {})
        result.dpi_scale = float(shot_meta.get("dpi_scale") or result.dpi_scale)
        if not shot_meta.get("ok"):
            result.error = shot_meta.get("error") or "screenshot_failed"
            continue

        # 3) Detect UI elements
        snap = detect_elements(use_ocr=True, use_uia=True)
        result.elements = elements_as_dicts(snap)

        # 4) Ground requested target
        if x is not None and y is not None and not tgt:
            match = match_near_point(snap, int(x), int(y))
            if not match:
                result.error = "No UI element near coordinates — refusing ungrounded click."
                # no point scrolling for impossible coords
                break
        else:
            match = ground_target(
                tgt,
                snap,
                hint_bbox=hint_bbox,
                min_confidence=min_confidence,
            )

        if match and match.confidence >= min_confidence:
            result.match = match
            result.grounded = True
            result.confidence = match.confidence
            break

        # 5) Scroll + retry with updated screenshot
        if allow_scroll and attempt < max_retries and tgt:
            _scroll("down", clicks=3)
            result.scrolled = True
            time.sleep(0.25)
            continue
        result.error = result.error or f"Could not ground {tgt or f'({x},{y})'!r} (best conf={getattr(match, 'confidence', 0):.2f})"
        break

    if not result.grounded or not result.match:
        result.ok = False
        result.say = result.error or f"Refused click: target {tgt!r} not visually grounded."
        return result

    # 6) Click (only after grounding)
    mx, my = result.match.x, result.match.y
    if dry_run:
        result.ok = True
        result.say = (
            f"Grounded '{result.match.name}' ({result.match.role}) "
            f"conf={result.match.confidence:.2f} at ({mx},{my}) — dry-run, no click."
        )
        result.meta["dry_run"] = True
        return result

    click_res = _do_click(mx, my)
    result.acted = True
    result.meta["click"] = click_res

    # 7) Observe + 8) Verify
    ver = verify_click_result(target=tgt, match=result.match, expect=expect)
    result.verified = bool(ver.get("ok"))
    result.meta["verify"] = ver
    result.ok = bool(click_res.get("ok")) and result.verified
    if result.ok:
        result.say = (
            f"Clicked '{result.match.name}' (conf={result.match.confidence:.2f}, "
            f"verified via {', '.join(ver.get('signals') or [])})."
        )
    else:
        result.say = (
            f"Clicked '{result.match.name}' but visual verify was weak "
            f"(signals={ver.get('signals')})."
        )
        # Still report acted; caller may retry pipeline
        result.ok = bool(click_res.get("ok"))  # click happened; verify soft
    return result


def ground_only(target: str, *, app: str | None = None, min_confidence: float = 0.35) -> GroundingResult:
    return run_pipeline(target, target=target, app=app, min_confidence=min_confidence, dry_run=True, max_retries=2)
