"""Task decomposition — templates + generic clause planner + multi_app bridge."""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.taskplan.extract import extract_goal
from neuron.taskplan.types import GoalSpec, Subtask, TaskGraph


def _st(
    description: str,
    action: str,
    args: dict[str, Any] | None = None,
    *,
    depends: list[str] | None = None,
    expected: str = "",
    target: str = "",
    sid: str = "",
    confirm: bool = False,
    use_screen: bool = False,
    use_fast: bool = False,
) -> Subtask:
    s = Subtask(
        description=description,
        action=action,
        args=dict(args or {}),
        depends_on=list(depends or []),
        expected_result=expected or description,
        target=target,
        requires_confirm=confirm,
        use_screen=use_screen,
        use_fast=use_fast,
    )
    if sid:
        s.subtask_id = sid
    return s


def _chain(steps: list[Subtask]) -> list[Subtask]:
    """Wire sequential depends_on by subtask_id order."""
    for i, s in enumerate(steps):
        if i == 0:
            continue
        if not s.depends_on:
            s.depends_on = [steps[i - 1].subtask_id]
    return steps


# ---------------------------------------------------------------------------
# Templates for documented example workflows
# ---------------------------------------------------------------------------


def _tpl_youtube_unreal(text: str, goal: GoalSpec) -> TaskGraph | None:
    low = text.lower()
    if not (
        re.search(r"\b(?:chrome|browser)\b", low)
        and re.search(r"\byoutube\b", low)
        and re.search(r"\b(?:search|play)\b", low)
    ):
        return None
    m = re.search(
        r"\b(?:search\s+(?:on\s+)?(?:youtube|yt)\s+(?:for\s+)?|youtube\s+for\s+)"
        r"(.+?)(?=\s*(?:,|and|;|\bplay\b|$))",
        low,
    )
    query = (m.group(1).strip(" .,!") if m else "") or "Unreal Engine tutorials"
    query = re.sub(r"\s+play\b.*$", "", query).strip(" .,")
    steps = _chain([
        _st("Open Chrome", "open_app", {"name": "Chrome", "wait_seconds": 3},
            sid="st_chrome", use_fast=True, expected="Chrome is running"),
        _st(
            f"Search YouTube for {query}",
            "browser_search",
            {"site": "youtube", "query": query},
            sid="st_search",
            expected=f"search results for '{query}' visible",
            target="youtube",
        ),
        _st(
            "Play the first result",
            "play_result",
            {"index": 0},
            sid="st_play",
            expected="video playing or result opened",
        ),
    ])
    return TaskGraph(goal=goal, subtasks=steps, source="template:youtube")


def _tpl_vscode_hello(text: str, goal: GoalSpec) -> TaskGraph | None:
    low = text.lower()
    if not (
        re.search(r"\b(?:visual studio code|vs\s*code|vscode|\bcode\b)\b", low)
        and re.search(r"\b(?:python|hello\s*world)\b", low)
    ):
        return None
    content = "print('Hello World')\n"
    steps = _chain([
        _st("Open Visual Studio Code", "open_app", {"name": "Code", "wait_seconds": 4},
            sid="st_code", use_fast=True, expected="VS Code is running"),
        _st(
            "Create hello_world.py",
            "create_file",
            {"name": "hello_world.py", "content": content, "location": "desktop"},
            sid="st_file",
            confirm=True,
            expected="hello_world.py exists on Desktop",
        ),
        _st(
            "Open the Python file",
            "open_file",
            {"path": "hello_world.py"},
            sid="st_open",
            expected="file opened",
        ),
        _st(
            "Run Hello World (terminal)",
            "press_keys",
            {"keys": "ctrl+`"},
            sid="st_term",
            expected="terminal toggled",
        ),
        _st(
            "Execute python hello_world.py",
            "type_text",
            {"text": "python hello_world.py\n"},
            sid="st_run",
            confirm=True,
            expected="python command sent",
        ),
    ])
    return TaskGraph(goal=goal, subtasks=steps, source="template:vscode_hello")


