"""Desktop + conversation memory for deixis and chained commands."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DesktopMemory:
    current_app: str = ""
    last_app: str = ""
    focused_title: str = ""
    last_website: str = ""
    last_intent_id: str = ""
    last_command: str = ""
    last_query: str = ""
    last_monitor: str = ""
    clipboard_preview: str = ""
    running_apps: list[str] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0

    def push_turn(self, user: str, rewritten: str, intent_id: str) -> None:
        self.turns.append({
            "user": user[:160],
            "rewritten": rewritten[:160],
            "intent": intent_id,
            "ts": time.time(),
        })
        self.turns = self.turns[-12:]
        self.last_command = rewritten
        self.last_intent_id = intent_id
        self.updated_at = time.time()


_LOCK = threading.Lock()
_MEM = DesktopMemory()


def get_memory() -> DesktopMemory:
    return _MEM


def refresh_desktop_snapshot() -> DesktopMemory:
    """Cheap refresh of foreground + running sample (uses TTL window cache)."""
    with _LOCK:
        mem = _MEM
        try:
            from neuron.windows import state as win_state
            fg = win_state.get_foreground() or {}
            title = (fg.get("title") or "").strip()
            if title:
                mem.focused_title = title[:120]
                # Heuristic app from title
                low = title.lower()
                for needle, app in (
                    ("chrome", "chrome"),
                    ("edge", "edge"),
                    ("firefox", "firefox"),
                    ("notepad", "notepad"),
                    ("blender", "blender"),
                    ("visual studio code", "vscode"),
                    ("cursor", "cursor"),
                    ("spotify", "spotify"),
                    ("discord", "discord"),
                    ("steam", "steam"),
                ):
                    if needle in low:
                        if mem.current_app and mem.current_app != app:
                            mem.last_app = mem.current_app
                        mem.current_app = app
                        break
            procs = win_state.list_running_processes(40) or []
            mem.running_apps = [p.replace(".exe", "") for p in procs[:20]]
        except Exception:
            pass
        try:
            import pyperclip  # optional
            clip = (pyperclip.paste() or "")[:80]
            mem.clipboard_preview = clip
        except Exception:
            pass
        mem.updated_at = time.time()
        return mem


def remember_success(
    *,
    rewritten: str,
    intent_id: str,
    entities: list | None = None,
    user: str = "",
) -> None:
    with _LOCK:
        mem = _MEM
        mem.push_turn(user or rewritten, rewritten, intent_id)
        for e in entities or []:
            kind = getattr(e, "kind", "") or (e.get("kind") if isinstance(e, dict) else "")
            value = getattr(e, "value", "") or (e.get("value") if isinstance(e, dict) else "")
            if kind == "application" and value:
                if mem.current_app and mem.current_app != value:
                    mem.last_app = mem.current_app
                mem.current_app = value
            elif kind == "website" and value:
                mem.last_website = value
            elif kind == "query" and value:
                mem.last_query = value
            elif kind == "monitor" and value:
                mem.last_monitor = str(value)


def resolve_deixis(text: str, mem: DesktopMemory | None = None) -> tuple[str, list[str]]:
    """Replace it/that/this/again with concrete apps from memory."""
    mem = mem or refresh_desktop_snapshot()
    t = (text or "").strip()
    used: list[str] = []
    import re

    app = mem.current_app or mem.last_app
    if not app:
        return t, used

    def _sub_app(m: re.Match) -> str:
        used.append(f"deixis->{app}")
        return f"{m.group(1)} {app}{m.group(2) or ''}"

    def _replace_move(m: re.Match, application: str, used_list: list[str]) -> str:
        used_list.append(f"deixis->{application}")
        return f"move {application} to {m.group(1)}"

    newt = re.sub(
        r"\b(open|close|quit|focus|move|minimize|maximize)\s+"
        r"(?:it|that|this|them)(\s+again)?\b",
        _sub_app,
        t,
        flags=re.I,
    )
    newt = re.sub(
        r"\bmove\s+(?:it|that|this)\s+to\s+(monitor\s+\w+)",
        lambda m: _replace_move(m, app, used),
        newt,
        flags=re.I,
    )
    if re.search(r"\b(?:again|one more time)\b", newt, re.I) and app:
        if re.match(r"^(?:open|launch)\s+(?:it|that)(?:\s+again)?$", newt, re.I):
            newt = f"open {app}"
            used.append(f"again->{app}")

    return newt, used


def chain_rewrite(text: str, mem: DesktopMemory | None = None) -> tuple[str, list[str]]:
    """Fill missing site/app for follow-up searches / plays."""
    mem = mem or get_memory()
    t = (text or "").strip()
    used: list[str] = []
    import re

    if re.match(r"^search(?:\s+for)?\s+.+", t, re.I):
        youtube_ctx = mem.last_website == "youtube"
        if not youtube_ctx:
            for turn in reversed(mem.turns[-4:]):
                if "youtube" in (turn.get("rewritten") or "").lower():
                    youtube_ctx = True
                    break
        if youtube_ctx:
            q = re.sub(r"^search(?:\s+for)?\s+", "", t, flags=re.I).strip()
            if q and "youtube" not in q.lower():
                used.append("chain->youtube_search")
                return f"search youtube for {q}", used

    if re.match(r"^(?:play\s+)?(?:the\s+)?(?:first|second|third)\s+(?:one|video)?$", t, re.I):
        used.append("chain->play_result")
        ord_m = re.search(r"(first|second|third)", t, re.I)
        word = (ord_m.group(1) if ord_m else "first").lower()
        return f"play the {word} video", used

    if re.match(r"^go\s+to\s+(youtube|yt)$", t, re.I):
        used.append("chain->open_youtube")
        return "open youtube", used

    return t, used
