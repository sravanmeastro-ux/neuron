"""Multi-monitor world model for AgentLoop observation.

Produces the closed-loop observation format:

  Monitor 1
  Chrome
  YouTube
  Search results visible
  First video at approximately x,y

  Monitor 2
  Discord
  Server list visible

  Active application: Chrome
  Focused monitor: 1
  Cursor position: x,y
"""

from __future__ import annotations

import re
from typing import Any


# Window-title hints → short app label
_APP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgoogle chrome\b|\bchrome\b", re.I), "Chrome"),
    (re.compile(r"\bmicrosoft edge\b|\bedge\b", re.I), "Edge"),
    (re.compile(r"\bfirefox\b", re.I), "Firefox"),
    (re.compile(r"\bopera\b", re.I), "Opera"),
    (re.compile(r"\bbrave\b", re.I), "Brave"),
    (re.compile(r"\bdiscord\b", re.I), "Discord"),
    (re.compile(r"\bspotify\b", re.I), "Spotify"),
    (re.compile(r"\bsteam\b", re.I), "Steam"),
    (re.compile(r"\bblender\b", re.I), "Blender"),
    (re.compile(r"\bvisual studio code\b|\bvs ?code\b", re.I), "VS Code"),
    (re.compile(r"\bcursor\b", re.I), "Cursor"),
    (re.compile(r"\bnotepad\b", re.I), "Notepad"),
    (re.compile(r"\bfile explorer\b|\bexplorer\b", re.I), "Explorer"),
    (re.compile(r"\bslack\b", re.I), "Slack"),
    (re.compile(r"\bwhatsapp\b", re.I), "WhatsApp"),
]


def _app_from_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return ""
    # Prefer suffix after last " - " (common browser pattern)
    for pat, name in _APP_PATTERNS:
        if pat.search(t):
            return name
    # Last segment after dash often is the app
    if " - " in t:
        tail = t.rsplit(" - ", 1)[-1].strip()
        for pat, name in _APP_PATTERNS:
            if pat.search(tail):
                return name
        if len(tail) < 40:
            return tail
    return t.split()[0][:40] if t else ""


def _site_from_title_or_url(title: str, url: str = "") -> str:
    hay = f"{title} {url}".lower()
    if "youtube" in hay:
        return "YouTube"
    if "gmail" in hay or "mail.google" in hay:
        return "Gmail"
    if "google." in hay and "search" in hay:
        return "Google"
    if "discord.com" in hay:
        return "Discord"
    if "github.com" in hay:
        return "GitHub"
    if "twitter.com" in hay or "x.com" in hay:
        return "X"
    if "reddit.com" in hay:
        return "Reddit"
    return ""


def _cursor() -> dict[str, Any]:
    try:
        from neuron.perception.capture_ops import get_cursor_position
        r = get_cursor_position({})
        state = (getattr(r, "state", None) or {}) if r else {}
        return {
            "x": int(state.get("x") or 0),
            "y": int(state.get("y") or 0),
            "monitor": int(state.get("monitor") or state.get("monitor_id") or 0) or None,
        }
    except Exception:
        try:
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return {"x": int(pt.x), "y": int(pt.y), "monitor": None}
        except Exception:
            return {}


def _active_app_window() -> tuple[str, str, int | None]:
    """Return (app, window_title, monitor_id)."""
    title = ""
    app = ""
    mid = None
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        title = (fg.get("title") or "")[:160]
        app = _app_from_title(title)
    except Exception:
        pass
    try:
        import screen_capture as sc
        fg = sc.capture_foreground(padding=0)
        if fg:
            title = title or (fg.get("title") or "")
            mid = fg.get("monitor_id")
            if not app:
                app = _app_from_title(title)
    except Exception:
        pass
    try:
        import app_context
        sticky = ""
        if hasattr(app_context, "get_app"):
            sticky = app_context.get_app() or ""
        if sticky and not app:
            app = sticky[:40]
    except Exception:
        pass
    return app, title, mid


