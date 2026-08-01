"""Phase 10 / V3.8 — multi-monitor intelligence.

Live geometry from the OS (no hardcoded resolutions). Understands:
  main / primary, monitor 1/2/…, other, left, right, foreground / current
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.windows.result import ToolResult, fail, ok

_WORD_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def _log(msg: str) -> None:
    print(f"[monitors] {msg}", flush=True)


def list_monitor_dicts() -> list[dict[str, Any]]:
    """Enumerate connected displays with IDs, geometry, primary, work area, roles."""
    try:
        import screen_capture as sc
        raw = sc.list_monitors() or []
    except Exception as exc:
        _log(f"list_monitors failed: {exc}")
        return []

    mons: list[dict[str, Any]] = []
    for i, m in enumerate(raw, 1):
        if hasattr(m, "to_dict"):
            d = m.to_dict()
        elif isinstance(m, dict):
            d = {
                "id": int(m.get("id") or i),
                "left": int(m.get("left") or 0),
                "top": int(m.get("top") or 0),
                "width": int(m.get("width") or 0),
                "height": int(m.get("height") or 0),
                "primary": bool(m.get("primary")),
                "work_left": int(m.get("work_left") or m.get("left") or 0),
                "work_top": int(m.get("work_top") or m.get("top") or 0),
                "work_width": int(m.get("work_width") or m.get("width") or 0),
                "work_height": int(m.get("work_height") or m.get("height") or 0),
            }
        else:
            d = {
                "id": int(getattr(m, "id", i)),
                "left": int(getattr(m, "left", 0)),
                "top": int(getattr(m, "top", 0)),
                "width": int(getattr(m, "width", 0)),
                "height": int(getattr(m, "height", 0)),
                "primary": bool(getattr(m, "primary", i == 1)),
                "work_left": int(getattr(m, "work_left", getattr(m, "left", 0))),
                "work_top": int(getattr(m, "work_top", getattr(m, "top", 0))),
                "work_width": int(getattr(m, "work_width", getattr(m, "width", 0))),
                "work_height": int(getattr(m, "work_height", getattr(m, "height", 0))),
            }
        mons.append(d)

    return _annotate_roles(mons)


def _annotate_roles(mons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive left/right/main/other/foreground from live geometry — never assume resolutions."""
    if not mons:
        return mons
    # Spatial order by center-x then center-y
    ordered = sorted(
        mons,
        key=lambda m: (int(m["left"]) + int(m["width"]) // 2, int(m["top"]) + int(m["height"]) // 2),
    )
    leftmost_id = int(ordered[0]["id"])
    rightmost_id = int(ordered[-1]["id"])
    primary_id = next((int(m["id"]) for m in mons if m.get("primary")), int(mons[0]["id"]))
    fg_id = foreground_monitor_id(mons)

    for m in mons:
        mid = int(m["id"])
        roles: list[str] = []
        if mid == primary_id:
            roles.extend(["main", "primary"])
        else:
            roles.append("secondary")
        if len(mons) >= 2:
            if mid == leftmost_id:
                roles.append("left")
            if mid == rightmost_id:
                roles.append("right")
            if mid != primary_id:
                roles.append("other")
        if fg_id is not None and mid == int(fg_id):
            roles.extend(["foreground", "current", "this"])
        # Dedupe preserve order
        seen: set[str] = set()
        uniq = []
        for r in roles:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        m["roles"] = uniq
        m["label"] = (
            f"#{mid} {'/'.join(uniq)} {m['width']}x{m['height']} "
            f"@({m['left']},{m['top']})"
        )
    return mons


def resolve_monitor_ref(
    ref: Any,
    *,
    relative_to: int | None = None,
    monitors: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Resolve natural language / numeric monitor references to a monitor dict.

    Accepts: 1, "2", "screen 1", "left monitor", "right screen",
    "main", "primary", "other screen", "second display",
    "foreground monitor", "current screen", "this monitor", …
    """
    mons = monitors if monitors is not None else list_monitor_dicts()
    if not mons:
        return None

    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        mid = int(ref)
        for m in mons:
            if int(m["id"]) == mid:
                return m
        return None

    text = str(ref or "").strip().lower()
    if not text:
        return None

    # Bare number
    if re.fullmatch(r"\d{1,2}", text):
        return resolve_monitor_ref(int(text), monitors=mons)

    # screen/monitor/display N | Nth
    m = re.search(
        r"(?:screen|monitor|display)\s*(?:number\s*)?"
        r"(one|two|three|four|five|first|second|third|fourth|fifth|\d{1,2})",
        text,
    )
    if m:
        token = m.group(1)
        mid = _WORD_NUM.get(token) or int(token)
        return resolve_monitor_ref(mid, monitors=mons)

    # leading ordinal alone
    m = re.fullmatch(
        r"(?:the\s+)?(one|two|three|four|five|first|second|third|fourth|fifth|\d{1,2})",
        text,
    )
    if m:
        token = m.group(1)
        mid = _WORD_NUM.get(token) or int(token)
        return resolve_monitor_ref(mid, monitors=mons)

    # Foreground / current / this — live window→monitor mapping (not sticky focus alone)
    if re.search(
        r"\b(foreground|current|this|active)\s*(?:screen|monitor|display)?\b"
        r"|\b(?:screen|monitor|display)\s+(?:i(?:'m| am)\s+on|in\s+focus)\b",
        text,
    ):
        fg = relative_to if relative_to is not None else foreground_monitor_id(mons)
        if fg is not None:
            hit = resolve_monitor_ref(int(fg), monitors=mons)
            if hit:
                return hit
        try:
            import monitor_focus
            sticky = monitor_focus.get_focus()
            if sticky is not None:
                hit = resolve_monitor_ref(int(sticky), monitors=mons)
                if hit:
                    return hit
        except Exception:
            pass
        for mon in mons:
            if "foreground" in (mon.get("roles") or []) or "current" in (mon.get("roles") or []):
                return mon
        return next((m for m in mons if m.get("primary")), mons[0])

    # Role words
    if re.search(r"\b(main|primary|primary\s+screen|main\s+screen)\b", text):
        for mon in mons:
            if "main" in (mon.get("roles") or []) or mon.get("primary"):
                return mon
        return mons[0]

    if re.search(r"\bleft\b", text):
        for mon in mons:
            if "left" in (mon.get("roles") or []):
                return mon
        # Fallback: spatially leftmost
        return min(mons, key=lambda x: int(x["left"]) + int(x["width"]) // 2)

    if re.search(r"\bright\b", text):
        for mon in mons:
            if "right" in (mon.get("roles") or []):
                return mon
        return max(mons, key=lambda x: int(x["left"]) + int(x["width"]) // 2)

    if re.search(r"\b(other|another|opposite|secondary)\b", text):
        # Prefer monitor that is not relative_to / not primary — live geometry only
        cur = relative_to
        if cur is None:
            try:
                import monitor_focus
                cur = monitor_focus.get_focus()
            except Exception:
                cur = None
        if cur is None:
            # Use foreground window's monitor as "current"
            cur = foreground_monitor_id(mons)
        for mon in mons:
            if cur is not None and int(mon["id"]) != int(cur):
                return mon
        for mon in mons:
            if not mon.get("primary"):
                return mon
        return mons[-1] if len(mons) > 1 else mons[0]

    return None


def extract_monitor_ref(text: str) -> str | None:
    """Pull a monitor phrase out of a user utterance, if any."""
    t = (text or "").strip()
    if not t:
        return None
    patterns = [
        r"\b(?:on|to|onto|at)\s+(?:my\s+|the\s+)?"
        r"(left|right|main|other|another|primary|secondary|foreground|current|this)\s+"
        r"(?:screen|monitor|display)\b",
        r"\b(?:on|to|onto|at)\s+(?:my\s+|the\s+)?"
        r"(?:screen|monitor|display)\s*(?:number\s*)?"
        r"(one|two|three|four|five|first|second|third|\d{1,2})\b",
        r"\b(?:screen|monitor|display)\s*(?:number\s*)?"
        r"(one|two|three|four|five|first|second|third|\d{1,2})\b",
        r"\b(left|right|main|other|another|primary|foreground|current)\s+"
        r"(?:screen|monitor|display)\b",
        r"\bthe\s+other\s+screen\b",
        r"\b(?:the\s+)?foreground\s+monitor\b",
        r"\b(?:the\s+)?current\s+(?:screen|monitor)\b",
    ]
    for p in patterns:
        m = re.search(p, t, re.I)
        if m:
            return m.group(0)
    return None


def normalize_monitor_arg(ref: Any, *, relative_to: int | None = None) -> str | int | None:
    """
    Keep NL monitor args as stable tokens for plans (other/left/foreground/N).
    Never rewrite 'other' → hardcoded '2' — resolve at act time via geometry.
    """
    if ref is None or ref == "":
        return None
    if isinstance(ref, (int, float)) and not isinstance(ref, bool):
        return int(ref)
    text = str(ref).strip().lower()
    if re.fullmatch(r"\d{1,2}", text):
        return int(text)
    # Bare ordinals / word numbers → numeric id (stable across layouts)
    if text in _WORD_NUM:
        return int(_WORD_NUM[text])
    for token in (
        "other", "another", "opposite", "secondary",
        "left", "right", "main", "primary",
        "foreground", "current", "this", "active",
    ):
        if re.search(rf"\b{token}\b", text):
            return "other" if token == "another" else token
    # "monitor 2" / "screen two"
    m = re.search(
        r"(?:screen|monitor|display)\s*(?:number\s*)?"
        r"(one|two|three|four|five|first|second|third|fourth|fifth|\d{1,2})",
        text,
    )
    if m:
        tok = m.group(1)
        return _WORD_NUM.get(tok) or int(tok)
    mon = resolve_monitor_ref(text, relative_to=relative_to)
    return int(mon["id"]) if mon else text


def monitor_for_rect(
    left: int,
    top: int,
    width: int,
    height: int,
    monitors: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    mons = monitors if monitors is not None else list_monitor_dicts()
    cx = int(left) + max(1, int(width)) // 2
    cy = int(top) + max(1, int(height)) // 2
    for m in mons:
        if (
            int(m["left"]) <= cx < int(m["left"]) + int(m["width"])
            and int(m["top"]) <= cy < int(m["top"]) + int(m["height"])
        ):
            return m
    return mons[0] if mons else None


def foreground_monitor_id(monitors: list[dict[str, Any]] | None = None) -> int | None:
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        if not fg:
            return None
        left = int(fg.get("left") or 0)
        top = int(fg.get("top") or 0)
        right = int(fg.get("right") or left + 100)
        bottom = int(fg.get("bottom") or top + 100)
        mon = monitor_for_rect(left, top, right - left, bottom - top, monitors)
        return int(mon["id"]) if mon else None
    except Exception:
        return None


def window_monitor_id(win: dict[str, Any], monitors: list[dict[str, Any]] | None = None) -> int | None:
    if win.get("monitor_id"):
        return int(win["monitor_id"])
    mon = monitor_for_rect(
        int(win.get("left") or 0),
        int(win.get("top") or 0),
        int(win.get("width") or 100),
        int(win.get("height") or 100),
        monitors,
    )
    return int(mon["id"]) if mon else None


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


def get_monitors(args: dict | None = None) -> ToolResult:
    mons = list_monitor_dicts()
    if not mons:
        return fail("No monitors detected.")
    bits = [m.get("label") or f"#{m['id']}" for m in mons]
    return ok(
        "Monitors: " + "; ".join(bits),
        state={"monitors": mons, "count": len(mons)},
        method="win32",
    )


def get_windows_by_monitor(args: dict | None = None) -> ToolResult:
    args = args or {}
    mons = list_monitor_dicts()
    ref = args.get("monitor") or args.get("monitor_id") or args.get("screen") or args.get("display")
    if ref in (None, "", 0, "0"):
        # Group all
        grouped: dict[int, list[dict]] = {int(m["id"]): [] for m in mons}
        for w in _list_windows_with_monitor(mons):
            mid = int(w.get("monitor_id") or 0)
            grouped.setdefault(mid, []).append(w)
        summary = []
        for mid, wins in grouped.items():
            titles = ", ".join((x.get("title") or "")[:40] for x in wins[:6])
            summary.append(f"#{mid}({len(wins)}): {titles or 'none'}")
        return ok(
            "Windows by monitor — " + " | ".join(summary),
            state={"by_monitor": {str(k): v for k, v in grouped.items()}, "monitors": mons},
            method="win32",
        )

    mon = resolve_monitor_ref(ref, monitors=mons)
    if not mon:
        return fail(f"Couldn't resolve monitor '{ref}'.", state={"monitors": mons})
    mid = int(mon["id"])
    wins = [w for w in _list_windows_with_monitor(mons) if int(w.get("monitor_id") or 0) == mid]
    titles = [w.get("title") for w in wins]
    return ok(
        f"Monitor {mid} ({', '.join(mon.get('roles') or [])}): "
        + ("; ".join(str(t)[:50] for t in titles[:15]) if titles else "no windows"),
        state={"monitor": mon, "windows": wins, "count": len(wins)},
        method="win32",
    )


def capture_monitor(args: dict | None = None) -> ToolResult:
    """Capture a monitor; accepts id or NL (left/right/main/screen 2)."""
    args = dict(args or {})
    mons = list_monitor_dicts()
    ref = args.get("monitor") or args.get("monitor_id") or args.get("screen") or args.get("display") or 1
    mon = resolve_monitor_ref(ref, monitors=mons)
    if not mon:
        return fail(f"Couldn't resolve monitor '{ref}'.", state={"monitors": mons})
    mid = int(mon["id"])
    try:
        import screen_capture as sc
        from neuron.perception.capture_ops import prepare_image, _out_dir

        sc_mons = sc.list_monitors() or []
        target = None
        for m in sc_mons:
            if int(getattr(m, "id", 0) or 0) == mid:
                target = m
                break
        if target is None and sc_mons:
            target = sc_mons[0]
            mid = int(getattr(target, "id", 1) or 1)
        if target is None:
            return fail("No monitor.", state={"monitors": mons})
        img = sc.capture_monitor(target)
        img = prepare_image(img, max_width=int(args.get("max_width") or 1600))
        path = _out_dir() / f"mon_{mid}.png"
        img.save(path)
        return ok(
            f"Captured monitor {mid} ({', '.join(mon.get('roles') or [])}): {path.name}",
            state={
                "path": str(path),
                "monitor": mid,
                "roles": mon.get("roles") or [],
                "width": img.width,
                "height": img.height,
                "left": int(mon.get("left") or 0),
                "top": int(mon.get("top") or 0),
            },
            method="win32",
        )
    except Exception as exc:
        return fail(str(exc), state={"monitor": mon})


def move_window_to_monitor(args: dict | None = None) -> ToolResult:
    """
    Move a window onto a target monitor and verify its center landed there.
    Geometry comes from live monitor work areas — no hardcoded resolutions.
    """
    args = args or {}
    mons = list_monitor_dicts()
    if not mons:
        return fail("No monitors detected.")

    title = (
        args.get("title")
        or args.get("name")
        or args.get("app")
        or args.get("window")
        or ""
    ).strip()
    ref = (
        args.get("monitor")
        or args.get("monitor_id")
        or args.get("screen")
        or args.get("display")
        or args.get("to")
        or ""
    )

    # Resolve the window FIRST so "other/secondary" is relative to *that*
    # window's monitor — not whatever happens to be foreground on the PC.
    hwnd, win = _resolve_window(title)
    if not hwnd:
        return fail(f"Couldn't find window for '{title or 'foreground'}'.")

    before_mon = monitor_for_rect(
        int(win.get("left") or 0),
        int(win.get("top") or 0),
        int(win.get("width") or 100),
        int(win.get("height") or 100),
        mons,
    )
    before_id = int(before_mon["id"]) if before_mon else None

    relative_to = args.get("from_monitor")
    if relative_to is None:
        relative_to = before_id
    if relative_to is None and title:
        for w in _list_windows_with_monitor(mons):
            if title.lower() in (w.get("title") or "").lower():
                relative_to = w.get("monitor_id")
                break

    target = resolve_monitor_ref(ref, relative_to=relative_to, monitors=mons)
    if not target:
        return fail(
            f"Couldn't resolve target monitor '{ref}'.",
            state={"monitors": mons},
        )

    # Place inside work area (taskbar-aware), keep size clamped to work area
    ww = max(200, int(win.get("width") or 900))
    wh = max(150, int(win.get("height") or 700))
    work_w = max(200, int(target.get("work_width") or target["width"]))
    work_h = max(150, int(target.get("work_height") or target["height"]))
    ww = min(ww, work_w - 20)
    wh = min(wh, work_h - 20)
    margin = 40
    left = int(target.get("work_left") or target["left"]) + margin
    top = int(target.get("work_top") or target["top"]) + margin
    # Keep fully on work area
    left = min(left, int(target.get("work_left") or target["left"]) + work_w - ww - 8)
    top = min(top, int(target.get("work_top") or target["top"]) + work_h - wh - 8)

    try:
        import ctypes
        # Restore if maximized so MoveWindow sticks
        SW_RESTORE = 9
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        ctypes.windll.user32.MoveWindow(hwnd, int(left), int(top), int(ww), int(wh), True)
        time.sleep(0.2)
        from neuron.windows import state as win_state
        win_state.focus_hwnd(hwnd)
        time.sleep(0.15)
    except Exception as exc:
        return fail(f"move_window_to_monitor failed: {exc}")

    after = _window_by_hwnd(hwnd, mons) or {
        "hwnd": hwnd,
        "left": left,
        "top": top,
        "width": ww,
        "height": wh,
    }
    after_mon = monitor_for_rect(
        int(after.get("left") or left),
        int(after.get("top") or top),
        int(after.get("width") or ww),
        int(after.get("height") or wh),
        mons,
    )
    after_id = int(after_mon["id"]) if after_mon else None
    verified = after_id == int(target["id"])
    roles = ",".join(target.get("roles") or [])
    msg = (
        f"Moved '{(win.get('title') or title or 'window')[:60]}' "
        f"to monitor {target['id']} ({roles})."
    )
    if before_id is not None:
        msg = msg[:-1] + f" (was #{before_id})."
    if not verified:
        return fail(
            f"Moved but verification failed — expected monitor {target['id']}, got {after_id}.",
            state={
                "target": target,
                "before_monitor": before_id,
                "after_monitor": after_id,
                "window": after,
                "verified": False,
            },
        )
    return ok(
        msg,
        state={
            "target": target,
            "before_monitor": before_id,
            "after_monitor": after_id,
            "window": after,
            "hwnd": hwnd,
            "x": left,
            "y": top,
            "verified": True,
        },
        method="win32",
    )


def _list_windows_with_monitor(mons: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    mons = mons if mons is not None else list_monitor_dicts()
    try:
        import screen_capture as sc
        wins = sc.list_visible_windows(50) or []
        out = []
        for w in wins:
            row = dict(w)
            if not row.get("monitor_id"):
                row["monitor_id"] = window_monitor_id(row, mons)
            out.append(row)
        return out
    except Exception:
        pass
    # UIA fallback
    try:
        from neuron.windows import state as win_state
        wins = win_state.list_top_windows(40)
        out = []
        for w in wins:
            row = dict(w)
            row["monitor_id"] = window_monitor_id(row, mons)
            out.append(row)
        return out
    except Exception:
        return []


def _resolve_window(title: str) -> tuple[int, dict[str, Any]]:
    title = (title or "").strip()
    wins = _list_windows_with_monitor()
    if title:
        # Prefer app resolve
        try:
            from neuron.windows.resolve import resolve
            from neuron.windows import state as win_state
            resolved = resolve(title)
            app_wins = win_state.find_app_windows(resolved)
            if app_wins:
                hwnd = int(app_wins[0].get("hwnd") or 0)
                # Enrich with monitor list entry if possible
                for w in wins:
                    if int(w.get("hwnd") or 0) == hwnd:
                        return hwnd, w
                return hwnd, dict(app_wins[0])
        except Exception:
            pass
        low = title.lower()
        for w in wins:
            if low in (w.get("title") or "").lower():
                return int(w.get("hwnd") or 0), w
        return 0, {}
    # Foreground
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        hwnd = int(fg.get("hwnd") or 0)
        if hwnd:
            for w in wins:
                if int(w.get("hwnd") or 0) == hwnd:
                    return hwnd, w
            return hwnd, {
                "title": fg.get("title") or "",
                "hwnd": hwnd,
                "left": fg.get("left"),
                "top": fg.get("top"),
                "width": int(fg.get("right") or 0) - int(fg.get("left") or 0),
                "height": int(fg.get("bottom") or 0) - int(fg.get("top") or 0),
            }
    except Exception:
        pass
    return 0, {}


def _window_by_hwnd(hwnd: int, mons: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    for w in _list_windows_with_monitor(mons):
        if int(w.get("hwnd") or 0) == hwnd:
            return w
    # Fresh rect from Win32
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return {
                "hwnd": hwnd,
                "left": rect.left,
                "top": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "monitor_id": window_monitor_id(
                    {
                        "left": rect.left,
                        "top": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                    },
                    mons,
                ),
            }
    except Exception:
        pass
    return None