def _tpl_blender_download(text: str, goal: GoalSpec) -> TaskGraph | None:
    low = text.lower()
    if not (re.search(r"\bblender\b", low) and re.search(r"\b(?:download|install)\b", low)):
        return None
    steps = _chain([
        _st("Open Chrome", "open_app", {"name": "Chrome", "wait_seconds": 3},
            sid="st_chrome", use_fast=True),
        _st(
            "Open Blender download page",
            "open_website",
            {"url": "https://www.blender.org/download/"},
            sid="st_page",
            expected="blender.org download page open",
        ),
        _st(
            "Find and click Download",
            "screen_understand",
            {"request": "Find the download button", "force": True},
            sid="st_dl",
            use_screen=True,
            expected="download started or download button clicked",
        ),
        _st(
            "Confirm installer / install Blender",
            "screen_understand",
            {"request": "Click Install or Run if an installer dialog is open", "force": True},
            sid="st_install",
            use_screen=True,
            confirm=True,
            expected="installer acknowledged",
        ),
    ])
    return TaskGraph(goal=goal, subtasks=steps, source="template:blender_download")


def _tpl_whatsapp(text: str, goal: GoalSpec) -> TaskGraph | None:
    low = text.lower()
    if not (re.search(r"\bwhatsapp\b", low) and re.search(r"\b(?:reply|archive)\b", low)):
        return None
    steps = _chain([
        _st(
            "Open WhatsApp Web",
            "open_website",
            {"url": "https://web.whatsapp.com/"},
            sid="st_wa",
            expected="WhatsApp Web open",
        ),
        _st(
            "Reply to the latest message",
            "screen_understand",
            {"request": "Reply to this message", "force": True},
            sid="st_reply",
            use_screen=True,
            confirm=True,
            expected="reply sent or compose focused",
        ),
        _st(
            "Archive the chat",
            "screen_understand",
            {"request": "Archive this chat", "force": True},
            sid="st_archive",
            use_screen=True,
            confirm=True,
            expected="chat archived",
        ),
    ])
    return TaskGraph(goal=goal, subtasks=steps, source="template:whatsapp")


def _tpl_desktop_projects(text: str, goal: GoalSpec) -> TaskGraph | None:
    low = text.lower()
    if not (
        re.search(r"\b(?:folder|projects)\b", low)
        and re.search(r"\b(?:pdf|zip|move)\b", low)
    ):
        return None
    folder = "Projects"
    m = re.search(r"\bfolder\s+(?:on\s+the\s+desktop\s+)?(?:called|named)\s+([A-Za-z0-9_-]+)", text, re.I)
    if m:
        folder = m.group(1)
    steps = _chain([
        _st(
            f"Create Desktop folder {folder}",
            "create_folder",
            {"name": folder, "location": "desktop"},
            sid="st_folder",
            confirm=True,
            expected=f"folder {folder} exists on Desktop",
        ),
        _st(
            f"Move Desktop PDF files into {folder}",
            "task_move_files",
            {"pattern": "*.pdf", "dest": folder, "location": "desktop"},
            sid="st_move",
            confirm=True,
            expected="PDFs moved into folder",
        ),
        _st(
            f"Zip the {folder} folder",
            "task_zip_folder",
            {"name": folder, "location": "desktop"},
            sid="st_zip",
            confirm=True,
            expected=f"{folder}.zip created",
        ),
    ])
    return TaskGraph(goal=goal, subtasks=steps, source="template:desktop_projects")


def try_templates(text: str, goal: GoalSpec) -> TaskGraph | None:
    for fn in (
        _tpl_youtube_unreal,
        _tpl_vscode_hello,
        _tpl_blender_download,
        _tpl_whatsapp,
        _tpl_desktop_projects,
    ):
        g = fn(text, goal)
        if g and g.subtasks:
            return g
    return None


