"""UI Grounding orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.ui_grounding import capture as cap
from neuron.ui_grounding.detect import classify_ug_intent
from neuron.ui_grounding.detect_ui import detect_elements, elements_as_dicts
from neuron.ui_grounding.pipeline import ground_only, run_pipeline
from neuron.ui_grounding.types import UGCapability, UGResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> UGResult:
    args = args or {}

    if capability == UGCapability.STATUS.value:
        mons = cap.list_monitors()
        dpi = cap.ensure_dpi_aware()
        say = (
            f"UI Grounding Engine online. Monitors={len(mons)}; DPI scale~{dpi:.2f}. "
            "Clicks require visual grounding."
        )
        return UGResult(ok=True, say=say, capability=capability, data={"monitors": mons, "dpi_scale": dpi})

    if capability == UGCapability.OBSERVE.value:
        shot = cap.capture_for_grounding(monitor_id=args.get("monitor"))
        snap = detect_elements()
        say = f"Observed {len(snap.elements)} elements; window={snap.window_title or 'n/a'}."
        return UGResult(
            ok=True,
            say=say,
            acted=True,
            capability=capability,
            data={"shot": shot, "elements": elements_as_dicts(snap), "title": snap.window_title},
        )

    if capability == UGCapability.GROUND.value:
        target = str(args.get("target") or args.get("name") or "").strip()
        if not target:
            return UGResult(ok=False, error="Need target", say="Need a target to ground.", capability=capability)
        r = ground_only(target, app=args.get("app"), min_confidence=float(args.get("min_confidence") or 0.35))
        return UGResult(
            ok=r.grounded,
            say=r.say,
            acted=False,
            capability=capability,
            data=r.to_dict(),
            error=r.error,
        )

    if capability in (UGCapability.CLICK.value, UGCapability.PIPELINE.value):
        target = str(args.get("target") or args.get("name") or "").strip()
        if not target and args.get("x") is None:
            return UGResult(ok=False, error="Need target", say="Need a UI target.", capability=capability)
        r = run_pipeline(
            target or "point",
            target=target,
            app=args.get("app"),
            min_confidence=float(args.get("min_confidence") or 0.35),
            max_retries=int(args.get("retries") or 3),
            allow_scroll=bool(args.get("scroll", True)),
            expect=str(args.get("expect") or ""),
            dry_run=bool(args.get("dry_run", False)),
            x=args.get("x"),
            y=args.get("y"),
            monitor_id=args.get("monitor"),
        )
        return UGResult(
            ok=r.ok or r.grounded,
            say=r.say,
            acted=r.acted,
            capability=capability,
            data=r.to_dict(),
            error=r.error,
        )

    return UGResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False) -> tuple[str, bool, dict]:
    intent = classify_ug_intent(text)
    cap = intent.get("capability") or UGCapability.STATUS.value
    args = dict(intent.get("args") or {})
    # Voice clicks default to live unless dry_run requested
    result = dispatch(cap, args)
    meta = {
        "path": "ui_grounding",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "UI grounding failed.", True, meta
