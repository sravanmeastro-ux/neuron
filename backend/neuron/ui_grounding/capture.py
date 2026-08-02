"""Screenshot + multi-monitor + DPI helpers for grounding."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def ensure_dpi_aware() -> float:
    """Return approximate primary DPI scale (96dpi = 1.0)."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi and dpi > 0:
            return float(dpi) / 96.0
    except Exception:
        pass
    return 1.0


def list_monitors() -> list[dict[str, Any]]:
    try:
        import screen_capture
        return [m.to_dict() for m in screen_capture.list_monitors()]
    except Exception as exc:
        return [{"id": 1, "primary": True, "error": str(exc)}]


def capture_for_grounding(*, monitor_id: int | None = None, all_monitors: bool = False) -> dict[str, Any]:
    """Capture screen for element detection. Prefer foreground, else monitor/desktop."""
    out_dir = Path(__file__).resolve().parents[2] / "data" / "ui_grounding"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shot_{int(time.time() * 1000)}.png"
    dpi = ensure_dpi_aware()
    monitors = list_monitors()
    meta: dict[str, Any] = {"dpi_scale": dpi, "monitors": monitors}

    try:
        import screen_capture
        if all_monitors:
            img = screen_capture.capture_virtual_desktop()
            mon = {"id": "virtual", "primary": True}
        elif monitor_id is not None:
            img = screen_capture.capture_monitor(int(monitor_id))
            mon = next((m for m in monitors if m.get("id") == monitor_id), {"id": monitor_id})
        else:
            img = screen_capture.capture_foreground() or screen_capture.capture_virtual_desktop()
            mon = next((m for m in monitors if m.get("primary")), monitors[0] if monitors else {})
        if img is not None:
            img.save(str(path))
            meta.update({
                "path": str(path),
                "size": list(img.size),
                "monitor": mon,
                "ok": True,
            })
            return meta
    except Exception as exc:
        meta["capture_error"] = str(exc)

    # Fallback Pillow grab
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=bool(all_monitors))
        img.save(str(path))
        meta.update({"path": str(path), "size": list(img.size), "ok": True, "fallback": "ImageGrab"})
        return meta
    except Exception as exc:
        meta["ok"] = False
        meta["error"] = str(exc)
        return meta


def scale_point(x: int, y: int, *, dpi_scale: float = 1.0) -> tuple[int, int]:
    """Coords from screen_capture are already DPI-aware when awareness is set; keep identity."""
    if dpi_scale and abs(dpi_scale - 1.0) > 0.01:
        # Only adjust if caller provides logical coords
        return int(round(x * dpi_scale)), int(round(y * dpi_scale))
    return int(x), int(y)
