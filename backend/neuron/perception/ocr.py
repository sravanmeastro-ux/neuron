"""Local OCR — RapidOCR with region detection (Phase 5).

Process-wide singleton engine (thread-safe) — never re-init ONNX per call.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from neuron.windows.result import ToolResult, fail, ok

_ENGINE = None
_ENGINE_LOCK = threading.Lock()
_ENGINE_ERR: str | None = None


def _engine():
    """Return a cached RapidOCR instance (load once)."""
    global _ENGINE, _ENGINE_ERR
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ENGINE = RapidOCR()
            _ENGINE_ERR = None
            return _ENGINE
        except Exception as exc:
            _ENGINE_ERR = str(exc)
            raise


def ocr_image(args: dict | None = None) -> ToolResult:
    """OCR a saved image path or capture-then-OCR."""
    args = args or {}
    path = (args.get("path") or args.get("image") or args.get("file") or "").strip()
    if not path:
        # Capture FG / monitor first
        try:
            from neuron.perception import capture_ops
            if args.get("monitor"):
                cap = capture_ops.capture_monitor({"monitor": args.get("monitor")})
            else:
                cap = capture_ops.get_active_window_screenshot({})
                if not cap.success:
                    cap = capture_ops.capture_screen({})
            if not cap.success:
                return fail(cap.error or "Capture failed for OCR.")
            path = (cap.state or {}).get("path") or ""
        except Exception as exc:
            return fail(str(exc))
    if not path or not Path(path).exists():
        return fail(f"Image not found: {path}")

    regions = detect_text_regions({"path": path})
    if not regions.success:
        # Soft fallback to UIA labels
        try:
            from neuron.tools.uia_tools import get_ui_tree
            tree = str(get_ui_tree({"depth": 3, "limit": 30}))
            return ok(
                "OCR weak; UI labels:\n" + tree[:800],
                state={"path": path, "regions": [], "text": [], "fallback": "uia"},
                method="uia-fallback",
            )
        except Exception:
            return fail(regions.error or "OCR failed.")

    texts = [r.get("text") for r in (regions.state or {}).get("regions") or [] if r.get("text")]
    blob = "\n".join(texts)[:2000]
    return ok(
        blob or "(no text detected)",
        state={
            "path": path,
            "text": texts,
            "regions": (regions.state or {}).get("regions") or [],
            "visible_text": texts,
        },
        method="rapidocr",
    )


def detect_text_regions(args: dict | None = None) -> ToolResult:
    """Return OCR boxes: [{text, confidence, box:[[x,y]×4], center_x, center_y}]."""
    args = args or {}
    path = (args.get("path") or args.get("image") or "").strip()
    if not path or not Path(path).exists():
        return fail("Need an existing image path.")
    try:
        engine = _engine()
        result, _ = engine(path)
        regions: list[dict[str, Any]] = []
        if result:
            for line in result:
                # RapidOCR: [box, text, score]
                if not line or len(line) < 2:
                    continue
                box = line[0]
                text = str(line[1] or "").strip()
                conf = float(line[2]) if len(line) > 2 else 0.0
                if not text:
                    continue
                xs, ys = [], []
                try:
                    for pt in box:
                        xs.append(float(pt[0]))
                        ys.append(float(pt[1]))
                except Exception:
                    pass
                cx = int(sum(xs) / len(xs)) if xs else 0
                cy = int(sum(ys) / len(ys)) if ys else 0
                regions.append({
                    "text": text[:200],
                    "confidence": round(conf, 3),
                    "box": box,
                    "center_x": cx,
                    "center_y": cy,
                    "left": int(min(xs)) if xs else 0,
                    "top": int(min(ys)) if ys else 0,
                    "right": int(max(xs)) if xs else 0,
                    "bottom": int(max(ys)) if ys else 0,
                })
        return ok(
            f"{len(regions)} text region(s).",
            state={"path": path, "regions": regions[:80]},
            method="rapidocr",
        )
    except Exception as exc:
        err = _ENGINE_ERR or str(exc)
        return fail(f"OCR engine unavailable: {err}", method="rapidocr")


def read_screen(monitor=None) -> str:
    """Back-compat string API used by older callers."""
    args: dict[str, Any] = {}
    if monitor is not None:
        args["monitor"] = monitor
    r = ocr_image(args)
    return str(r)