def _browser_hints() -> dict[str, Any]:
    """Lightweight YouTube / browser scene hints (local Playwright if attached)."""
    out: dict[str, Any] = {"url": "", "site": "", "search_results": False, "first_video": None}
    try:
        import browser
        url = ""
        try:
            url = browser.current_url() or ""
        except Exception:
            url = ""
        out["url"] = (url or "")[:200]
        out["site"] = _site_from_title_or_url("", url)
        if "youtube.com" in (url or "").lower():
            out["site"] = "YouTube"
            if "/results" in url.lower() or "search_query=" in url.lower():
                out["search_results"] = True
            # Best-effort first video coords — never block the loop
            try:
                worker = getattr(browser, "_worker", None) or getattr(browser, "_get", lambda: None)()
                if worker is not None and hasattr(worker, "submit"):
                    first = worker.submit(_op_first_video_screen_xy, timeout=3)
                    if isinstance(first, dict) and first.get("x") is not None:
                        out["first_video"] = first
                        out["search_results"] = out["search_results"] or bool(first.get("visible"))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _op_first_video_screen_xy(w):
    """Playwright worker op: first visible YouTube card center in screen coords."""
    page = w.page
    if page is None:
        return None
    data = page.evaluate(
        """() => {
          const items = Array.from(document.querySelectorAll(
            'ytd-rich-item-renderer, ytd-video-renderer, ytd-grid-video-renderer'
          ));
          for (const item of items) {
            const a = item.querySelector('a#video-title-link, a#video-title, h3 a[href*="/watch"]');
            if (!a) continue;
            const href = a.href || '';
            if (!href || href.includes('/shorts/')) continue;
            const rect = item.getBoundingClientRect();
            if (rect.width < 80 || rect.height < 40) continue;
            if (rect.top < -40 || rect.bottom < 80) continue;
            const ratio = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0)) / Math.max(1, rect.height);
            if (ratio < 0.4) continue;
            return {
              x: Math.round(rect.left + rect.width / 2),
              y: Math.round(rect.top + rect.height / 2),
              title: (a.getAttribute('title') || a.innerText || '').trim().slice(0, 80),
              visible: true,
            };
          }
          return null;
        }"""
    )
    if not data:
        return None
    # Convert page viewport coords → screen using Chrome window position if possible
    try:
        import screen_capture as sc
        wins = sc.list_visible_windows(30) or []
        chrome = next(
            (w for w in wins if "chrome" in (w.get("title") or "").lower()
             or "youtube" in (w.get("title") or "").lower()),
            None,
        )
        if chrome:
            # Rough: content area offset under title bar (~80px) + window left/top
            sx = int(chrome["left"]) + int(data["x"])
            sy = int(chrome["top"]) + int(data["y"]) + 80
            return {
                "x": sx,
                "y": sy,
                "page_x": data["x"],
                "page_y": data["y"],
                "title": data.get("title") or "",
                "visible": True,
            }
    except Exception:
        pass
    return {
        "x": int(data["x"]),
        "y": int(data["y"]),
        "title": data.get("title") or "",
        "visible": True,
        "page_only": True,
    }


def _discord_hints(title: str, uia_labels: list[str] | None = None) -> list[str]:
    bits: list[str] = []
    hay = " ".join([title or ""] + list(uia_labels or [])).lower()
    if "discord" not in hay and "discord" not in (title or "").lower():
        return bits
    if any(k in hay for k in ("settings", "user settings", "voice connected")):
        bits.append("Discord open")
    else:
        # Default structural guess — Discord's main chrome is the server rail
        bits.append("Server list visible")
    return bits


def _monitor_blocks(
    *,
    deep: bool = False,
    browser_hints: dict | None = None,
) -> list[dict[str, Any]]:
    import screen_capture as sc

    mons = sc.list_monitors()
    wins = sc.list_visible_windows(40) or []
    browser_hints = browser_hints or {}
    blocks: list[dict[str, Any]] = []

    uia_labels: list[str] = []
    if deep:
        try:
            from neuron.uia import inspect as uia_inspect
            _win, elements = uia_inspect.walk_elements(
                max_depth=2,
                max_elements=30,
                named_only=True,
                time_budget=1.2,
            )
            for el in elements or []:
                name = (getattr(el, "name", None) or "").strip()
                if name and name not in uia_labels:
                    uia_labels.append(name)
        except Exception:
            uia_labels = []

    for m in mons:
        on_mon = [w for w in wins if int(w.get("monitor_id") or 0) == int(m.id)]
        # Largest window as primary content
        primary = max(on_mon, key=lambda w: int(w.get("width") or 0) * int(w.get("height") or 0), default=None)
        title = (primary.get("title") if primary else "") or ""
        app = _app_from_title(title)
        site = _site_from_title_or_url(title, browser_hints.get("url") or "")
        details: list[str] = []

        # Browser / YouTube details only when this monitor likely hosts the browser
        app_l = (app or "").lower()
        title_l = title.lower()
        is_browser_mon = app_l in ("chrome", "edge", "firefox", "opera", "brave") or any(
            k in title_l for k in ("youtube", "chrome", "edge", "opera")
        )
        if is_browser_mon:
            if site:
                details.append(site)
            elif browser_hints.get("site"):
                details.append(str(browser_hints["site"]))
            if browser_hints.get("search_results") and (
                "youtube" in (site or browser_hints.get("site") or "").lower()
                or "youtube" in title_l
            ):
                details.append("Search results visible")
            fv = browser_hints.get("first_video")
            if fv and isinstance(fv, dict) and fv.get("x") is not None:
                fx, fy = int(fv["x"]), int(fv["y"])
                if (
                    fv.get("page_only")
                    or (
                        m.left <= fx < m.left + m.width
                        and m.top <= fy < m.top + m.height
                    )
                ):
                    details.append(f"First video at approximately {fx},{fy}")

        if "discord" in app_l or "discord" in title_l:
            details.extend(_discord_hints(title, uia_labels))

        other_titles = [
            (w.get("title") or "")[:50]
            for w in on_mon[:4]
            if w is not primary and (w.get("title") or "")
        ]

        blocks.append({
            "monitor": int(m.id),
            "primary": bool(m.primary),
            "app": app or ("Desktop" if not on_mon else "Window"),
            "title": title[:100],
            "site": site,
            "details": details,
            "windows": [title] + other_titles if title else other_titles,
            "geometry": {
                "left": m.left, "top": m.top,
                "width": m.width, "height": m.height,
            },
        })
    return blocks


