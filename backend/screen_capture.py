"""Multi-monitor capture for N.E.U.R.O.N.

Uses Win32 EnumDisplayMonitors + Pillow ImageGrab so NEURON can see every
display (not just the primary / focused window).
"""

from __future__ import annotations

import base64
import ctypes
import io
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageGrab

user32 = ctypes.windll.user32

# Per-monitor DPI awareness so Win32 bounds match ImageGrab / mouse coords.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class Monitor:
    id: int  # 1-based human id (matches Windows display numbering when possible)
    left: int
    top: int
    width: int
    height: int
    primary: bool

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def label(self) -> str:
        tag = "primary" if self.primary else "secondary"
        return f"Monitor {self.id} ({tag}, {self.width}x{self.height} at {self.left},{self.top})"


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


MONITORINFOF_PRIMARY = 1
EnumDisplayMonitorsProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


def list_monitors() -> list[Monitor]:
    """Return all connected monitors with virtual-desktop coordinates."""
    found: list[tuple] = []

    def _cb(hmon, _hdc, _lprc, _lp):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append((
                r.left,
                r.top,
                r.right - r.left,
                r.bottom - r.top,
                bool(info.dwFlags & MONITORINFOF_PRIMARY),
                hmon,
            ))
        return True

    user32.EnumDisplayMonitors(0, 0, EnumDisplayMonitorsProc(_cb), 0)
    # Primary first, then left-to-right / top-to-bottom.
    found.sort(key=lambda m: (not m[4], m[0], m[1]))
    out = []
    for i, (l, t, w, h, primary, _) in enumerate(found, start=1):
        out.append(Monitor(id=i, left=l, top=t, width=w, height=h, primary=primary))
    if not out:
        # Fallback: single virtual desktop
        vw = user32.GetSystemMetrics(78) or 1920
        vh = user32.GetSystemMetrics(79) or 1080
        vl = user32.GetSystemMetrics(76)
        vt = user32.GetSystemMetrics(77)
        out.append(Monitor(id=1, left=vl, top=vt, width=vw, height=vh, primary=True))
    return out


def virtual_desktop_bounds() -> tuple[int, int, int, int]:
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    return left, top, width, height


def capture_monitor(mon: Monitor) -> Image.Image:
    """Grab one monitor by absolute virtual-desktop bbox."""
    return ImageGrab.grab(bbox=mon.bbox, all_screens=True)


def capture_all_monitors() -> list[dict]:
    """Capture every monitor. Each item: monitor, image, label."""
    results = []
    for mon in list_monitors():
        try:
            img = capture_monitor(mon)
        except Exception:
            # Last resort: crop from full virtual grab
            full = ImageGrab.grab(all_screens=True)
            vl, vt, _, _ = virtual_desktop_bounds()
            x0 = mon.left - vl
            y0 = mon.top - vt
            img = full.crop((x0, y0, x0 + mon.width, y0 + mon.height))
        results.append({"monitor": mon, "image": img, "label": mon.label()})
    return results


def capture_virtual_desktop() -> Image.Image:
    """One image spanning the entire virtual desktop (all monitors)."""
    return ImageGrab.grab(all_screens=True)


def downscale(img: Image.Image, max_w: int = 1280) -> Image.Image:
    if img.width <= max_w:
        return img
    h = int(img.height * (max_w / img.width))
    return img.resize((max_w, h), Image.Resampling.LANCZOS)


def encode_jpeg(img: Image.Image, quality: int = 55, max_w: int = 1280) -> str:
    """Base64 JPEG for VLM prompts."""
    img = downscale(img.convert("RGB"), max_w=max_w)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def encode_png(img: Image.Image, max_w: int = 1600) -> str:
    img = downscale(img.convert("RGB"), max_w=max_w)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def monitor_for_point(x: int, y: int, monitors: Optional[list[Monitor]] = None) -> Optional[Monitor]:
    mons = monitors or list_monitors()
    for m in mons:
        if m.left <= x < m.left + m.width and m.top <= y < m.top + m.height:
            return m
    return mons[0] if mons else None


def list_visible_windows(max_windows: int = 40) -> list[dict]:
    """Top-level visible windows with title + bounds (for fast structural glance)."""
    results: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lp):
        if len(results) >= max_windows:
            return False
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()
        if not title or title.startswith("N.E.U.R.O.N"):
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 80 or h < 80:
            return True
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        mon = monitor_for_point(cx, cy)
        results.append({
            "title": title[:100],
            "left": rect.left,
            "top": rect.top,
            "width": w,
            "height": h,
            "monitor_id": mon.id if mon else 1,
        })
        return True

    user32.EnumWindows(_enum, 0)
    return results


def structural_overview() -> str:
    """Instant text map of monitors + open windows (no VLM)."""
    mons = list_monitors()
    wins = list_visible_windows()
    lines = [f"Displays: {len(mons)}"]
    for m in mons:
        lines.append(f"- {m.label()}")
        on_mon = [w for w in wins if w["monitor_id"] == m.id]
        if not on_mon:
            lines.append("  (no large windows)")
            continue
        for w in on_mon[:12]:
            lines.append(f'  • "{w["title"]}"')
    return "\n".join(lines)
