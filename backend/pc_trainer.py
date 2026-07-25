"""PC inventory + background training for N.E.U.R.O.N.

When the user says "learn my computer" / "learn every app", NEURON:
1) Scans installed apps (Start Menu + App Paths) and important folders
2) Saves a durable inventory under pc_inventory.json
3) Writes lightweight how-to stubs so open_app knows real names
4) Optionally deep-learns priority apps in the background (slow, non-blocking)

This is the path to JARVIS-like efficiency: know what's on the machine
BEFORE the user asks, instead of dumping phrases into Windows Search.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import winreg
from datetime import datetime
from pathlib import Path

STORE = Path(__file__).resolve().parent / "pc_inventory.json"
APP_MEMORY = Path(__file__).resolve().parent / "app_memory"

_lock = threading.Lock()
_state = {
    "running": False,
    "phase": "idle",
    "scanned_apps": 0,
    "scanned_folders": 0,
    "learned": 0,
    "queued": 0,
    "last_error": "",
    "started": "",
    "finished": "",
}


def status() -> dict:
    with _lock:
        return dict(_state)


def status_report() -> str:
    s = status()
    if s["running"]:
        return (
            f"Still training my PC map — phase {s['phase']}. "
            f"Found {s['scanned_apps']} apps and {s['scanned_folders']} folders; "
            f"deep-learned {s['learned']} so far"
            + (f", {s['queued']} waiting" if s.get("queued") else "")
            + "."
        )
    if not STORE.exists():
        return (
            "I haven't mapped your PC yet. Say 'learn my computer' and I'll "
            "inventory apps and folders in the background."
        )
    data = load_inventory() or {}
    apps = len(data.get("apps") or [])
    folders = len(data.get("folders") or [])
    learned = 0
    try:
        learned = len(list(APP_MEMORY.glob("*.json")))
    except Exception:
        pass
    return (
        f"I know {apps} installed apps and {folders} key folders on this PC, "
        f"plus {learned} deep app memories. Say 'learn my computer' to refresh."
    )


def load_inventory() -> dict | None:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_inventory(data: dict) -> Path:
    data = dict(data)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return STORE


def _special_folders() -> dict[str, str]:
    out = {}
    names = {
        "Desktop": "desktop",
        "Personal": "documents",
        "{374DE290-123F-4565-9164-39C4925E467B}": "downloads",
        "My Pictures": "pictures",
        "My Music": "music",
        "My Video": "videos",
    }
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as key:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                slug = names.get(name)
                if slug and isinstance(val, str) and os.path.isdir(val):
                    out[slug] = val
    except Exception:
        pass
    home = Path.home()
    defaults = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
    }
    for k, p in defaults.items():
        if k not in out and p.is_dir():
            out[k] = str(p)
    return out


def _start_menu_roots() -> list[Path]:
    roots = []
    for env in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        p = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if p.is_dir():
            roots.append(p)
    return roots


def _resolve_lnk(path: Path) -> tuple[str, str]:
    """Return (display_name, target_exe). Prefer fast name-only; resolve target lazily."""
    return path.stem, ""


def scan_apps(limit: int = 250) -> list[dict]:
    """Discover installed apps from Start Menu shortcuts + App Paths registry."""
    found: dict[str, dict] = {}

    def add(name: str, exe: str = "", source: str = ""):
        key = re.sub(r"\s+", " ", (name or "").strip().lower())
        if not key or len(key) < 2:
            return
        bad = (
            "uninstall", "readme", "help", "documentation", "release notes",
            "eula", "license", "update", "setup", "install ",
        )
        if any(b in key for b in bad):
            return
        if key in found and found[key].get("exe") and not exe:
            return
        found[key] = {
            "name": name.strip(),
            "alias": key,
            "exe": exe or found.get(key, {}).get("exe", ""),
            "source": source or found.get(key, {}).get("source", ""),
        }

    try:
        import actions
        for alias, target in actions.APPS.items():
            add(alias, str(target), "builtin")
    except Exception:
        pass

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(
                hive,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            ) as root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            exe, _ = winreg.QueryValueEx(k, None)
                    except Exception:
                        continue
                    stem = Path(sub).stem
                    add(stem, str(exe), "app_paths")
        except Exception:
            continue

    for root in _start_menu_roots():
        try:
            for lnk in root.rglob("*.lnk"):
                if len(found) >= limit:
                    break
                try:
                    name, target = _resolve_lnk(lnk)
                    add(name, target, "start_menu")
                except Exception:
                    add(lnk.stem, "", "start_menu")
        except Exception:
            continue

    return sorted(found.values(), key=lambda a: a["alias"])[:limit]


def scan_folders(max_children: int = 40) -> list[dict]:
    """Map important user folders + top-level children for voice open."""
    out = []
    specials = _special_folders()
    for slug, path in specials.items():
        entry = {
            "name": slug,
            "path": path,
            "kind": "special",
            "children": [],
        }
        try:
            kids = []
            for child in sorted(Path(path).iterdir(), key=lambda p: p.name.lower()):
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    kids.append({"name": child.name, "path": str(child), "kind": "folder"})
                if len(kids) >= max_children:
                    break
            entry["children"] = kids
        except Exception:
            pass
        out.append(entry)

    try:
        home = Path.home()
        for child in sorted(home.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.lower() in {s.lower() for s in specials}:
                continue
            if child.name.lower() in ("appdata", "application data", "local settings"):
                continue
            out.append({
                "name": child.name,
                "path": str(child),
                "kind": "home",
                "children": [],
            })
    except Exception:
        pass
    return out


def _write_inventory_stub(app: dict):
    """Lightweight app memory so planner/open_app know the app exists."""
    APP_MEMORY.mkdir(exist_ok=True)
    alias = app.get("alias") or app.get("name", "app")
    slug = re.sub(r"[^a-z0-9]+", "-", alias.lower()).strip("-")[:60] or "app"
    path = APP_MEMORY / f"{slug}.json"
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("voice_commands") and not old.get("inventory_only"):
                return
        except Exception:
            pass
    data = {
        "name": app.get("name") or alias,
        "kind": "desktop_app",
        "summary": f"Installed desktop app '{app.get('name')}'. Launch with open_app.",
        "preferred_action": "open_app",
        "voice_commands": [
            {"say": f"open {alias}", "do": f"open_app {alias}"},
            {"say": f"launch {alias}", "do": f"open_app {alias}"},
            {"say": f"close {alias}", "do": f"close_app {alias}"},
        ],
        "notes": "From PC inventory. Deep UI learn happens when the app is opened/focused.",
        "exe": app.get("exe") or "",
        "inventory_only": True,
        "auto": True,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "slug": slug,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_apps_with_actions(apps: list[dict]):
    """Teach open_app short aliases discovered on this PC."""
    try:
        import actions
    except Exception:
        return
    web_block = set(getattr(actions, "WEB_SERVICES", {}) or {})
    web_block.update({"yt", "youtube", "gmail", "maps", "google maps"})
    for app in apps:
        alias = (app.get("alias") or "").strip().lower()
        exe = (app.get("exe") or "").strip()
        if not alias or len(alias) > 40:
            continue
        if alias in actions.APPS:
            continue
        # Never register websites as desktop apps (causes Win Search disasters).
        if alias in web_block or any(w in alias for w in ("youtube", "gmail.com", "http")):
            continue
        if exe and exe.lower().endswith(".exe") and os.path.isfile(exe):
            actions.APPS[alias] = exe
        elif len(alias.split()) <= 3 and not any(
            w in alias for w in ("account", "login", "search", "open the")
        ):
            actions.APPS[alias] = alias


def inventory_for_prompt(hint: str = "") -> str:
    data = load_inventory()
    if not data:
        return ""
    apps = data.get("apps") or []
    folders = data.get("folders") or []
    hint_l = (hint or "").lower()
    lines = ["PC INVENTORY (installed on this machine — prefer these over Windows Search):"]
    matched = [a for a in apps if any(
        tok and tok in hint_l for tok in re.split(r"[^a-z0-9]+", (a.get("alias") or ""))
    )]
    show = matched[:12] if matched else apps[:18]
    if show:
        lines.append("Apps: " + ", ".join(
            (a.get("name") or a.get("alias") or "") for a in show if a.get("name") or a.get("alias")
        ))
    flines = []
    for f in folders[:10]:
        name = f.get("name")
        if not name:
            continue
        kids = ", ".join(c.get("name", "") for c in (f.get("children") or [])[:6])
        if hint_l and name.lower() not in hint_l and f.get("kind") != "special":
            if not any((c.get("name") or "").lower() in hint_l for c in (f.get("children") or [])[:8]):
                continue
        flines.append(f"{name}" + (f" [{kids}]" if kids else ""))
    if flines:
        lines.append("Folders: " + "; ".join(flines[:8]))
    lines.append(
        "Use open_app {short name} / open_folder {desktop|documents|downloads|...}. "
        "Never Windows Search for task phrases."
    )
    return "\n".join(lines)


def _priority_apps(apps: list[dict]) -> list[dict]:
    """Apps worth deep-learning first (common daily tools)."""
    priority_keys = (
        "steam", "chrome", "edge", "firefox", "spotify", "discord", "slack",
        "code", "cursor", "notepad", "word", "excel", "powerpoint", "outlook",
        "whatsapp", "telegram", "obs", "vlc", "photoshop", "figma", "notion",
        "explorer", "calculator", "paint", "terminal", "cmd",
    )
    ranked = []
    for a in apps:
        alias = (a.get("alias") or "").lower()
        score = 0
        for i, key in enumerate(priority_keys):
            if key in alias:
                score = 100 - i
                break
        if score:
            ranked.append((score, a))
    ranked.sort(key=lambda x: -x[0])
    seen = set()
    out = []
    for _, a in ranked:
        al = a.get("alias")
        if al in seen:
            continue
        seen.add(al)
        out.append(a)
    return out[:20]


def _deep_learn_worker(apps: list[dict]):
    import app_learner
    with _lock:
        _state["queued"] = len(apps)
        _state["phase"] = "deep_learn"
    for app in apps:
        with _lock:
            if not _state["running"]:
                break
            _state["queued"] = max(0, _state["queued"] - 1)
        alias = app.get("alias") or app.get("name") or ""
        try:
            if app_learner._fresh_enough(alias, hours=72):
                continue
            print(f"[pc_trainer] deep-learning {alias}…", flush=True)
            msg = app_learner.learn_app(
                alias, auto=True, open_if_needed=True, force=False
            )
            print(f"[pc_trainer] {msg}", flush=True)
            with _lock:
                _state["learned"] += 1
            time.sleep(4.0)
        except Exception as exc:
            with _lock:
                _state["last_error"] = str(exc)
            print(f"[pc_trainer] learn failed for {alias}: {exc}", flush=True)
            time.sleep(1.0)
    with _lock:
        _state["running"] = False
        _state["phase"] = "done"
        _state["finished"] = datetime.now().isoformat(timespec="seconds")
    print("[pc_trainer] background training finished", flush=True)


def start_training(*, deep_learn: bool = True) -> str:
    """Kick off inventory (+ optional deep learn). Non-blocking spoken reply."""
    with _lock:
        if _state["running"]:
            return status_report()
        _state.update({
            "running": True,
            "phase": "scan",
            "scanned_apps": 0,
            "scanned_folders": 0,
            "learned": 0,
            "queued": 0,
            "last_error": "",
            "started": datetime.now().isoformat(timespec="seconds"),
            "finished": "",
        })

    def worker():
        try:
            print("[pc_trainer] scanning apps + folders…", flush=True)
            apps = scan_apps()
            folders = scan_folders()
            save_inventory({
                "apps": apps,
                "folders": folders,
                "deep_learn": deep_learn,
            })
            register_apps_with_actions(apps)
            for app in apps:
                try:
                    _write_inventory_stub(app)
                except Exception:
                    pass
            with _lock:
                _state["scanned_apps"] = len(apps)
                _state["scanned_folders"] = len(folders)
                _state["phase"] = "inventory_saved"
            print(
                f"[pc_trainer] inventory saved: {len(apps)} apps, {len(folders)} folders",
                flush=True,
            )
            if deep_learn:
                pri = _priority_apps(apps)
                _deep_learn_worker(pri)
            else:
                with _lock:
                    _state["running"] = False
                    _state["phase"] = "done"
                    _state["finished"] = datetime.now().isoformat(timespec="seconds")
        except Exception as exc:
            with _lock:
                _state["running"] = False
                _state["phase"] = "error"
                _state["last_error"] = str(exc)
            print(f"[pc_trainer] failed: {exc}", flush=True)

    threading.Thread(target=worker, daemon=True, name="pc-trainer").start()
    return (
        "On it. I'll map every app and important folder on this PC in the background — "
        "it takes a while. Meanwhile you can keep talking to me; say 'training status' "
        "anytime. After that I'll handle opens and workflows much more efficiently."
    )


def stop_training() -> str:
    with _lock:
        if not _state["running"]:
            return "I'm not training right now."
        _state["running"] = False
        _state["phase"] = "stopping"
    return "Stopping background PC training after the current step."


def bootstrap_on_startup():
    """Load existing inventory aliases into open_app at server boot."""
    data = load_inventory()
    if not data:
        return
    try:
        register_apps_with_actions(data.get("apps") or [])
        print(
            f"[pc_trainer] loaded inventory "
            f"({len(data.get('apps') or [])} apps, {len(data.get('folders') or [])} folders)",
            flush=True,
        )
    except Exception as exc:
        print(f"[pc_trainer] bootstrap failed: {exc}", flush=True)
