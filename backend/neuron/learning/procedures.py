"""Phase 9 — controlled procedure learning (not source-code rewriting).

NEURON may learn *procedures* (ordered tool steps) from demonstration.
It must NEVER modify its own `.py` / project source as a form of learning.

Example:
  User: "Neuron, learn how I create a new Blender project."
  User demonstrates (clicks recorded).
  User: "Done." / "stop learning"
  → Skill blender.new_project saved under learned_procedures.json

  Later: "Create a Blender project." → run_procedure replays those steps.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

STORE = Path(__file__).resolve().parent.parent.parent / "learned_procedures.json"

# Never allow learned procedures to write project source / self-modify.
_SOURCE_WRITE_BAN = re.compile(
    r"(?i)("
    r"\.(py|pyw|ts|tsx|js|jsx|mjs|cjs|cs|cpp|cxx|h|hpp|rs|go|java)([\"'\s]|$)"
    r"|[/\\]neuron[/\\]"
    r"|\bbackend[/\\][^\"'\s]*\.py"
    r"|[/\\]\.git[/\\]"
    r"|modify (your|my|the) (source|code|repo|repository)"
    r"|edit (your|neuron).*\.py"
    r"|rewrite (yourself|your code)"
    r")"
)

# Built-in seeds — overridable by demonstration learning.
_BUILTINS: list[dict[str, Any]] = [
    {
        "id": "blender.new_project",
        "domain": "blender",
        "name": "new_project",
        "say": [
            "create a blender project",
            "new blender project",
            "create new blender project",
            "start a new blender project",
            "create a new project in blender",
        ],
        "steps": [
            {
                "action": "open_app",
                "args": {"name": "blender"},
                "target": "Blender",
                "expected_result": "Blender window is open",
            },
            {
                "action": "wait",
                "args": {"seconds": 4},
                "target": "startup",
                "expected_result": "startup splash finished",
            },
            {
                "action": "click_element",
                "args": {"name": "General"},
                "target": "General template",
                "expected_result": "General template selected / viewport visible",
            },
        ],
        "builtin": True,
        "source": "builtin",
        "semantic": True,
    },
    {
        "id": "blender.start_render",
        "domain": "blender",
        "name": "start_render",
        "say": [
            "start blender render",
            "render blender project",
            "start render in blender",
            "start a blender render",
            "render this blender project",
        ],
        "params": ["project"],
        "steps": [
            {
                "action": "blender.open_project",
                "args": {"query": "{project}"},
                "target": "{project}",
                "expected_result": "Blender project open",
            },
            {
                "action": "wait",
                "args": {"seconds": 2},
                "target": "Blender",
                "expected_result": "Blender settled",
            },
            {
                "action": "focus_app",
                "args": {"name": "Blender"},
                "target": "Blender",
                "expected_result": "Blender focused",
            },
            {
                "action": "press_keys",
                "args": {"keys": "f12"},
                "target": "Render",
                "expected_result": "render triggered (F12)",
            },
            {
                "action": "wait",
                "args": {"seconds": 1.5},
                "target": "render",
                "expected_result": "render UI visible",
            },
            {
                "action": "find_element",
                "args": {"name": "Render"},
                "target": "Render",
                "expected_result": "render UI or progress detectable",
            },
        ],
        "builtin": True,
        "source": "builtin",
        "semantic": True,
    },
]


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"procedures": [], "updated": ""}


def _save(data: dict) -> None:
    data = dict(data)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def skill_id_from_goal(goal: str, app_hint: str = "") -> str:
    """Map 'create a new Blender project' → blender.new_project."""
    g = re.sub(r"\s+", " ", (goal or "").strip().lower())
    g = re.sub(
        r"^(?:learn how i|learn how to|watch me|teach (?:yourself|me)|show me how (?:to|i)|record)\s+",
        "",
        g,
    ).strip()
    app = (app_hint or "").strip().lower()
    if not app:
        for cand in (
            "blender", "discord", "spotify", "chrome", "steam", "notepad",
            "photoshop", "word", "excel", "code", "cursor", "whatsapp",
        ):
            if cand in g:
                app = cand
                break
    if not app:
        app = "desktop"

    # Action slug from remaining words
    action = g
    for a in (app, "a", "an", "the", "new", "my", "me"):
        action = re.sub(rf"\b{re.escape(a)}\b", " ", action)
    action = re.sub(r"[^a-z0-9]+", "_", action).strip("_")
    # Prefer short meaningful names
    if "project" in g and app == "blender" and "render" not in g:
        action = "new_project"
    elif "render" in g and app == "blender":
        action = "start_render"
    elif "friends" in g and app == "discord":
        action = "open_friends"
    elif not action or action in ("how", "to", "i"):
        action = "workflow"
    action = action[:40] or "workflow"
    return f"{app}.{action}"


def phrases_from_goal(goal: str) -> list[str]:
    g = re.sub(r"\s+", " ", (goal or "").strip().lower())
    g = re.sub(
        r"^(?:learn how i|learn how to|watch me|teach (?:yourself|me)|show me how (?:to|i)|record)\s+",
        "",
        g,
    ).strip(" .")
    phrases = [g] if g else []
    # Drop leading "create a new" variants as alternate says
    alt = re.sub(r"^(?:how (?:to|i)\s+)", "", g).strip()
    if alt and alt not in phrases:
        phrases.append(alt)
    return phrases[:8]


def rejects_source_write(step: dict | str) -> bool:
    blob = step if isinstance(step, str) else json.dumps(step)
    return bool(_SOURCE_WRITE_BAN.search(blob or ""))


def list_procedures(*, include_builtin: bool = True) -> list[dict]:
    learned = list((_load().get("procedures") or []))
    if not include_builtin:
        return learned
    ids = {p.get("id") for p in learned}
    out = list(learned)
    for b in _BUILTINS:
        if b["id"] not in ids:
            out.append(dict(b))
    return out


def get(proc_id: str) -> dict | None:
    pid = (proc_id or "").strip().lower()
    if not pid:
        return None
    for p in list_procedures():
        if (p.get("id") or "").lower() == pid:
            return p
    return None


def match(text: str) -> dict | None:
    """Find a procedure whose say-phrase matches the utterance.

    Ignores teach/learn commands so 'learn how I create …' is not treated as run.
    """
    q = re.sub(r"[^\w\s]", " ", (text or "").lower())
    q = re.sub(r"\s+", " ", q).strip()
    if not q or len(q) < 4:
        return None
    if re.search(
        r"\b(learn how i|learn how to|watch me|teach yourself|stop learning|"
        r"save the procedure|list procedures|forget skill)\b",
        q,
    ):
        return None

    q_tokens = {t for t in q.split() if len(t) > 2 and t not in (
        "the", "and", "for", "with", "from", "that", "this", "please",
    )}

    best = None
    best_score = 0.0
    for p in list_procedures():
        if (p.get("id") or "").lower() == q:
            return p
        # Also match dotted id spoken as words: blender new project
        id_words = (p.get("id") or "").replace(".", " ").replace("_", " ")
        if id_words and (id_words == q or id_words in q):
            return p
        for say in list(p.get("say") or []) + [id_words]:
            s = re.sub(r"\s+", " ", str(say).lower()).strip()
            if not s:
                continue
            if s == q:
                return p
            if s in q or q in s:
                score = float(len(s))
            else:
                s_tokens = {t for t in s.split() if len(t) > 2}
                if not s_tokens or not q_tokens:
                    continue
                overlap = len(s_tokens & q_tokens) / max(len(s_tokens), 1)
                # Require strong overlap (e.g. blender+project+create)
                if overlap < 0.7:
                    continue
                score = overlap * 100 + len(s_tokens & q_tokens)
            if score > best_score:
                best = p
                best_score = score
    return best


def save_procedure(
    *,
    skill_id: str,
    steps: list[dict],
    say: list[str] | None = None,
    domain: str = "",
    source: str = "demonstration",
    meta: dict | None = None,
) -> tuple[bool, str, dict | None]:
    """Persist a learned semantic procedure. Refuses source / private / coord skills."""
    from neuron.learning.semantic import rejects_private_field, sanitize_steps

    sid = (skill_id or "").strip().lower()
    if not sid or "." not in sid:
        return False, "Skill id must look like domain.name (e.g. blender.new_project).", None
    if not steps:
        return False, "No steps to save.", None

    for s in steps:
        if rejects_source_write(s):
            return False, "Refusing to learn a procedure that modifies NEURON source code.", None
        if rejects_private_field(s):
            return False, "Refusing to learn a procedure that captures passwords or private fields.", None

    clean, warnings = sanitize_steps(steps, drop_coordinates=True)
    if not clean:
        return False, "No usable semantic steps after filtering (coordinates/private data dropped).", None

    parts = sid.split(".", 1)
    domain = (domain or parts[0]).strip().lower()
    name = parts[1] if len(parts) > 1 else "workflow"
    phrases = [p for p in (say or []) if p] or [sid.replace(".", " ").replace("_", " ")]
    # Merge builtin phrases for the same id so alternate wordings still match
    for b in _BUILTINS:
        if (b.get("id") or "").lower() == sid:
            for alt in b.get("say") or []:
                if alt and alt.lower() not in [x.lower() for x in phrases]:
                    phrases.append(alt)
            break

    proc = {
        "id": sid,
        "domain": domain,
        "name": name,
        "say": phrases,
        "steps": clean,
        "builtin": False,
        "source": source,
        "semantic": True,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": {**(meta or {}), "sanitize_warnings": warnings[:12]},
    }

    data = _load()
    procs = [p for p in (data.get("procedures") or []) if (p.get("id") or "").lower() != sid]
    procs.append(proc)
    data["procedures"] = procs[-60:]
    _save(data)

    # Voice recipe bindings for each phrase
    try:
        import voice_recipes
        for phrase in phrases[:6]:
            voice_recipes.remember(phrase, "run_procedure", {"id": sid}, app=domain)
    except Exception:
        pass

    # Register as callable skill alias
    try:
        _register_skill(proc)
    except Exception:
        pass

    warn_txt = f" ({len(warnings)} filtered)" if warnings else ""
    return True, f"Learned skill {sid} ({len(clean)} semantic steps){warn_txt}. Say: '{phrases[0]}'.", proc


def delete_procedure(skill_id: str) -> str:
    sid = (skill_id or "").strip().lower()
    data = _load()
    before = len(data.get("procedures") or [])
    data["procedures"] = [p for p in (data.get("procedures") or []) if (p.get("id") or "").lower() != sid]
    _save(data)
    if len(data["procedures"]) < before:
        return f"Forgot learned skill {sid}."
    return f"No learned skill named {sid}."


def clicks_to_steps(click_recipe: dict, *, app: str = "") -> list[dict]:
    """Convert a click_recorder recipe into adaptive semantic AgentLoop steps.

    Prefers UIA name / automationId. Drops raw x,y (not adaptive to window moves).
    Never retains screenshots or pixel crops.
    """
    from neuron.learning.semantic import sanitize_steps

    steps: list[dict] = []
    app_name = (app or click_recipe.get("app") or "").strip()
    if app_name and app_name.lower() not in ("unknown", "explorer"):
        steps.append({
            "action": "open_app",
            "args": {"name": app_name},
            "target": app_name,
            "expected_result": f"{app_name} is focused",
        })
        steps.append({
            "action": "wait",
            "args": {"seconds": 1.5},
            "target": "settle",
            "expected_result": "UI settled",
        })

    for raw in click_recipe.get("steps") or []:
        el = raw.get("element") or {}
        name = (el.get("name") or "").strip()
        auto_id = str(el.get("automationId") or el.get("automation_id") or "").strip()
        button = raw.get("button") or "left"
        if name and len(name) >= 2:
            steps.append({
                "action": "click_element",
                "args": {"name": name},
                "target": name,
                "expected_result": f"clicked {name}",
            })
        elif auto_id and len(auto_id) >= 2:
            steps.append({
                "action": "click_element",
                "args": {"name": auto_id, "automation_id": auto_id},
                "target": auto_id,
                "expected_result": f"clicked {auto_id}",
            })
        else:
            # V3.8: skip absolute coordinates — they break when windows move
            continue
        # Small wait between clicks
        steps.append({
            "action": "wait",
            "args": {"seconds": 0.4},
            "target": "between clicks",
            "expected_result": "ready for next step",
        })
        _ = button  # reserved for future button-aware semantic click

    clean, _warnings = sanitize_steps(steps, drop_coordinates=True)
    return clean


def run_procedure(
    proc_id: str = "",
    query: str = "",
    *,
    confirmed: bool = False,
    params: dict | None = None,
) -> str:
    """Execute a learned/builtin semantic procedure via AgentLoop."""
    from neuron.learning.semantic import bind_params, scrub_args

    proc = get(proc_id) if proc_id else None
    if not proc and query:
        proc = match(query)
    if not proc:
        return "I don't have a learned procedure for that yet. Say 'learn how I …' and demonstrate."

    for s in proc.get("steps") or []:
        if rejects_source_write(s):
            return "Blocked: this procedure targets source code and will not run."

    # Merge explicit params + extract simple "project=X" from query
    bound_params = dict(params or {})
    if query:
        m = re.search(r"\bproject[=:\s]+([^\s,]+)", query, re.I)
        if m and "project" not in bound_params:
            bound_params["project"] = m.group(1).strip()
        # "start blender render MyScene" → project=MyScene when param listed
        if "project" in (proc.get("params") or []) and "project" not in bound_params:
            q2 = re.sub(
                r"(?i)\b(start|render|blender|project|the|a|an|in|this)\b",
                " ",
                query,
            )
            q2 = re.sub(r"\s+", " ", q2).strip()
            if q2 and len(q2) >= 2:
                bound_params["project"] = q2.split()[0]

    raw_steps = list(proc.get("steps") or [])
    steps = bind_params(raw_steps, scrub_args(bound_params) if bound_params else bound_params)
    # If open_project has empty query and no project, fall back to focus Blender
    fixed = []
    for s in steps:
        args = dict(s.get("args") or {})
        if s.get("action") == "blender.open_project":
            q = str(args.get("query") or args.get("path") or "").strip()
            if not q or q == "{project}":
                fixed.append({
                    "action": "open_app",
                    "args": {"name": "Blender"},
                    "target": "Blender",
                    "expected_result": "Blender window is open",
                })
                continue
        fixed.append(s)
    steps = fixed

    plan = {
        "say": f"Running {proc.get('id')}.",
        "steps": steps,
    }
    try:
        from neuron.brain.agent_loop import AgentLoop
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        say, acted, meta, goal = AgentLoop(confirmed=confirmed).run(
            request=query or proc.get("id") or "",
            plan=plan,
            context=(
                f"Learned semantic procedure {proc.get('id')} "
                f"source={proc.get('source')} adaptive=true"
            ),
            normalized=(proc.get("say") or [proc.get("id")])[0],
        )
        status = getattr(goal, "status", "") or meta.get("path")
        if status == "interrupted":
            return "Stopped."
        if meta.get("needs_confirm"):
            return say or "That step needs confirmation — say confirm."
        return (say or f"Finished {proc.get('id')}.") if acted else (say or "Nothing ran.")
    except Exception as exc:
        # Fallback: sequential executor
        try:
            from neuron.brain import executor
            er = executor.execute_plan(plan, confirmed=confirmed)
            if er.needs_confirm:
                return er.needs_confirm.get("reason") or "Needs confirmation."
            if er.errors:
                return "I hit a problem: " + "; ".join(er.errors)
            return er.outcomes[-1] if er.outcomes else f"Finished {proc.get('id')}."
        except Exception as exc2:
            return f"Procedure failed: {exc2 or exc}"


def list_summary(limit: int = 12) -> str:
    rows = list_procedures()
    if not rows:
        return "No procedures yet. Say 'learn how I …' and demonstrate a workflow."
    lines = ["Learned procedures (NEURON never rewrites its own source — only these skills):"]
    for p in rows[-limit:]:
        n = len(p.get("steps") or [])
        src = "builtin" if p.get("builtin") else (p.get("source") or "learned")
        say0 = (p.get("say") or [p.get("id")])[0]
        lines.append(f"- {p.get('id')} ({n} steps, {src}) — say '{say0}'")
    return "\n".join(lines)


def _register_skill(proc: dict) -> None:
    """Expose procedure as a dotted skill tool, e.g. blender.new_project."""
    from neuron.brain import tool_registry
    from neuron.windows.result import ok, fail

    sid = proc["id"]

    def _handler(args, _id=sid):
        msg = run_procedure(proc_id=_id, query=str((args or {}).get("query") or ""), confirmed=bool((args or {}).get("confirmed")))
        low = (msg or "").lower()
        if any(x in low for x in ("don't have", "failed", "blocked", "problem")):
            return fail(msg)
        return ok(msg, method="procedure")

    tool_registry.register(
        sid,
        _handler,
        description=f"learned procedure: {sid}",
        args_schema={"query": "str"},
        risk="safe",
        overwrite=True,
    )
    alias = sid.replace(".", "_")
    if alias != sid:
        tool_registry.register(
            alias,
            _handler,
            description=f"learned procedure: {sid}",
            args_schema={"query": "str"},
            risk="safe",
            overwrite=True,
        )


def bootstrap_learned_skills() -> int:
    """Register all learned + builtin procedures as tools."""
    n = 0
    for p in list_procedures():
        try:
            _register_skill(p)
            n += 1
        except Exception:
            pass
    return n


# Tool-registry handlers
def run_procedure_tool(args: dict | None = None):
    args = args or {}
    msg = run_procedure(
        proc_id=str(args.get("id") or args.get("skill") or ""),
        query=str(args.get("query") or args.get("say") or ""),
        confirmed=bool(args.get("confirmed")),
    )
    try:
        from neuron.skills._util import as_result
        return as_result(msg, method="procedure")
    except Exception:
        return msg
