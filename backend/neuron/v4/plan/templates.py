"""Deterministic goal → TaskPlan templates (no LLM)."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.plan.types import Goal, StepStatus, Subgoal, TaskPlan

_APP_ALIASES = {
    "chrome": "Chrome",
    "google chrome": "Chrome",
    "edge": "Edge",
    "firefox": "Firefox",
    "blender": "Blender",
    "notepad": "Notepad",
    "spotify": "Spotify",
    "discord": "Discord",
    "code": "Code",
    "vscode": "Code",
    "cursor": "Cursor",
}


def _canon_app(raw: str) -> str:
    key = re.sub(r"\s+", " ", (raw or "").strip().lower())
    key = re.split(r"\s+(?:on|to|onto|and|then|,)\b", key)[0].strip()
    return _APP_ALIASES.get(key) or key.title()


def _norm_mon(token: str) -> str | int:
    tok = (token or "").strip().lower()
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "first": 1, "second": 2, "third": 3,
    }
    if tok in words:
        return words[tok]
    if re.fullmatch(r"\d{1,2}", tok):
        return int(tok)
    return tok


def _sg(
    description: str,
    intent: str,
    *,
    tools: list[str] | None = None,
    hints: dict | None = None,
    pre: list[str] | None = None,
    done: list[str] | None = None,
    depends: list[str] | None = None,
    sid: str = "",
) -> Subgoal:
    sg = Subgoal(
        description=description,
        intent=intent,
        preferred_tools=list(tools or []),
        target_hints=dict(hints or {}),
        preconditions=list(pre or []),
        completion_criteria=list(done or []),
        depends_on=list(depends or []),
        status=StepStatus.PENDING,
    )
    if sid:
        sg.subgoal_id = sid
    return sg


def try_simple_template(text: str, goal: Goal) -> TaskPlan | None:
    t = (text or "").strip().lower()
    if not t:
        return None

    # mute / volume
    if re.fullmatch(r"(?:mute|unmute)(?:\s+(?:audio|sound|volume))?", t):
        mute = t.startswith("mute") and not t.startswith("unmute")
        return TaskPlan(
            goal=goal,
            source="template",
            subgoals=[
                _sg(
                    "Mute system audio" if mute else "Unmute system audio",
                    "mute",
                    tools=["volume"],
                    hints={"action": "mute" if mute else "unmute"},
                    done=["volume mute state applied"],
                    sid="sg_mute",
                )
            ],
        )
    m = re.fullmatch(r"volume\s+(up|down|raise|lower)(?:\s+(\d+))?", t)
    if m:
        direction = "up" if m.group(1) in ("up", "raise") else "down"
        return TaskPlan(
            goal=goal,
            source="template",
            subgoals=[
                _sg(
                    f"Volume {direction}",
                    "volume",
                    tools=["volume"],
                    hints={"action": direction},
                    done=["volume changed"],
                    sid="sg_vol",
                )
            ],
        )

    # open <app> [on monitor N]
    m = re.match(
        r"^(?:please\s+)?(?:open|launch|start)\s+([a-z0-9 .+-]{2,40}?)"
        r"(?:\s+(?:on|to|onto)\s+(?:the\s+|my\s+)?(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}|left|right|main|other))?"
        r"\s*$",
        t,
    )
    if m:
        app_raw = m.group(1).strip()
        if re.search(r"\b(and|,|;|then)\b", app_raw):
            return None  # multi-app — handled elsewhere
        app = _canon_app(app_raw)
        mon = _norm_mon(m.group(2)) if m.group(2) else None
        goal.target_applications = [app]
        if mon is not None:
            goal.target_monitor = mon
        sgs = [
            _sg(
                f"Ensure {app} is available",
                "open_app",
                tools=["windows.open_app", "open_app"],
                hints={"name": app},
                done=[f"{app} window exists"],
                sid="sg_open",
            )
        ]
        if mon is not None:
            sgs.append(
                _sg(
                    f"Place {app} on monitor {mon}",
                    "move_monitor",
                    tools=["windows.move_to_monitor", "move_window_to_monitor"],
                    hints={"name": app, "monitor": mon},
                    done=[f"{app} window center on monitor {mon}"],
                    depends=["sg_open"],
                    sid="sg_place",
                )
            )
        return TaskPlan(goal=goal, source="template", subgoals=sgs)

    # focus <app>
    m = re.match(r"^(?:please\s+)?(?:focus|switch to)\s+([a-z0-9 .+-]{2,40})\s*$", t)
    if m:
        app = _canon_app(m.group(1))
        return TaskPlan(
            goal=goal,
            source="template",
            subgoals=[
                _sg(
                    f"Focus {app}",
                    "focus_app",
                    tools=["windows.focus_app", "focus_app"],
                    hints={"name": app},
                    done=[f"{app} is focused"],
                    sid="sg_focus",
                )
            ],
        )

    # move <app> to monitor N
    m = re.match(
        r"^(?:please\s+)?move\s+([a-z0-9 .+-]{2,40}?)\s+(?:to|onto)\s+"
        r"(?:the\s+|my\s+)?(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}|left|right|main|other)\s*$",
        t,
    )
    if m:
        app = _canon_app(m.group(1))
        mon = _norm_mon(m.group(2))
        return TaskPlan(
            goal=goal,
            source="template",
            subgoals=[
                _sg(
                    f"Move {app} to monitor {mon}",
                    "move_monitor",
                    tools=["windows.move_to_monitor", "move_window_to_monitor"],
                    hints={"name": app, "monitor": mon},
                    done=[f"{app} window center on monitor {mon}"],
                    sid="sg_move",
                )
            ],
        )

    return None


def try_youtube_workflow(text: str, goal: Goal) -> TaskPlan | None:
    """YouTube search / play / fullscreen style goals (single or multi-clause)."""
    t = (text or "").strip().lower()
    if "youtube" not in t and "yt" not in t and "blender beginner" not in t:
        # still allow "search … play first" if youtube context later — require youtube mention
        if not re.search(r"\b(youtube|yt)\b", t):
            return None

    mon = None
    m = re.search(
        r"(?:on|to|onto)\s+(?:the\s+|my\s+)?(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}|left|right|main|other)",
        t,
    )
    if m:
        mon = _norm_mon(m.group(1))
        goal.target_monitor = mon

    query = ""
    mq = re.search(
        r"\bsearch\s+(?:on\s+)?(?:youtube|yt)\s+(?:for\s+)?(.+?)(?=\s*(?:,|and|;|\bplay\b|\bfullscreen\b|$))",
        t,
    )
    if not mq:
        mq = re.search(
            r"\bsearch\s+(?:for\s+)?(.+?)(?=\s*(?:,|and|;|\bplay\b|\bfullscreen\b|$))",
            t,
        )
    if not mq:
        # "youtube for <query>" only when not "youtube on monitor"
        mq = re.search(
            r"\b(?:youtube|yt)\s+for\s+(.+?)(?=\s*(?:,|and|;|\bplay\b|\bfullscreen\b|$))",
            t,
        )
    if mq:
        query = mq.group(1).strip(" .,!?")
        query = re.sub(r"\s+play\b.*$", "", query).strip(" .,")
        query = re.sub(
            r"\s+on\s+(?:the\s+|my\s+)?(?:monitor|screen|display)\s*\S*",
            "",
            query,
        ).strip(" .,")
        if query.lower().startswith("on monitor") or query.lower().startswith("on screen"):
            query = ""

    play_idx = None
    mp = re.search(r"\bplay\s+(?:the\s+)?(first|1st|second|2nd|third|3rd|\d+)(?:\s+result|\s+video)?\b", t)
    if mp:
        word = mp.group(1)
        idx_map = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}
        play_idx = idx_map.get(word)
        if play_idx is None:
            try:
                play_idx = max(0, int(word) - 1)
            except ValueError:
                play_idx = 0
    want_fs = bool(re.search(r"\bfullscreen\b|\bfull screen\b", t))
    want_open = bool(re.search(r"\bopen\b|\blaunch\b|\bgo to\b|\bwatch\b", t)) or bool(query)

    if not (want_open or query or play_idx is not None or want_fs):
        return None

    browser = "Chrome"
    goal.target_applications = list(dict.fromkeys((goal.target_applications or []) + [browser, "YouTube"]))

    sgs: list[Subgoal] = []
    sgs.append(
        _sg(
            "Ensure browser/YouTube available",
            "ensure_youtube",
            tools=["youtube.home", "open_website", "open_app"],
            hints={"name": browser, "site": "youtube", "url": "https://www.youtube.com"},
            done=["YouTube loaded or Chrome with YouTube"],
            sid="sg_yt_avail",
        )
    )
    prev = "sg_yt_avail"
    if mon is not None:
        sgs.append(
            _sg(
                f"Ensure browser window on monitor {mon}",
                "move_monitor",
                tools=["windows.move_to_monitor", "move_window_to_monitor"],
                hints={"name": browser, "monitor": mon},
                done=[f"{browser} on monitor {mon}"],
                depends=[prev],
                sid="sg_yt_mon",
            )
        )
        prev = "sg_yt_mon"
    if query:
        sgs.append(
            _sg(
                f"Search YouTube for '{query}'",
                "youtube_search",
                tools=["youtube.search", "browser_search"],
                hints={"query": query, "site": "youtube"},
                done=[f"search results for '{query}' visible"],
                depends=[prev],
                sid="sg_yt_search",
            )
        )
        prev = "sg_yt_search"
    if play_idx is not None:
        sgs.append(
            _sg(
                f"Play result index {play_idx}",
                "youtube_play",
                tools=["youtube.play_result", "play_result"],
                hints={"index": play_idx},
                done=["video playing or result opened"],
                depends=[prev],
                sid="sg_yt_play",
            )
        )
        prev = "sg_yt_play"
        # Optional semantic identify step before play when no domain skill preferred path
        # kept as play skill-first
    if want_fs:
        sgs.append(
            _sg(
                "Enter fullscreen",
                "youtube_fullscreen",
                tools=["youtube.fullscreen"],
                hints={"exit": False},
                done=["player fullscreen where detectable"],
                depends=[prev],
                sid="sg_yt_fs",
            )
        )
        prev = "sg_yt_fs"
    sgs.append(
        _sg(
            "Confirm final desired state",
            "observe",
            tools=["observe"],
            hints={},
            done=["final state observed"],
            depends=[prev],
            sid="sg_yt_confirm",
        )
    )
    goal.completion_criteria = ["YouTube workflow complete"]
    return TaskPlan(goal=goal, source="template", subgoals=sgs)


def try_multi_app_as_plan(text: str, goal: Goal) -> TaskPlan | None:
    """Wrap v3 multi_app composer into typed Subgoals (compatibility)."""
    try:
        from neuron.v3.multi_app import compose_multi_app_plan, looks_multi_app
    except Exception:
        return None
    if not looks_multi_app(text):
        return None
    legacy = compose_multi_app_plan(text)
    if not legacy or not legacy.get("steps"):
        return None
    return legacy_steps_to_plan(legacy["steps"], goal, source="multi_app")


def legacy_steps_to_plan(
    steps: list[dict[str, Any]],
    goal: Goal,
    *,
    source: str = "legacy",
) -> TaskPlan:
    sgs: list[Subgoal] = []
    prev_id = ""
    for i, step in enumerate(steps):
        action = str(step.get("action") or "").strip()
        args = dict(step.get("args") or {})
        sid = f"sg_legacy_{i}"
        intent = _action_to_intent(action, args)
        tools = [action] if action else []
        # Prefer skill aliases when mapping known legacy tools
        if action == "browser_search" and str(args.get("site") or "").lower() == "youtube":
            tools = ["youtube.search", "browser_search"]
            intent = "youtube_search"
        elif action == "play_result":
            tools = ["youtube.play_result", "play_result"]
            intent = "youtube_play"
        elif action == "open_app":
            tools = ["windows.open_app", "open_app"]
            intent = "open_app"
        elif action == "move_window_to_monitor":
            tools = ["windows.move_to_monitor", "move_window_to_monitor"]
            intent = "move_monitor"
        sg = _sg(
            str(step.get("target") or step.get("expected_result") or action or f"step {i}"),
            intent,
            tools=tools,
            hints=args,
            done=[str(step.get("expected_result") or "")],
            depends=[prev_id] if prev_id else None,
            sid=sid,
        )
        sgs.append(sg)
        prev_id = sid
    return TaskPlan(goal=goal, source=source, subgoals=sgs, meta={"from_legacy": True})


def _action_to_intent(action: str, args: dict) -> str:
    a = (action or "").lower()
    if a in ("open_app", "windows.open_app"):
        return "open_app"
    if a in ("focus_app", "windows.focus_app"):
        return "focus_app"
    if "move" in a and "monitor" in a:
        return "move_monitor"
    if "youtube.search" in a or a == "browser_search":
        return "youtube_search" if str(args.get("site") or "").lower() == "youtube" else "browser_search"
    if "play_result" in a:
        return "youtube_play"
    if "fullscreen" in a:
        return "youtube_fullscreen"
    if a == "volume":
        return "mute" if "mute" in args else "volume"
    return a or "unknown"


def try_click_resolve_template(text: str, goal: Goal) -> TaskPlan | None:
    t = (text or "").strip().lower()
    m = re.match(r"^(?:please\s+)?(?:click|press|tap)\s+(?:on\s+)?(.+)$", t)
    if not m:
        return None
    ref = m.group(1).strip(" .,")
    if not ref or len(ref) > 80:
        return None
    return TaskPlan(
        goal=goal,
        source="template",
        subgoals=[
            _sg(
                f"Resolve and click '{ref}'",
                "click",
                tools=["resolve", "uia_click", "browser_click", "click"],
                hints={"reference": ref},
                done=[f"clicked {ref}"],
                sid="sg_click",
            )
        ],
    )


def try_multi_open(text: str, goal: Goal) -> TaskPlan | None:
    """Open Spotify and Chrome / dual-monitor variants without full multi_app regex."""
    t = (text or "").strip().lower()
    apps = []
    for alias, canon in _APP_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            if canon not in apps:
                apps.append(canon)
    if "youtube" in t and "Chrome" not in apps:
        apps.append("Chrome")
    if len(apps) < 2:
        return None
    if not re.search(r"\b(open|launch|start)\b", t):
        return None
    # Monitor assignments
    placements: dict[str, Any] = {}
    for m in re.finditer(
        r"\b(youtube|chrome|spotify|discord|blender|edge)\b.{0,40}?"
        r"(?:on|to)\s+(?:the\s+)?(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}|left|right)",
        t,
    ):
        app = _canon_app(m.group(1) if m.group(1) != "youtube" else "chrome")
        placements[app] = _norm_mon(m.group(2))

    sgs: list[Subgoal] = []
    prev = ""
    for i, app in enumerate(apps):
        sid = f"sg_open_{i}"
        sgs.append(
            _sg(
                f"Ensure {app} available",
                "open_app",
                tools=["windows.open_app", "open_app"],
                hints={"name": app},
                done=[f"{app} window exists"],
                depends=[prev] if prev else None,
                sid=sid,
            )
        )
        prev = sid
        if app in placements:
            sid2 = f"sg_place_{i}"
            sgs.append(
                _sg(
                    f"Place {app} on monitor {placements[app]}",
                    "move_monitor",
                    tools=["windows.move_to_monitor", "move_window_to_monitor"],
                    hints={"name": app, "monitor": placements[app]},
                    done=[f"{app} on monitor {placements[app]}"],
                    depends=[sid],
                    sid=sid2,
                )
            )
            prev = sid2
    goal.target_applications = apps
    return TaskPlan(goal=goal, source="template", subgoals=sgs)


__all__ = [
    "try_simple_template",
    "try_youtube_workflow",
    "try_multi_app_as_plan",
    "try_click_resolve_template",
    "try_multi_open",
    "legacy_steps_to_plan",
]
