"""V3.8 — semantic procedure sanitization + privacy for skill learning.

Skills are semantic procedures (open_file, wait_for_app, click_element by name),
never coordinate recordings. Scrubs passwords/tokens/credentials/private fields
and strips unnecessary screenshots / pixel crops.
"""

from __future__ import annotations

import re
from typing import Any

# Actions that are considered semantic / adaptive (survive window moves)
SEMANTIC_ACTIONS = frozenset({
    "open_app", "focus_app", "close_app", "launch_app",
    "wait", "wait_for_app",
    "click_element", "click_ui_element", "find_element", "find_ui_element",
    "browser_click", "browser_find_element", "browser_open", "browser_navigate",
    "browser_search", "open_website", "search_site", "search_web",
    "type_text", "press_keys", "hotkey",
    "open_file", "open_folder", "search_files", "find_file",
    "move_window_to_monitor", "move_window",
    "play_result", "skip_ad", "youtube_home", "ensure_playback",
    "blender.open", "blender.focus", "blender.open_project", "blender.new_file",
    "blender.start_render", "blender.trigger_render", "blender.verify_render",
    "run_procedure",
    "speak", "volume",
})

# Never persist these action types into learned skills
_BANNED_LEARN_ACTIONS = frozenset({
    "click",  # raw x,y
    "mouse_click",
    "drag",
    "capture_monitor",
    "capture_screen",
    "screenshot",
    "save_screenshot",
})

_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "credentials", "ssn", "credit", "cvv", "private_key",
    "auth", "authorization", "bearer", "session_id", "cookie",
})

_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token|credential|ssn|credit\s*card)"
    r"\s*[:=]\s*\S+"
)

_PRIVATE_FIELD_NAMES = re.compile(
    r"(?i)\b(password|passwd|pin|ssn|credit\s*card|cvv|otp|one[- ]time|"
    r"api[_-]?key|secret|token|credential)\b"
)


def is_sensitive_key(key: str) -> bool:
    k = (key or "").lower().replace("-", "_")
    return any(s in k for s in _SENSITIVE_KEYS)


def scrub_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, dict):
        return scrub_args(val)
    s = str(val)
    if _SENSITIVE_VALUE_RE.search(s) or _looks_secret(s):
        return "[redacted]"
    return val


