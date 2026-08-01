"""Map tool events → habit categories and reinforce scores."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

from neuron.learning_engine.scores import reinforce
from neuron.learning_engine.store import _BROWSERS, _EDITORS, get_store
from neuron.learning_engine.types import ToolEvent


def _scrub_args(args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        if k.lower() in ("password", "token", "api_key", "secret"):
            continue
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "..."
        out[k] = s
    return out


def _site_from(args: dict) -> str:
    url = str(args.get("url") or args.get("site") or args.get("query") or "").strip()
    if not url:
        return ""
    if "://" not in url and "." in url and " " not in url:
        url = "https://" + url
    try:
        host = urlparse(url).netloc or url
        host = host.lower().removeprefix("www.")
        return host.split("/")[0][:80]
    except Exception:
        return url[:80]


def _app_name(args: dict) -> str:
    return str(args.get("name") or args.get("application") or args.get("app") or "").strip()


def observe_tool(
    name: str,
    args: dict | None = None,
    *,
    ok: bool = True,
    detail: str = "",
    ts: float | None = None,
) -> None:
    """Primary learning hook — called from tool_registry.execute wrapper."""
    try:
        from neuron.learning_engine.config import enabled
        if not enabled():
            return
    except Exception:
        pass

    args = dict(args or {})
    ts = ts or time.time()
    tool = (name or "").strip()
    if not tool:
        return

    store = get_store()
    store.note_tool_sequence(tool)
    event = ToolEvent(tool=tool, args=_scrub_args(args), ok=ok, ts=ts, detail=detail[:200])

    if tool in ("open_app", "focus_app", "close_app", "minimize_app", "maximize_app"):
        app = _app_name(args)
        if app:
            item = store.get_or_create("app", app)
            reinforce(item, ok=ok, now=ts)
            store.note_schedule("app", app, ts)
            low = app.lower()
            if low in _BROWSERS or any(b in low for b in _BROWSERS):
                b = store.get_or_create("browser", app)
                reinforce(b, ok=ok, now=ts)
            if low in _EDITORS or any(e in low for e in _EDITORS):
                e = store.get_or_create("editor", app)
                reinforce(e, ok=ok, now=ts)

    if tool in ("open_website", "browser_open", "browser_navigate", "browser_search", "search_web", "search_site"):
        site = _site_from(args) or str(args.get("site") or "")
        if site:
            item = store.get_or_create("website", site)
            reinforce(item, ok=ok, now=ts)
            store.note_schedule("website", site, ts)
        browser = str(args.get("browser") or "")
        if browser:
            b = store.get_or_create("browser", browser)
            reinforce(b, ok=ok, now=ts)

    if tool in ("open_folder", "open_file", "search_files", "create_folder", "create_file"):
        loc = str(
            args.get("location")
            or args.get("path")
            or args.get("folder")
            or args.get("root")
            or args.get("name")
            or ""
        ).strip()
        if loc:
            key = loc.replace("\\", "/").rstrip("/")
            if "/" in key:
                key = "/".join(key.split("/")[:4])
            item = store.get_or_create("folder", key[:120])
            reinforce(item, ok=ok, now=ts)
            store.note_schedule("folder", key[:120], ts)

    if tool in ("move_window_to_monitor", "get_monitors", "move_window"):
        mon = str(args.get("monitor") or args.get("to") or args.get("display") or "").strip()
        if mon:
            item = store.get_or_create("monitor", mon)
            reinforce(item, ok=ok, now=ts)

    if tool in ("press_keys", "press_key", "hotkey"):
        keys = str(args.get("keys") or args.get("key") or "").strip().lower()
        keys = re.sub(r"\s+", "+", keys)
        if keys and len(keys) < 40:
            hk = store.hotkeys.get(keys)
            if hk is None:
                from neuron.learning_engine.types import ScoredItem
                hk = ScoredItem(key=keys, category="hotkey")
                store.hotkeys[keys] = hk
            reinforce(hk, ok=ok, now=ts)

    if ok and len(store.last_tools) >= 2:
        seq = " > ".join(store.last_tools[-3:])
        item = store.get_or_create("workflow", seq)
        reinforce(item, ok=True, now=ts)

    store.save()
    try:
        _bridge_prefs(event)
    except Exception:
        pass


def observe_utterance(text: str, *, acted: bool = True) -> None:
    if not acted or not (text or "").strip():
        return
    try:
        from neuron.learning_engine.config import enabled
        if not enabled():
            return
    except Exception:
        return
    store = get_store()
    low = text.lower()
    key = "command"
    if re.search(r"\b(open|launch)\b", low):
        key = "open"
    elif re.search(r"\b(search|youtube|google)\b", low):
        key = "search"
    elif re.search(r"\b(code|python|editor)\b", low):
        key = "coding"
    item = store.get_or_create("utterance", key)
    reinforce(item, ok=True)
    store.note_schedule("utterance", key)
    store.save()


def _bridge_prefs(event: ToolEvent) -> None:
    if not event.ok:
        return
    from neuron.v4.learn.preferences import get_preference_store
    prefs = get_preference_store()
    tool = event.tool
    args = event.args
    if tool in ("open_app", "focus_app"):
        app = _app_name(args)
        if app:
            prefs.note_inferred("favorite_app", app, domain="desktop")
            low = app.lower()
            if any(b in low for b in _BROWSERS):
                prefs.note_inferred("preferred_browser", app, domain="browser")
            if any(e in low for e in _EDITORS):
                prefs.note_inferred("preferred_editor", app, domain="coding")
    if tool in ("open_website", "browser_navigate", "browser_search"):
        site = _site_from(args)
        if site:
            prefs.note_inferred("favorite_website", site, domain="browser")
