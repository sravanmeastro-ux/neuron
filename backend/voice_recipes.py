"""Voice recipe memory — learn how the user talks about controlling apps.

Inventory knows *which* apps exist. Recipes know *how* to act on a phrase:
  "open friends chat" → open Discord DMs / friends
  "open steam friends" → steam_goto friends

Recipes grow when:
  - built-in seeds match
  - a command succeeds and we auto-save the phrase
  - the user says "remember that as …" / "when I say X, do that"
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

STORE = Path(__file__).resolve().parent / "voice_recipes.json"

# Last successful tool call this session (for "remember that as …").
_LAST = {"phrase": "", "action": "", "args": {}, "say": "", "t": 0.0}

# Built-in seeds — always available even before any teaching.
_SEEDS: list[dict] = [
    {
        "say": "open friends chat",
        "action": "discord_friends",
        "args": {},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open friend chat",
        "action": "discord_friends",
        "args": {},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open discord friends",
        "action": "discord_friends",
        "args": {},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open discord chat",
        "action": "discord_friends",
        "args": {},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open dms",
        "action": "discord_friends",
        "args": {},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open discord",
        "action": "open_app",
        "args": {"name": "discord"},
        "app": "discord",
        "builtin": True,
    },
    {
        "say": "open steam friends",
        "action": "steam_goto",
        "args": {"section": "friends"},
        "app": "steam",
        "builtin": True,
    },
    {
        "say": "open friends in steam",
        "action": "steam_goto",
        "args": {"section": "friends"},
        "app": "steam",
        "builtin": True,
    },
    {
        "say": "steam friends chat",
        "action": "steam_goto",
        "args": {"section": "friends"},
        "app": "steam",
        "builtin": True,
    },
    {
        "say": "open youtube homepage",
        "action": "youtube_home",
        "args": {},
        "app": "youtube",
        "builtin": True,
    },
    {
        "say": "open youtube home",
        "action": "youtube_home",
        "args": {},
        "app": "youtube",
        "builtin": True,
    },
    {
        "say": "open youtube",
        "action": "open_website",
        "args": {"site": "youtube"},
        "app": "youtube",
        "builtin": True,
    },
    {
        "say": "open google",
        "action": "open_website",
        "args": {"site": "google"},
        "app": "google",
        "builtin": True,
    },
    {
        "say": "open opera",
        "action": "open_app",
        "args": {"name": "opera"},
        "app": "opera",
        "builtin": True,
    },
    {
        "say": "open blender",
        "action": "open_app",
        "args": {"name": "blender"},
        "app": "blender",
        "builtin": True,
    },
    {
        "say": "open notepad",
        "action": "open_app",
        "args": {"name": "notepad"},
        "app": "notepad",
        "builtin": True,
    },
    {
        "say": "open whatsapp",
        "action": "open_app",
        "args": {"name": "whatsapp"},
        "app": "whatsapp",
        "builtin": True,
    },
    {
        "say": "open windows settings",
        "action": "open_settings",
        "args": {"page": "home"},
        "app": "windows-settings",
        "builtin": True,
    },
    {
        "say": "open bluetooth settings",
        "action": "open_settings",
        "args": {"page": "bluetooth"},
        "app": "windows-settings",
        "builtin": True,
    },
    {
        "say": "open wifi settings",
        "action": "open_settings",
        "args": {"page": "wifi"},
        "app": "windows-settings",
        "builtin": True,
    },
]


def _norm(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"recipes": [], "updated": ""}


def _save(data: dict) -> None:
    data = dict(data)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def all_recipes() -> list[dict]:
    learned = _load().get("recipes") or []
    # Seeds win over learned when the say-text collides (protect builtins).
    by_say = {_norm(r.get("say", "")): r for r in _SEEDS if r.get("say")}
    for r in learned:
        key = _norm(r.get("say", ""))
        if not key:
            continue
        if key in by_say and by_say[key].get("builtin"):
            continue
        by_say[key] = r
    return list(by_say.values())


def match(text: str) -> dict | None:
    """Return best recipe for this utterance, or None."""
    q = _norm(text)
    if not q or len(q) < 3:
        return None
    recipes = all_recipes()
    # Exact
    for r in recipes:
        if _norm(r.get("say", "")) == q:
            return r
    # Recipe phrase fully contained in the utterance (prefer longer say).
    # Leftover words must be empty/filler — otherwise "open youtube" would
    # steal "open youtube homepage".
    _filler = {"please", "now", "for", "me", "the", "a", "an", "my", "just"}
    ranked = []
    for r in recipes:
        say = _norm(r.get("say", ""))
        if not say or len(say) < 4:
            continue
        if say in q:
            rest = q.replace(say, " ", 1)
            rest = re.sub(r"\s+", " ", rest).strip()
            rest_toks = [t for t in rest.split() if t not in _filler]
            if not rest_toks:
                ranked.append((len(say), r))
    if ranked:
        ranked.sort(key=lambda x: -x[0])
        return ranked[0][1]
    # All recipe tokens must appear — only for richer phrases (3+ tokens),
    # so "open steam" cannot steal "open first account in steam".
    q_toks = set(q.split())
    best = None
    best_len = 0
    for r in recipes:
        say = _norm(r.get("say", ""))
        s_toks = set(say.split())
        if len(s_toks) < 3:
            continue
        if s_toks <= q_toks and len(s_toks) > best_len:
            best_len = len(s_toks)
            best = r
    return best


def remember(say: str, action: str, args: dict | None = None, app: str = "") -> str:
    """Save / update a voice recipe."""
    say_n = _norm(say)
    if len(say_n) < 3 or not action:
        return "I need a short phrase and an action to remember."
    data = _load()
    recipes = data.setdefault("recipes", [])
    entry = {
        "say": say_n,
        "action": action,
        "args": args or {},
        "app": (app or "").strip().lower(),
        "builtin": False,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    replaced = False
    for i, r in enumerate(recipes):
        if _norm(r.get("say", "")) == say_n:
            recipes[i] = entry
            replaced = True
            break
    if not replaced:
        recipes.append(entry)
    # Cap growth
    data["recipes"] = recipes[-200:]
    _save(data)
    return f"Got it. When you say '{say_n}', I'll do {action}."


def note_success(phrase: str, action: str, args: dict | None = None, say: str = "") -> None:
    """Remember last successful action for later teaching / auto-save."""
    _LAST["phrase"] = _norm(phrase)
    _LAST["action"] = action
    _LAST["args"] = args or {}
    _LAST["say"] = say or ""
    _LAST["t"] = time.time()


def last_success() -> dict:
    return dict(_LAST)


def remember_last_as(phrase: str) -> str:
    if not _LAST.get("action") or time.time() - float(_LAST.get("t") or 0) > 600:
        return (
            "I don't have a recent successful action to remember. "
            "Do the thing once, then say 'remember that as …'."
        )
    return remember(
        phrase,
        _LAST["action"],
        _LAST.get("args") or {},
        app="",
    )


def auto_save_if_useful(phrase: str, action: str, args: dict | None = None) -> None:
    """Quietly save successful non-trivial phrases so they work next time."""
    q = _norm(phrase)
    if not q or not action:
        return
    # Skip tiny / already-covered
    if len(q.split()) < 2:
        return
    if action in ("volume", "media", "wait", "system_report"):
        return
    hit = match(q)
    if hit and hit.get("builtin"):
        return
    # Don't spam-save open chrome etc.
    if re.fullmatch(r"open [a-z0-9 .]{2,30}", q) and action == "open_app":
        return
    # Don't overwrite dedicated YouTube home / play routing with bare open_website
    if re.search(r"\b(home(?:page)?|feed)\b", q) and action in ("open_website", "open_site"):
        return
    if re.search(r"\b(account|login|log in|sign in)\b", q) and action == "open_app":
        return
    try:
        remember(q, action, args or {})
    except Exception:
        pass


def for_prompt(limit: int = 24) -> str:
    """Compact recipe list for the LLM planner."""
    rows = []
    for r in all_recipes()[:limit]:
        say = r.get("say") or ""
        act = r.get("action") or ""
        if not say or not act:
            continue
        args = r.get("args") or {}
        arg_bit = (" " + json.dumps(args, separators=(",", ":"))) if args else ""
        rows.append(f'- "{say}" → {act}{arg_bit}')
    if not rows:
        return ""
    return "VOICE RECIPES (prefer these over guessing):\n" + "\n".join(rows)