def scrub_args(args: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if is_sensitive_key(str(k)):
            out[str(k)] = "[redacted]"
        else:
            out[str(k)] = scrub_value(v)
    return out


def _looks_secret(s: str) -> bool:
    low = (s or "").lower()
    if any(x in low for x in ("password=", "bearer ", "api_key=", "secret=")):
        return True
    digits = "".join(c for c in s if c.isdigit())
    return len(digits) >= 13 and len(digits) <= 19 and len(s) <= 24


def strip_media_fields(step: dict) -> dict:
    """Drop screenshots / pixel crops / absolute coords from a step dict."""
    drop_keys = {
        "screenshot", "image", "pixels", "png", "jpeg", "bmp",
        "crop", "bitmap", "frame", "thumbnail",
    }
    out = {}
    for k, v in step.items():
        if str(k).lower() in drop_keys:
            continue
        if str(k).lower() in ("x", "y") and step.get("action") in _BANNED_LEARN_ACTIONS | {"click"}:
            continue
        out[k] = v
    args = dict(out.get("args") or {})
    for k in list(args.keys()):
        if str(k).lower() in drop_keys or str(k).lower() in ("x", "y", "px", "py"):
            args.pop(k, None)
    out["args"] = args
    return out


def rejects_private_field(step: dict | str) -> bool:
    """True when a step would persist passwords, tokens, or private form fields."""
    if isinstance(step, str):
        return bool(_SENSITIVE_VALUE_RE.search(step) or _PRIVATE_FIELD_NAMES.search(step))

    action = str(step.get("action") or "")
    args = step.get("args") or {}
    target = str(step.get("target") or args.get("name") or "")
    text = str(args.get("text") or args.get("value") or args.get("content") or "")

    if any(is_sensitive_key(str(k)) and str(v) not in ("", "[redacted]") for k, v in args.items()):
        return True
    if _SENSITIVE_VALUE_RE.search(text) or _looks_secret(text):
        return True
    if action in ("type_text", "type", "paste", "fill", "set_value") and _PRIVATE_FIELD_NAMES.search(target):
        return True
    if action in ("type_text", "type", "paste") and _PRIVATE_FIELD_NAMES.search(text):
        return True
    return False


def is_coordinate_step(step: dict) -> bool:
    action = str(step.get("action") or step.get("tool") or "").strip().lower()
    if action in _BANNED_LEARN_ACTIONS:
        return True
    args = step.get("args") or {}
    if action in ("click", "mouse_click", "drag") and (
        args.get("x") is not None or args.get("y") is not None
    ):
        return True
    return False


def is_semantic_step(step: dict) -> bool:
    action = str(step.get("action") or step.get("tool") or "").strip()
    if not action or is_coordinate_step(step):
        return False
    base = action.split(".")[0] if "." in action else action
    if action in SEMANTIC_ACTIONS or base in SEMANTIC_ACTIONS:
        return True
    # Allow dotted domain skills that aren't click/coords
    if "." in action and action.split(".")[0] in (
        "blender", "youtube", "browser", "windows", "spotify", "discord", "files",
    ):
        return True
    return action not in _BANNED_LEARN_ACTIONS


def sanitize_steps(
    steps: list[dict],
    *,
    drop_coordinates: bool = True,
) -> tuple[list[dict], list[str]]:
    """
    Convert raw demonstration steps into adaptive semantic procedures.
    Returns (clean_steps, warnings).
    """
    clean: list[dict] = []
    warnings: list[str] = []
    for raw in steps or []:
        if not isinstance(raw, dict):
            continue
        step = strip_media_fields(dict(raw))
        action = str(step.get("action") or step.get("tool") or "").strip()
        if not action:
            continue
        if rejects_private_field(step):
            warnings.append(f"dropped private-field step ({action})")
            continue
        if drop_coordinates and is_coordinate_step(step):
            # Try to promote to click_element via name / automationId
            promoted = _promote_coordinate_step(step)
            if promoted:
                step = promoted
                warnings.append("promoted coordinate click → click_element")
            else:
                warnings.append(f"dropped non-adaptive coordinate step ({action})")
                continue
        if not is_semantic_step(step):
            warnings.append(f"dropped non-semantic step ({action})")
            continue
        args = scrub_args(dict(step.get("args") or {}))
        # Bind template placeholders stay as-is ({project})
        clean.append({
            "action": action,
            "args": args,
            "target": step.get("target") or "",
            "expected_result": step.get("expected_result") or step.get("expect") or "",
        })
    return clean, warnings


def _promote_coordinate_step(step: dict) -> dict | None:
    """If a raw click has UIA name/automationId, rewrite as click_element."""
    el = step.get("element") or {}
    args = step.get("args") or {}
    name = (
        (el.get("name") if isinstance(el, dict) else None)
        or args.get("name")
        or args.get("text")
        or step.get("target")
        or ""
    )
    name = str(name).strip()
    auto_id = ""
    if isinstance(el, dict):
        auto_id = str(el.get("automationId") or el.get("automation_id") or "").strip()
    if name and len(name) >= 2 and not _PRIVATE_FIELD_NAMES.search(name):
        return {
            "action": "click_element",
            "args": {"name": name},
            "target": name,
            "expected_result": f"clicked {name}",
        }
    if auto_id and len(auto_id) >= 2:
        return {
            "action": "click_element",
            "args": {"name": auto_id, "automation_id": auto_id},
            "target": auto_id,
            "expected_result": f"clicked {auto_id}",
        }
    return None


def bind_params(steps: list[dict], params: dict[str, Any] | None) -> list[dict]:
    """Substitute {param} placeholders in step args/targets."""
    if not params:
        return [dict(s) for s in steps]
    out = []
    for s in steps:
        step = dict(s)
        args = dict(step.get("args") or {})
        for k, v in list(args.items()):
            if isinstance(v, str):
                args[k] = _subst(v, params)
        step["args"] = args
        if isinstance(step.get("target"), str):
            step["target"] = _subst(step["target"], params)
        if isinstance(step.get("expected_result"), str):
            step["expected_result"] = _subst(step["expected_result"], params)
        out.append(step)
    return out


def _subst(text: str, params: dict[str, Any]) -> str:
    out = text
    for k, v in params.items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out