def from_multi_app(text: str, goal: GoalSpec) -> TaskGraph | None:
    try:
        from neuron.v3.multi_app import compose_multi_app_plan
        plan = compose_multi_app_plan(text)
    except Exception:
        return None
    if not plan or not (plan.get("steps") or []):
        return None
    steps: list[Subtask] = []
    prev: str | None = None
    for i, raw in enumerate(plan.get("steps") or []):
        action = (raw.get("action") or raw.get("tool") or "").strip()
        if not action:
            continue
        sid = f"st_ma_{i}"
        st = _st(
            raw.get("expected_result") or action,
            action,
            dict(raw.get("args") or raw.get("arguments") or {}),
            depends=[prev] if prev else None,
            expected=str(raw.get("expected_result") or ""),
            target=str(raw.get("target") or ""),
            sid=sid,
            use_fast=action in ("open_app", "focus_app", "volume"),
        )
        steps.append(st)
        prev = sid
    if not steps:
        return None
    return TaskGraph(goal=goal, subtasks=steps, source="multi_app")


def generic_decompose(text: str, goal: GoalSpec) -> TaskGraph | None:
    """Split on and/then and map simple clauses to tools."""
    clauses = re.split(r"\b(?:and|,|;|\bthen\b)\b", text, flags=re.I)
    clauses = [c.strip(" .") for c in clauses if c.strip(" .")]
    if len(clauses) < 2:
        return None
    steps: list[Subtask] = []
    prev: str | None = None
    for i, clause in enumerate(clauses):
        low = clause.lower()
        sid = f"st_g_{i}"
        st: Subtask | None = None
        m = re.search(r"\b(?:open|launch|start)\s+([a-z0-9 .+-]{2,40})", low)
        if m and not re.search(r"\b(website|youtube|whatsapp\s+web)\b", low):
            app = m.group(1).strip()
            if app in ("youtube", "google"):
                pass
            else:
                name = {"vscode": "Code", "visual studio code": "Code", "code": "Code"}.get(
                    app, app.title()
                )
                st = _st(f"Open {name}", "open_app", {"name": name}, sid=sid, use_fast=True)
        if st is None:
            m = re.search(r"\bsearch\s+(?:on\s+)?(?:youtube|yt)\s+(?:for\s+)?(.+)$", low)
            if m:
                st = _st(
                    f"YouTube search {m.group(1)}",
                    "browser_search",
                    {"site": "youtube", "query": m.group(1).strip()},
                    sid=sid,
                )
        if st is None and re.search(r"\bplay\s+(?:the\s+)?first\b", low):
            st = _st("Play first result", "play_result", {"index": 0}, sid=sid)
        if st is None and re.search(r"\bcreate\s+(?:a\s+)?(?:new\s+)?folder\b", low):
            name_m = re.search(r"called\s+([A-Za-z0-9_-]+)", clause, re.I)
            st = _st(
                "Create folder",
                "create_folder",
                {"name": (name_m.group(1) if name_m else "Projects"), "location": "desktop"},
                sid=sid,
                confirm=True,
            )
        if st is None:
            # Fall back: let AgentLoop/LLM handle via computer_use-ish wait marker
            # Use screen_understand for visual phrasing; else type as open_website search
            if re.search(r"\b(click|button|popup|tab|reply)\b", low):
                st = _st(clause, "screen_understand", {"request": clause, "force": True},
                         sid=sid, use_screen=True)
            else:
                continue
        if prev:
            st.depends_on = [prev]
        steps.append(st)
        prev = sid
    if len(steps) < 2:
        return None
    return TaskGraph(goal=goal, subtasks=steps, source="generic")


def build_graph(text: str, *, goal: GoalSpec | None = None) -> TaskGraph | None:
    """Full pipeline: extract goal → template → multi_app → generic."""
    t0 = time.perf_counter()
    goal = goal or extract_goal(text)
    graph = try_templates(text, goal)
    if graph is None:
        graph = from_multi_app(text, goal)
    if graph is None:
        graph = generic_decompose(text, goal)
    if graph is None:
        return None
    graph.planner_ms = round((time.perf_counter() - t0) * 1000, 2)
    graph.goal = goal
    return graph
