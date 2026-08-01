"""Long-term memory engine — write / query / maintain."""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.memory_engine.store import get_store
from neuron.memory_engine.types import MemoryItem, MemoryKind


def enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("long_term_memory", True))
    except Exception:
        return True


def remember(
    content: str,
    *,
    kind: str = MemoryKind.SEMANTIC.value,
    title: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
    value: float = 1.0,
    meta: dict | None = None,
) -> MemoryItem:
    item = MemoryItem(
        kind=kind,
        content=(content or "").strip(),
        title=title or "",
        tags=list(tags or []),
        pinned=pinned,
        value=value if not pinned else max(value, 3.0),
        meta=dict(meta or {}),
    )
    return get_store().add(item)


def remember_forever(content: str, *, title: str = "") -> MemoryItem:
    return remember(content, kind=MemoryKind.PREFERENCE.value, title=title or "Pinned", pinned=True, value=4.0)


def append_episode(text: str, *, meta: dict | None = None) -> MemoryItem | None:
    if not enabled() or not (text or "").strip():
        return None
    return remember(
        text.strip()[:400],
        kind=MemoryKind.EPISODIC.value,
        title="Episode",
        tags=["episode"],
        value=1.0,
        meta=meta,
    )


def append_conversation(role: str, text: str) -> MemoryItem | None:
    if not enabled() or not (text or "").strip():
        return None
    return remember(
        f"{role}: {text.strip()[:300]}",
        kind=MemoryKind.CONVERSATION.value,
        title="Chat",
        tags=["conversation", role],
        value=0.8,
    )


def note_project(name: str, detail: str = "") -> MemoryItem:
    return remember(
        detail or f"Working on project {name}",
        kind=MemoryKind.PROJECT.value,
        title=name,
        tags=["project", name.lower()],
        value=1.5,
        meta={"project": name},
    )


def note_desktop(app: str = "", folder: str = "", window: str = "") -> MemoryItem | None:
    if not enabled():
        return None
    parts = []
    if app:
        parts.append(f"app={app}")
    if folder:
        parts.append(f"folder={folder}")
    if window:
        parts.append(f"window={window}")
    if not parts:
        return None
    return remember(
        "; ".join(parts),
        kind=MemoryKind.DESKTOP.value,
        title="Desktop",
        tags=["desktop"],
        value=1.0,
        meta={"app": app, "folder": folder, "window": window},
    )


def note_preference(key: str, value: str) -> MemoryItem:
    return remember(
        f"{key} = {value}",
        kind=MemoryKind.PREFERENCE.value,
        title=key,
        tags=["pref", key],
        value=2.0,
        meta={"key": key, "value": value},
    )


def note_procedural(name: str, detail: str = "") -> MemoryItem:
    return remember(
        detail or name,
        kind=MemoryKind.PROCEDURAL.value,
        title=name,
        tags=["procedure"],
        value=1.5,
    )


def maintain() -> dict[str, Any]:
    """Summarize old + forget low-value memories."""
    store = get_store()
    summary = store.summarize_old()
    deleted = store.forget_low_value()
    return {
        "summarized": bool(summary),
        "summary_id": summary.item_id if summary else None,
        "forgotten": len(deleted),
        "stats": store.stats(),
    }


