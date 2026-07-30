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
    if "project" in g and app == "blender":
        action = "new_project"
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
    """Persist a learned procedure. Refuses source-modifying steps."""
    sid = (skill_id or "").strip().lower()
    if not sid or "." not in sid:
        return False, "Skill id must look like domain.name (e.g. blender.new_project).", None
    if not steps:
        return False, "No steps to save.", None

    clean: list[dict] = []
    for s in steps:
        if rejects_source_write(s):
            return False, "Refusing to learn a procedure that modifies NEURON source code.", None
        action = str(s.get("action") or s.get("tool") or "").strip()
        if not action:
            continue
        # Ban shell that writes to repo
        args = dict(s.get("args") or {})
        if action in ("run_shell", "run_powershell", "create_file") and rejects_source_write(args):
            return False, "Refusing shell/file step that targets project source.", None
        step = {
            "action": action,
            "args": args,
            "target": s.get("target") or "",
            "expected_result": s.get("expected_result") or s.get("expect") or "",
        }
        clean.append(step)

    if not clean:
        return False, "No usable steps after filtering.", None

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
            # Prefer builtin steps if demonstration empty (handled by caller)
            break

    proc = {
        "id": sid,
        "domain": domain,
        "name": name,
        "say": phrases,
        "steps": clean,
        "builtin": False,
        "source": source,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": meta or {},
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

    return True, f"Learned skill {sid} ({len(clean)} steps). Say: '{phrases[0]}'.", proc


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
    """Convert a click_recorder recipe into AgentLoop steps."""
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
        x, y = raw.get("x"), raw.get("y")
        button = raw.get("button") or "left"
        if name and len(name) >= 2:
            steps.append({
                "action": "click_element",
                "args": {"name": name},
                "target": name,
                "expected_result": f"clicked {name}",
            })
        elif x is not None and y is not None:
            steps.append({
                "action": "click",
                "args": {"x": int(x), "y": int(y), "button": button},
                "target": f"({x},{y})",
                "expected_result": "click landed",
            })
        # Small wait between clicks
        steps.append({
            "action": "wait",
            "args": {"seconds": 0.4},
            "target": "between clicks",
            "expected_result": "ready for next step",
        })
    # Drop trailing wait
    while steps and steps[-1].get("action") == "wait" and len(steps) > 1:
        # keep one settle wait at end for verify
        break
    return steps


def run_procedure(proc_id: str = "", query: str = "", *, confirmed: bool = False) -> str:
    """Execute a learned/builtin procedure via AgentLoop."""
    proc = get(proc_id) if proc_id else None
    if not proc and query:
        proc = match(query)
    if not proc:
        return "I don't have a learned procedure for that yet. Say 'learn how I …' and demonstrate."

    for s in proc.get("steps") or []:
        if rejects_source_write(s):
            return "Blocked: this procedure targets source code and will not run."

    plan = {
        "say": f"Running {proc.get('id')}.",
        "steps": list(proc.get("steps") or []),
    }
    try:
        from neuron.brain.agent_loop import AgentLoop
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        say, acted, meta, goal = AgentLoop(confirmed=confirmed).run(
            request=query or proc.get("id") or "",
            plan=plan,
            context=f"Learned procedure {proc.get('id')} source={proc.get('source')}",
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
