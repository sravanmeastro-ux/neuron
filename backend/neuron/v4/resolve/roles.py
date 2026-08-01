"""Role normalization for V4.3 — preserve raw role, expose semantic category."""

from __future__ import annotations

import re

# semantic role → compatible raw/source tokens
_ROLE_GROUPS: dict[str, frozenset[str]] = {
    "button": frozenset({
        "button", "pushbutton", "splitbutton", "btn", "menuitem", "menu_item",
    }),
    "link": frozenset({"link", "hyperlink", "a"}),
    "text_field": frozenset({
        "text_field", "textbox", "edit", "input", "searchbox", "search_box",
        "document", "combobox", "combo",
    }),
    "search_box": frozenset({
        "search_box", "searchbox", "search", "text_field", "edit", "textbox",
    }),
    "tab": frozenset({"tab", "tabitem"}),
    "video": frozenset({"video", "browser_result", "list_item", "link"}),
    "browser_result": frozenset({"browser_result", "video", "list_item", "link", "result"}),
    "menu_item": frozenset({"menu_item", "menuitem", "menu"}),
    "checkbox": frozenset({"checkbox", "check"}),
    "dropdown": frozenset({"dropdown", "combobox", "combo", "list"}),
    "window": frozenset({"window", "pane"}),
    "close_button": frozenset({"button", "pushbutton"}),
    "play_button": frozenset({"button", "pushbutton"}),
    "pause_button": frozenset({"button", "pushbutton"}),
    "fullscreen_button": frozenset({"button", "pushbutton"}),
    "minimize_button": frozenset({"button", "pushbutton"}),
    "maximize_button": frozenset({"button", "pushbutton"}),
    "address_bar": frozenset({"text_field", "edit", "textbox", "document"}),
}

_PHRASE_TO_ROLE = (
    ("search box", "search_box"),
    ("search field", "search_box"),
    ("search bar", "search_box"),
    ("address bar", "address_bar"),
    ("url bar", "address_bar"),
    ("play button", "play_button"),
    ("pause button", "pause_button"),
    ("fullscreen button", "fullscreen_button"),
    ("full screen button", "fullscreen_button"),
    ("close button", "close_button"),
    ("minimize button", "minimize_button"),
    ("maximize button", "maximize_button"),
    ("text field", "text_field"),
    ("text box", "text_field"),
    ("menu item", "menu_item"),
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def normalize_role(raw: str) -> str:
    """Map raw UIA/source role string → semantic role token."""
    r = _norm(raw).replace("control", "").replace(" ", "_").strip("_")
    if not r:
        return "other"
    for sem, group in _ROLE_GROUPS.items():
        if r in group or r == sem:
            return sem
    if "button" in r:
        return "button"
    if "edit" in r or "text" in r:
        return "text_field"
    if "link" in r or "hyper" in r:
        return "link"
    if "tab" in r:
        return "tab"
    if "check" in r:
        return "checkbox"
    if "menu" in r:
        return "menu_item"
    if "combo" in r or "list" in r:
        return "dropdown"
    if "window" in r or "pane" in r:
        return "window"
    return r or "other"


def roles_compatible(wanted: str, candidate_raw_or_norm: str) -> bool:
    w = normalize_role(wanted)
    c = normalize_role(candidate_raw_or_norm)
    if w == c:
        return True
    group = _ROLE_GROUPS.get(w)
    if group and (c in group or normalize_role(c) == w):
        return True
    # search_box accepts text_field candidates that look searchable (caller filters name)
    if w == "search_box" and c in ("text_field", "search_box", "edit", "textbox"):
        return True
    if w in ("video", "browser_result") and c in ("video", "browser_result", "link", "list_item"):
        return True
    return False


def parse_role_from_text(text: str) -> str | None:
    t = _norm(text)
    for phrase, role in _PHRASE_TO_ROLE:
        if phrase in t:
            return role
    m = re.search(
        r"\b(videos?|results?|buttons?|links?|tabs?|windows?|menus?|"
        r"checkbox(?:es)?|dropdowns?|textbox(?:es)?|inputs?|searchbox)\b",
        t,
        re.I,
    )
    if not m:
        return None
    tok = m.group(1).lower()
    mapping = {
        "video": "video",
        "videos": "video",
        "result": "browser_result",
        "results": "browser_result",
        "button": "button",
        "buttons": "button",
        "link": "link",
        "links": "link",
        "tab": "tab",
        "tabs": "tab",
        "window": "window",
        "windows": "window",
        "menu": "menu_item",
        "menus": "menu_item",
        "checkbox": "checkbox",
        "checkboxes": "checkbox",
        "dropdown": "dropdown",
        "dropdowns": "dropdown",
        "textbox": "text_field",
        "textboxes": "text_field",
        "input": "text_field",
        "inputs": "text_field",
        "searchbox": "search_box",
    }
    return mapping.get(tok)


def name_tokens_suggest_role(name: str, role_hint: str) -> float:
    """Extra score for name/role alignment (e.g. search box named Search)."""
    n = _norm(name)
    if not n:
        return 0.0
    if role_hint == "search_box" and "search" in n:
        return 0.35
    if role_hint == "address_bar" and any(x in n for x in ("address", "url", "omnibox", "location")):
        return 0.35
    if role_hint == "play_button" and "play" in n and "playlist" not in n:
        return 0.4
    if role_hint == "pause_button" and "pause" in n:
        return 0.4
    if role_hint == "fullscreen_button" and ("fullscreen" in n or "full screen" in n):
        return 0.4
    if role_hint == "close_button" and (n in ("close", "x") or n.endswith("close")):
        return 0.35
    if role_hint == "minimize_button" and "minimize" in n:
        return 0.4
    if role_hint == "maximize_button" and "maximize" in n:
        return 0.4
    if role_hint in ("video", "browser_result"):
        # Penalize chrome nav chrome
        if any(x in n for x in ("home", "shorts", "subscriptions", "library", "youtube", "logo")):
            return -0.5
        if len(n) >= 8:
            return 0.15
    return 0.0
