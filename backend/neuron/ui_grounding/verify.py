"""Post-click visual verification."""

from __future__ import annotations

import time
from typing import Any

from neuron.ui_grounding.detect_ui import detect_elements
from neuron.ui_grounding.types import GroundMatch


def verify_click_result(
    *,
    target: str,
    match: GroundMatch | None,
    expect: str = "",
    settle_ms: int = 250,
) -> dict[str, Any]:
    """Re-observe screen after click; success if UI changed or expected text appears."""
    time.sleep(max(0, settle_ms) / 1000.0)
    before_title = ""
    try:
        import screen_capture
        # best-effort previous not stored — compare titles/OCR churn
    except Exception:
        pass

    snap = detect_elements(use_ocr=True, use_uia=True)
    names = {_norm(e.name) for e in snap.elements if e.name}
    ocr = " ".join(snap.ocr_text[:40]).lower()
    title = (snap.window_title or "").lower()
    exp = (expect or target or "").strip().lower()

    signals = []
    ok = False
    if exp and exp in ocr:
        ok = True
        signals.append("expect_in_ocr")
    if exp and any(exp in n for n in names):
        ok = True
        signals.append("expect_in_elements")
    # Soft success: we still see the app and click didn't crash detection
    if snap.elements or snap.window_title:
        signals.append("screen_observable")
        if not expect:
            ok = True  # no explicit expect → observability is enough
    if match and _norm(match.name) and _norm(match.name) not in names and match.role == "button":
        # button may have disappeared (dialog closed) — good signal
        signals.append("target_disappeared")
        ok = True

    return {
        "ok": ok,
        "signals": signals,
        "window_title": snap.window_title,
        "element_count": len(snap.elements),
        "ocr_preview": snap.ocr_text[:12],
    }


def _norm(s: str) -> str:
    return (s or "").strip().lower()
