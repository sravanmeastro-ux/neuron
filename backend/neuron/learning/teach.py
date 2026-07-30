"""Teach session — 'learn how I …' → demonstrate → save procedure.

Wraps click_recorder for demonstration capture. Does not edit source files.
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.learning import procedures

_session: dict[str, Any] = {
    "active": False,
    "goal": "",
    "skill_id": "",
    "say": [],
    "app": "",
    "started": 0.0,
}


def is_teaching() -> bool:
    return bool(_session.get("active"))


def status() -> str:
    if not _session.get("active"):
        n = len(procedures.list_procedures(include_builtin=False))
        return (
            f"Not teaching. {n} learned procedure(s). "
            "Say 'learn how I …' then demonstrate, then 'done' or 'stop learning'."
        )
    try:
        import click_recorder
        extra = click_recorder.status()
    except Exception:
        extra = ""
    return (
        f"Learning '{_session.get('skill_id')}' — demonstrate the workflow now. "
        f"When finished say 'done' or 'stop learning'. {extra}"
    ).strip()


def start(goal: str, *, app: str = "") -> str:
    """Begin a controlled teaching session for a spoken goal."""
    g = (goal or "").strip()
    if not g:
        return "Tell me what to learn, e.g. 'learn how I create a new Blender project'."

    # Refuse source-code teaching goals
    if procedures.rejects_source_write(g):
        return (
            "I won't learn procedures that rewrite my own source code. "
            "I can learn app workflows — like creating a Blender project."
        )

    skill_id = procedures.skill_id_from_goal(g, app_hint=app)
    phrases = procedures.phrases_from_goal(g)
    domain = skill_id.split(".", 1)[0]

    _session.update({
        "active": True,
        "goal": g,
        "skill_id": skill_id,
        "say": phrases,
        "app": domain,
        "started": time.time(),
    })

    # Start click demonstration capture when available
    clicked = ""
    try:
        import click_recorder
        if click_recorder.is_feature_enabled():
            if click_recorder.is_recording():
                click_recorder.cancel()
            clicked = click_recorder.start(label=skill_id.replace(".", " "))
    except Exception as exc:
        clicked = f"(click capture unavailable: {exc})"

    return (
        f"OK — teach me '{skill_id}'. Do the steps yourself now "
        f"(I'll record clicks). When finished say 'done', 'stop learning', "
        f"or 'save the procedure'. {clicked}"
    ).strip()


def cancel() -> str:
    _session["active"] = False
    try:
        import click_recorder
        if click_recorder.is_recording():
            click_recorder.cancel()
    except Exception:
        pass
    return "Teaching cancelled. Nothing saved."


def finish(name: str = "") -> str:
    """Stop demonstration and save as a learned procedure."""
    if not _session.get("active"):
        return "I wasn't learning a procedure. Say 'learn how I …' first."

    skill_id = (name or "").strip() or _session.get("skill_id") or ""
    if name and "." not in name and " " not in name:
        domain = _session.get("app") or "desktop"
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
        skill_id = f"{domain}.{slug}" if slug else _session.get("skill_id")
    elif name and " " in name and "." not in name:
        # Treat as alternate say-phrase, keep skill id
        skill_id = _session.get("skill_id") or skill_id

    say = list(_session.get("say") or [])
    if name and " " in name and name.lower() not in [s.lower() for s in say]:
        say.insert(0, name.lower().strip())

    steps: list[dict] = []
    click_id = ""
    try:
        import click_recorder
        was_recording = click_recorder.is_recording()
        if was_recording:
            msg = click_recorder.stop(
                (_session.get("skill_id") or "workflow").replace(".", " ")
            )
            recipe = click_recorder.last_saved()
            click_id = recipe.get("id") or ""
            steps = procedures.clicks_to_steps(recipe, app=_session.get("app") or "")
            if not steps:
                _session["active"] = False
                return f"Teaching stopped but no clicks captured. {msg}"
    except Exception as exc:
        _session["active"] = False
        return f"Couldn't finish teaching: {exc}"

    if not steps:
        builtin = procedures.get(skill_id)
        if builtin and builtin.get("builtin"):
            steps = list(builtin.get("steps") or [])
            source = "builtin_seed"
        else:
            _session["active"] = False
            return (
                "No demonstration steps captured. Enable click recording in config, "
                "or demonstrate with the mouse after saying 'learn how I …'."
            )
    else:
        source = "demonstration"

    ok, message, _proc = procedures.save_procedure(
        skill_id=skill_id,
        steps=steps,
        say=say,
        domain=_session.get("app") or "",
        source=source,
        meta={"click_recipe_id": click_id, "goal": _session.get("goal")},
    )
    _session["active"] = False
    return message


def parse_learn_goal(text: str) -> str | None:
    """Extract goal from 'learn how I …' / 'watch me …' utterances."""
    t = (text or "").strip()
    patterns = (
        r"^(?:neuron[,.]?\s+)?learn how i\s+(.+)$",
        r"^(?:neuron[,.]?\s+)?learn how to\s+(.+)$",
        r"^(?:neuron[,.]?\s+)?watch me\s+(.+)$",
        r"^(?:neuron[,.]?\s+)?(?:please\s+)?teach yourself how (?:to|i)\s+(.+)$",
        r"^(?:neuron[,.]?\s+)?record (?:how i|this workflow|a workflow)(?:\s+to)?\s*(.*)$",
        r"^(?:neuron[,.]?\s+)?learn (?:this|the) (?:procedure|workflow|skill)\s*(?:for|to)?\s*(.*)$",
    )
    for pat in patterns:
        m = re.match(pat, t, re.I)
        if m:
            goal = (m.group(1) or "").strip(" .")
            return goal or t
    return None
