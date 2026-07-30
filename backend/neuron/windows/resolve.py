"""Natural application name resolution (aliases, processes, window titles)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken / casual names → canonical key
ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "googlechrome": "chrome",
    "browser": "chrome",
    "web browser": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "msedge": "edge",
    "firefox": "firefox",
    "mozilla": "firefox",
    "brave": "brave",
    "opera": "opera",
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "paint": "paint",
    "mspaint": "paint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "this pc": "explorer",
    "command prompt": "cmd",
    "cmd": "cmd",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "wt": "terminal",
    "powershell": "powershell",
    "settings": "settings",
    "windows settings": "settings",
    "task manager": "task manager",
    "taskmgr": "task manager",
    "word": "word",
    "microsoft word": "word",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpoint",
    "spotify": "spotify",
    "steam": "steam",
    "discord": "discord",
    "whatsapp": "whatsapp",
    "blender": "blender",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "code": "code",
    "cursor": "cursor",
    "cursor ide": "cursor",
}

PROCESS_NAMES: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "firefox": ("firefox.exe",),
    "brave": ("brave.exe",),
    "opera": ("opera.exe",),
    "notepad": ("notepad.exe",),
    "calculator": ("calculator.exe", "calc.exe"),
    "paint": ("mspaint.exe",),
    "explorer": ("explorer.exe",),
    "cmd": ("cmd.exe",),
    "terminal": ("windowsterminal.exe", "wt.exe"),
    "powershell": ("powershell.exe", "pwsh.exe"),
    "task manager": ("taskmgr.exe",),
    "word": ("winword.exe",),
    "excel": ("excel.exe",),
    "powerpoint": ("powerpnt.exe",),
    "spotify": ("spotify.exe",),
    "steam": ("steam.exe",),
    "discord": ("discord.exe",),
    "whatsapp": ("whatsapp.exe",),
    "blender": ("blender.exe",),
    "code": ("code.exe",),
    "cursor": ("cursor.exe",),
}

TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome", "google chrome"),
    "edge": ("edge", "microsoft edge"),
    "firefox": ("firefox", "mozilla"),
    "notepad": ("notepad",),
    "blender": ("blender",),
    "steam": ("steam",),
    "discord": ("discord",),
    "spotify": ("spotify",),
    "code": ("visual studio code",),
    "cursor": ("cursor",),
    "calculator": ("calculator",),
    "explorer": ("file explorer", "this pc", "quick access"),
    "whatsapp": ("whatsapp",),
    "word": ("word",),
    "excel": ("excel",),
    "opera": ("opera",),
    "terminal": ("windows terminal",),
    "settings": ("settings",),
}


@dataclass
class ResolvedApp:
    query: str
    canonical: str
    launch_target: str
    process_names: tuple[str, ...]
    title_hints: tuple[str, ...]
    confidence: float


def _clean(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"\b(the|app|application|program|window|please|open|launch|start)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip(" .!?,")
    return n


def resolve(name: str) -> ResolvedApp:
    query = _clean(name)
    if not query:
        return ResolvedApp("", "", "", (), (), 0.0)

    aliases = dict(ALIASES)
    try:
        import actions
        for k in (actions.APPS or {}):
            aliases.setdefault(str(k).lower(), str(k).lower())
    except Exception:
        pass

    # Prefer explicit APPS key when present (e.g. browser → msedge launch target)
    canonical = aliases.get(query, query)
    try:
        import actions
        if query in (actions.APPS or {}):
            canonical = query
        # Smart browser: prefer Chrome if installed, else Edge
        if query in ("browser", "web browser"):
            chrome = actions._resolve_exe("chrome") if hasattr(actions, "_resolve_exe") else None
            edge = actions._resolve_exe("msedge") if hasattr(actions, "_resolve_exe") else None
            if chrome:
                canonical = "chrome"
            elif edge:
                canonical = "edge"
            else:
                canonical = "chrome"
    except Exception:
        canonical = aliases.get(query, query)

    canonical = aliases.get(canonical, canonical)

    launch = canonical
    try:
        import actions
        launch = actions.APPS.get(canonical, actions.APPS.get(query, canonical))
    except Exception:
        pass

    procs = PROCESS_NAMES.get(canonical, (f"{canonical.replace(' ', '')}.exe",))
    hints = TITLE_HINTS.get(canonical, (canonical,))
    if query in ALIASES or query in ("browser", "web browser", "google chrome"):
        conf = 0.95
    elif query == canonical:
        conf = 0.55
    else:
        conf = 0.7
    return ResolvedApp(query, canonical, str(launch), procs, hints, conf)


def matches_window_title(resolved: ResolvedApp, title: str) -> bool:
    t = (title or "").lower()
    if not t or "n.e.u.r.o.n" in t or t.startswith("neuron"):
        return False
    for h in resolved.title_hints:
        if h and h in t:
            return True
    if resolved.canonical and resolved.canonical in t:
        return True
    if resolved.query and len(resolved.query) >= 3 and resolved.query in t:
        return True
    return False


def matches_process(resolved: ResolvedApp, proc_name: str) -> bool:
    p = (proc_name or "").lower()
    if not p:
        return False
    for n in resolved.process_names:
        if p == n.lower():
            return True
    base = resolved.canonical.replace(" ", "")
    return bool(base) and base in p.replace(".exe", "")