def query_memories(text: str) -> str | None:
    """Natural language memory questions. Returns reply or None if not a memory Q."""
    t = (text or "").strip()
    if not t:
        return None

    # Remember forever
    m = re.match(
        r"^(?:remember\s+(?:this|that)\s+forever|pin\s+(?:this|that)|never\s+forget)\s*[:\-]?\s*(.*)$",
        t,
        re.I,
    )
    if m:
        body = (m.group(1) or "").strip() or t
        item = remember_forever(body)
        maintain()
        return f"I'll remember that forever: {item.content[:120]}"

    m = re.match(r"^remember\s+(?:that\s+)?(.+)$", t, re.I)
    if m and "forever" not in t.lower():
        # Let legacy brain remember path handle "remember my X is Y" — only catch freeform
        body = m.group(1).strip()
        if re.search(r"\b(my\s+\w+\s+is|that\s+as)\b", body, re.I):
            return None
        item = remember(body, kind=MemoryKind.SEMANTIC.value, title="Note")
        return f"Noted: {item.content[:120]}"

    low = t.lower()
    memory_q = bool(
        re.search(
            r"\b(what|which|where|when|who)\b.+\b(project|folder|app|website|working|yesterday|remember|memory)\b"
            r"|\bwhat\s+(?:was|were|did)\s+i\b"
            r"|\bwhat\s+folder\b"
            r"|\bwhat\s+project\b",
            low,
        )
    )
    if not memory_q and "remember" not in low:
        return None

    store = get_store()
    now = time.time()

    # Yesterday project
    if re.search(r"\bproject\b", low) and re.search(r"\byesterday\b", low):
        start = _day_start(now - 86400)
        end = start + 86400
        hits = store.search("project", kind=MemoryKind.PROJECT.value, since=start, until=end, limit=5)
        if not hits:
            hits = store.search("working", kind=MemoryKind.EPISODIC.value, since=start, until=end, limit=5)
        if hits:
            return _format_hits("Yesterday you were on", hits)
        return "I don't have a project memory from yesterday yet."

    if re.search(r"\bwhat\s+project\b|\bproject\s+was\s+i\b", low):
        hits = store.search("project", kind=MemoryKind.PROJECT.value, limit=5)
        if not hits:
            hits = store.search(t, kind=MemoryKind.EPISODIC.value, limit=5)
        if hits:
            return _format_hits("Recent projects", hits)
        return "No project memories yet."

    if re.search(r"\bfolder\b", low):
        hits = store.search("folder", kind=MemoryKind.DESKTOP.value, limit=5)
        # Also pull learning engine favorites
        try:
            from neuron.learning_engine import favorites
            fav = favorites("folder", limit=3)
            if fav:
                names = ", ".join(f["key"] for f in fav)
                extra = f" Frequent folders (learned): {names}."
            else:
                extra = ""
        except Exception:
            extra = ""
        if hits:
            return _format_hits("Folders I remember", hits) + extra
        if extra:
            return extra.strip()
        return "I haven't stored a folder memory yet."

    if re.search(r"\byesterday\b", low):
        start = _day_start(now - 86400)
        end = start + 86400
        hits = store.search(t, since=start, until=end, limit=8)
        if hits:
            return _format_hits("From yesterday", hits)
        return "Nothing memorable logged for yesterday."

    hits = store.search(t, limit=8)
    if hits:
        return _format_hits("Here's what I remember", hits)

    # Fall back to learning engine snapshot
    try:
        from neuron.learning_engine import for_prompt
        blob = for_prompt()
        if blob:
            return "From learned habits:\n" + blob
    except Exception:
        pass
    return "I don't have that in long-term memory yet."


def _day_start(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))


def _format_hits(header: str, hits: list[MemoryItem]) -> str:
    lines = [header + ":"]
    for h in hits[:5]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(h.created_at))
        pin = " [pinned]" if h.pinned else ""
        lines.append(f"- ({when}){pin} {h.title + ': ' if h.title else ''}{h.content[:180]}")
    return "\n".join(lines)


def for_prompt(*, limit: int = 6) -> str:
    if not enabled():
        return ""
    store = get_store()
    maintain()  # opportunistic GC
    items = sorted(
        store.all(),
        key=lambda i: store.effective_value(i),
        reverse=True,
    )[:limit]
    if not items:
        return ""
    lines = ["[long_term_memory]"]
    for i in items:
        pin = "*" if i.pinned else ""
        lines.append(f"- ({i.kind}){pin} {i.content[:140]}")
    return "\n".join(lines)


def ingest_from_learning() -> int:
    """Promote top learning-engine favorites into preference/desktop memory."""
    n = 0
    try:
        from neuron.learning_engine import favorites
        for cat, kind in (
            ("app", MemoryKind.DESKTOP.value),
            ("folder", MemoryKind.DESKTOP.value),
            ("website", MemoryKind.PREFERENCE.value),
            ("editor", MemoryKind.PREFERENCE.value),
            ("browser", MemoryKind.PREFERENCE.value),
        ):
            for fav in favorites(cat, limit=3):
                remember(
                    f"favorite_{cat}: {fav['key']} (score={fav.get('score')})",
                    kind=kind,
                    title=f"fav_{cat}",
                    tags=["learned", cat],
                    value=1.0 + float(fav.get("score") or 0),
                    meta={"source": "learning_engine", "category": cat},
                )
                n += 1
    except Exception:
        pass
    return n


def snapshot() -> dict[str, Any]:
    store = get_store()
    return {
        "stats": store.stats(),
        "pinned": [i.to_dict() for i in store.all() if i.pinned][:10],
        "recent_episodic": [i.to_dict() for i in sorted(store.all(MemoryKind.EPISODIC.value), key=lambda x: -x.created_at)[:5]],
        "recent_projects": [i.to_dict() for i in sorted(store.all(MemoryKind.PROJECT.value), key=lambda x: -x.created_at)[:5]],
    }


def tool_memory_status(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    maintain()
    return ok("Long-term memory status.", state=snapshot(), method="memory_engine")
