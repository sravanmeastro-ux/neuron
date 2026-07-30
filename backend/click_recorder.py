"""Optional click / key workflow recorder for N.E.U.R.O.N.

NOT always-on. Recording starts only when you say so, e.g.:
  "start recording clicks"
  "stop recording" / "save that as open friends"
  "replay open friends"

Each step prefers UI Automation identity (name, type, automationId)
over raw pixels so replays survive window moves better.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

STORE = Path(__file__).resolve().parent / "click_recipes.json"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_lock = threading.Lock()
_thread: threading.Thread | None = None
_recording = False
_session: dict = {}
_last_saved: dict = {}
_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("click_record", {}) or {}
    except Exception:
        return {}


def is_feature_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _max_steps() -> int:
    return max(5, int(_cfg().get("max_steps", 40) or 40))


def _poll_ms() -> float:
    return max(0.03, float(_cfg().get("poll_seconds", 0.05) or 0.05))


def _store_pixels() -> bool:
    return bool(_cfg().get("store_pixels", True))


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"recipes": [], "updated": ""}


def _save(data: dict) -> None:
    data = dict(data)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "workflow")[:48]


def is_recording() -> bool:
    return _recording


def status() -> str:
    if _recording:
        n = len(_session.get("steps") or [])
        app = _session.get("app") or "unknown"
        return f"Recording ({n} steps, app={app}). Say 'stop recording' when done."
    n = len(_load().get("recipes") or [])
    return f"Not recording. {n} saved click recipes. Say 'start recording clicks' to teach a workflow."


def _cursor_pos():
    import ctypes
    from ctypes import wintypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _foreground_app() -> tuple[str, str]:
    """Return (process_stem, window_title)."""
    try:
        import uiautomation as auto
        fg = auto.GetForegroundControl()
        if not fg:
            return "", ""
        title = (fg.Name or "").strip()
        try:
            pid = fg.ProcessId
            import psutil
            name = psutil.Process(pid).name()
            stem = Path(name).stem.lower()
        except Exception:
            stem = ""
        return stem, title
    except Exception:
        return "", ""


def _element_at(x: int, y: int) -> dict:
    info = {
        "name": "",
        "control_type": "",
        "automation_id": "",
        "class_name": "",
        "rect": None,
    }
    try:
        import uiautomation as auto
        ctrl = auto.ControlFromPoint(x, y)
        if not ctrl:
            return info
        info["name"] = (ctrl.Name or "").strip()[:120]
        try:
            info["control_type"] = str(ctrl.ControlTypeName or "")
        except Exception:
            pass
        try:
            info["automation_id"] = (ctrl.AutomationId or "").strip()[:120]
        except Exception:
            pass
        try:
            info["class_name"] = (ctrl.ClassName or "").strip()[:80]
        except Exception:
            pass
        try:
            r = ctrl.BoundingRectangle
            if r:
                info["rect"] = {
                    "left": int(r.left),
                    "top": int(r.top),
                    "right": int(r.right),
                    "bottom": int(r.bottom),
                }
        except Exception:
            pass
    except Exception:
        pass
    return info


def _window_rect() -> dict | None:
    try:
        import uiautomation as auto
        fg = auto.GetForegroundControl()
        if not fg:
            return None
        r = fg.BoundingRectangle
        if not r:
            return None
        return {
            "left": int(r.left),
            "top": int(r.top),
            "right": int(r.right),
            "bottom": int(r.bottom),
        }
    except Exception:
        return None


def _relative(x: int, y: int, win: dict | None) -> dict | None:
    if not win:
        return None
    w = max(1, win["right"] - win["left"])
    h = max(1, win["bottom"] - win["top"])
    return {
        "rx": round((x - win["left"]) / w, 4),
        "ry": round((y - win["top"]) / h, 4),
    }


def _ignore_app(stem: str, title: str) -> bool:
    blob = f"{stem} {title}".lower()
    skip = ("neuron", "n.e.u.r.o.n", "program manager", "cursor")
    return any(s in blob for s in skip)


def _append_step(button: str, x: int, y: int) -> None:
    app, title = _foreground_app()
    if _ignore_app(app, title):
        return
    el = _element_at(x, y)
    win = _window_rect()
    step = {
        "t": time.time(),
        "button": button,
        "app": app,
        "title": title[:120],
        "element": el,
        "rel": _relative(x, y, win),
    }
    if _store_pixels():
        step["x"] = x
        step["y"] = y
    with _lock:
        steps = _session.setdefault("steps", [])
        if len(steps) >= _max_steps():
            return
        # Debounce identical rapid double-fires on same element
        if steps:
            prev = steps[-1]
            if (
                prev.get("button") == button
                and prev.get("element", {}).get("name") == el.get("name")
                and prev.get("element", {}).get("automation_id") == el.get("automation_id")
                and abs(float(prev.get("t", 0)) - step["t"]) < 0.18
            ):
                return
        steps.append(step)
        if app and not _session.get("app"):
            _session["app"] = app
        elif app:
            _session["app"] = app


def _loop() -> None:
    global _recording
    left_was = False
    right_was = False
    while _recording:
        try:
            left = _key_down(_VK_LBUTTON)
            right = _key_down(_VK_RBUTTON)
            if left and not left_was:
                x, y = _cursor_pos()
                _append_step("left", x, y)
            if right and not right_was:
                x, y = _cursor_pos()
                _append_step("right", x, y)
            left_was = left
            right_was = right
        except Exception as exc:
            print(f"[click_recorder] {exc}", flush=True)
        time.sleep(_poll_ms())


def start(label: str = "") -> str:
    """Begin a recording session."""
    global _recording, _thread, _session
    if not is_feature_enabled():
        return "Click recording is disabled in config."
    if _recording:
        n = len(_session.get("steps") or [])
        return f"Already recording ({n} steps). Say 'stop recording' when finished."
    _session = {
        "label": (label or "").strip(),
        "app": "",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": [],
    }
    _recording = True
    _thread = threading.Thread(target=_loop, name="click-recorder", daemon=True)
    _thread.start()
    return (
        "Recording your clicks. Do the workflow with the mouse, then say "
        "'stop recording' or 'remember that as …'."
    )


def stop(name: str = "") -> str:
    """Stop recording and optionally save under a name."""
    global _recording, _last_saved
    if not _recording and not _session.get("steps"):
        return "I wasn't recording. Say 'start recording clicks' first."
    _recording = False
    time.sleep(_poll_ms() * 2)
    steps = list(_session.get("steps") or [])
    if not steps:
        return "Recording stopped — no clicks captured."
    label = (name or _session.get("label") or "").strip()
    if not label:
        label = f"{_session.get('app') or 'app'} workflow"
    recipe = {
        "id": _slug(label) + "-" + str(int(time.time()) % 100000),
        "say": _slug(label).replace("-", " "),
        "label": label,
        "app": _session.get("app") or "",
        "steps": steps,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    data = _load()
    recipes = data.setdefault("recipes", [])
    # Replace same say-text
    say_n = re.sub(r"\s+", " ", recipe["say"].lower()).strip()
    recipes = [r for r in recipes if re.sub(r"\s+", " ", (r.get("say") or "").lower()).strip() != say_n]
    recipes.append(recipe)
    data["recipes"] = recipes[-80:]
    _save(data)
    _last_saved = recipe
    _session["steps"] = []
    # Also bind a voice recipe so the phrase reuses replay.
    try:
        import voice_recipes
        voice_recipes.remember(recipe["say"], "replay_clicks", {"id": recipe["id"]}, app=recipe.get("app") or "")
        voice_recipes.note_success(recipe["say"], "replay_clicks", {"id": recipe["id"]})
    except Exception:
        pass
    return (
        f"Saved {len(steps)} clicks as '{recipe['say']}'. "
        f"Say that phrase anytime, or 'replay {recipe['say']}'."
    )


def cancel() -> str:
    global _recording, _session
    was = _recording
    _recording = False
    _session = {"steps": []}
    return "Recording cancelled." if was else "Nothing to cancel."


def last_saved() -> dict:
    return dict(_last_saved)


def find_recipe(query: str) -> dict | None:
    q = re.sub(r"[^\w\s]", " ", (query or "").lower())
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return None
    recipes = _load().get("recipes") or []
    for r in recipes:
        if (r.get("id") or "") == q:
            return r
    for r in recipes:
        say = re.sub(r"\s+", " ", (r.get("say") or "").lower()).strip()
        if say == q or say in q or q in say:
            return r
    for r in recipes:
        label = re.sub(r"\s+", " ", (r.get("label") or "").lower()).strip()
        if label and (label == q or label in q):
            return r
    return None


def list_recipes(limit: int = 12) -> str:
    rows = _load().get("recipes") or []
    if not rows:
        return "No click recipes yet. Say 'start recording clicks' to teach one."
    lines = []
    for r in rows[-limit:]:
        n = len(r.get("steps") or [])
        lines.append(f"- {r.get('say')} ({n} clicks, app={r.get('app') or '?'})")
    return "Click recipes:\n" + "\n".join(lines)


def _click_xy(x: int, y: int, button: str = "left") -> None:
    import pyautogui
    pyautogui.click(x, y, button=button)


def _find_control(step: dict):
    el = step.get("element") or {}
    name = (el.get("name") or "").strip()
    aid = (el.get("automation_id") or "").strip()
    ctype = (el.get("control_type") or "").strip()
    if not name and not aid:
        return None
    try:
        import uiautomation as auto
        fg = auto.GetForegroundControl()
        if not fg:
            return None
        # Prefer AutomationId when present
        if aid:
            try:
                c = fg.Control(AutomationId=aid, searchDepth=12)
                if c and c.Exists(0, 0):
                    return c
            except Exception:
                pass
        if name:
            kwargs = {"Name": name, "searchDepth": 12}
            if ctype and ctype.endswith("Control"):
                # ControlTypeName like "ButtonControl" — try Name only first
                pass
            try:
                c = fg.Control(**kwargs)
                if c and c.Exists(0, 0):
                    return c
            except Exception:
                pass
            # Walk a shallow tree for fuzzy name
            try:
                for ctrl in fg.GetChildren():
                    try:
                        if (ctrl.Name or "").strip() == name:
                            return ctrl
                        for child in ctrl.GetChildren()[:40]:
                            if (child.Name or "").strip() == name:
                                return child
                    except Exception:
                        continue
            except Exception:
                pass
    except Exception:
        return None
    return None


def _focus_app(app: str) -> None:
    if not app:
        return
    try:
        import actions
        actions.open_app(app, auto_learn=False)
        time.sleep(0.8)
    except Exception:
        pass


def replay(query: str = "", recipe_id: str = "") -> str:
    """Replay a saved click recipe by phrase or id."""
    if _recording:
        return "Still recording — say 'stop recording' first."
    recipe = None
    if recipe_id:
        recipe = find_recipe(recipe_id)
    if not recipe and query:
        # Strip common prefixes
        q = re.sub(
            r"^(?:replay|play back|do|run)\s+(?:the\s+)?(?:recording|recipe|clicks?)?\s*",
            "",
            (query or "").lower(),
        ).strip()
        recipe = find_recipe(q) or find_recipe(query)
    if not recipe and _last_saved:
        recipe = _last_saved
    if not recipe:
        return "I don't have that click recipe. Say 'list click recipes' or record one first."

    steps = recipe.get("steps") or []
    if not steps:
        return "That recipe has no steps."

    app = recipe.get("app") or (steps[0].get("app") if steps else "")
    _focus_app(app)

    done = 0
    for step in steps:
        button = step.get("button") or "left"
        # Prefer UIA control click
        ctrl = _find_control(step)
        if ctrl is not None:
            try:
                if button == "right":
                    ctrl.RightClick()
                else:
                    ctrl.Click()
                done += 1
                time.sleep(0.35)
                continue
            except Exception:
                pass
        # Relative window coords
        rel = step.get("rel")
        if rel:
            win = _window_rect()
            if win:
                w = max(1, win["right"] - win["left"])
                h = max(1, win["bottom"] - win["top"])
                x = int(win["left"] + float(rel["rx"]) * w)
                y = int(win["top"] + float(rel["ry"]) * h)
                try:
                    _click_xy(x, y, button)
                    done += 1
                    time.sleep(0.35)
                    continue
                except Exception:
                    pass
        # Absolute pixels last resort
        if "x" in step and "y" in step:
            try:
                _click_xy(int(step["x"]), int(step["y"]), button)
                done += 1
                time.sleep(0.35)
            except Exception:
                pass

    label = recipe.get("say") or recipe.get("label") or "workflow"
    if done == 0:
        # Vision fallback for whole goal
        try:
            import vision_agent
            if vision_agent and vision_agent.is_enabled():
                return vision_agent.computer_use(
                    f"Replay this workflow in {app or 'the app'}: {label}"
                )
        except Exception:
            pass
        return f"Couldn't replay '{label}' — UI may have changed."
    return f"Replayed '{label}' ({done}/{len(steps)} clicks)."