def build_world_model(*, deep: bool = False, use_ocr: bool = False) -> dict[str, Any]:
    """Gather structured multi-monitor world state (local/free)."""
    browser_hints = _browser_hints()
    blocks = _monitor_blocks(deep=deep, browser_hints=browser_hints)
    app, title, mid = _active_app_window()
    cursor = _cursor()
    focused = None
    try:
        import monitor_focus
        focused = monitor_focus.get_focus()
    except Exception:
        focused = None
    if focused is None:
        focused = mid or cursor.get("monitor") or 1

    # Attach OCR snippet to focused monitor only when requested
    if use_ocr and blocks:
        try:
            from neuron.perception.ocr import ocr_image
            args: dict[str, Any] = {}
            if focused is not None:
                args["monitor"] = focused
            result = ocr_image(args)
            state = getattr(result, "state", None) or {}
            ocr = list(state.get("visible_text") or state.get("text") or [])[:12]
            for b in blocks:
                if int(b["monitor"]) == int(focused or b["monitor"]) and ocr:
                    b.setdefault("details", []).append("OCR: " + " | ".join(str(t) for t in ocr)[:180])
                    b["ocr_text"] = ocr
                    break
        except Exception:
            pass

    model = {
        "monitors": blocks,
        "active_application": app or _app_from_title(title) or "",
        "active_window": title,
        "focused_monitor": int(focused) if focused else 1,
        "cursor": cursor,
        "browser": browser_hints,
    }
    model["text"] = format_world_model(model)
    return model


def format_world_model(model: dict[str, Any] | None) -> str:
    """Render the human/agent observation format the loop expects."""
    model = model or {}
    lines: list[str] = []
    for b in model.get("monitors") or []:
        lines.append(f"Monitor {b.get('monitor')}")
        app = (b.get("app") or "").strip()
        if app:
            lines.append(app)
        for d in b.get("details") or []:
            if d and str(d).strip() and str(d).strip() != app:
                lines.append(str(d).strip())
        # If no details, show window title as a hint
        if not (b.get("details") or []) and (b.get("title") or ""):
            title = b["title"]
            if app and title.lower().startswith(app.lower()):
                pass
            elif app and f" - {app}" in title:
                # "Something - Chrome" → show page bit
                page = title.rsplit(f" - {app}", 1)[0].strip()
                if page:
                    lines.append(page[:80])
            else:
                lines.append(title[:80])
        lines.append("")  # blank line between monitors

    active = model.get("active_application") or ""
    focused = model.get("focused_monitor")
    cursor = model.get("cursor") or {}
    lines.append(f"Active application: {active or '?'}")
    lines.append(f"Focused monitor: {focused if focused is not None else '?'}")
    if cursor.get("x") is not None and cursor.get("y") is not None:
        lines.append(f"Cursor position: {cursor['x']},{cursor['y']}")
    else:
        lines.append("Cursor position: …")

    # Trim trailing blank lines before footer was already placed
    text = "\n".join(lines).rstrip() + "\n"
    return text


def world_model_text(*, deep: bool = False, use_ocr: bool = False) -> str:
    """Convenience: build + format in one call."""
    return build_world_model(deep=deep, use_ocr=use_ocr).get("text") or ""
