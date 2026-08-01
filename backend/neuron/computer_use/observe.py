"""Observe desktop for Computer Use — wraps Screen Understanding + world model."""

from __future__ import annotations

from neuron.computer_use.types import CUObservation


def observe(*, use_ocr: bool = True, use_vlm: bool = False, question: str = "") -> CUObservation:
    app = ""
    title = ""
    elements = 0
    ocr: list[str] = []
    notes = ""
    raw: dict = {}
    try:
        from neuron.screen import observe as screen_observe
        snap = screen_observe(use_ocr=use_ocr, use_vlm=use_vlm, question=question)
        app = snap.application or ""
        title = snap.window_title or ""
        elements = len(snap.elements or [])
        ocr = list(snap.ocr_text[:20] or [])
        raw["screen"] = snap.to_dict() if hasattr(snap, "to_dict") else {}
        if snap.vlm_summary:
            notes = snap.vlm_summary[:240]
    except Exception as exc:
        raw["screen_error"] = str(exc)
    if not app:
        try:
            from neuron.brain.world_model import build_world_model
            wm = build_world_model(deep=False, use_ocr=False) or {}
            app = str(wm.get("active_app") or "")
            title = str(wm.get("active_window") or title)
            raw["world"] = {k: wm.get(k) for k in ("active_app", "active_window") if k in wm}
        except Exception:
            pass
    return CUObservation(
        application=app,
        window_title=title,
        notes=notes,
        elements=elements,
        ocr_preview=ocr,
        raw=raw,
    )


def text_visible(needle: str, obs: CUObservation) -> bool:
    n = (needle or "").lower().strip()
    if not n:
        return False
    blob = " ".join(obs.ocr_preview).lower()
    blob += " " + (obs.window_title or "").lower()
    blob += " " + (obs.notes or "").lower()
    return n in blob
