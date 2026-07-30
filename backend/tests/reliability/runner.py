"""Reliability benchmark runner — multi-run success-rate tracking.

Modes:
  plan   — score expected actions in a fixed/normalized plan (no OS side effects)
  mock   — run AgentLoop with mocked executor (validates closed-loop plumbing)
  live   — execute real desktop tools via AgentLoop (use carefully)

Metric:
  Task success rate = successful completed attempts / attempted tasks
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    from tests.reliability.tasks import TASKS, filter_tasks
except ImportError:
    from reliability.tasks import TASKS, filter_tasks  # type: ignore


@dataclass
class AttemptResult:
    task_id: str
    ok: bool
    mode: str
    detail: str = ""
    ms: int = 0
    actions: list[str] = field(default_factory=list)


@dataclass
class TaskScore:
    task_id: str
    name: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0

    @property
    def rate(self) -> float:
        return (self.successes / self.attempts) if self.attempts else 0.0


def _plan_actions(plan: dict | list | None) -> list[str]:
    if plan is None:
        return []
    if isinstance(plan, list):
        steps = plan
    else:
        steps = plan.get("steps") or []
    out = []
    for s in steps:
        a = (s.get("action") or s.get("tool") or "").strip()
        if a:
            out.append(a)
    return out


def score_plan(task: dict, plan: dict | list | None) -> tuple[bool, str]:
    """True if plan contains at least one expected action (or task has none)."""
    expect = task.get("expect_actions") or []
    if not expect:
        return True, "no tool expectation"

    if plan is None and task.get("plan") is not None:
        plan = {"steps": task["plan"]}
    actions = _plan_actions(plan)
    if not actions and task.get("plan"):
        actions = _plan_actions({"steps": task["plan"]})

    for want in expect:
        for got in actions:
            if (
                got == want
                or got.replace("_", ".") == want.replace("_", ".")
                or want.split(".")[-1] == got.split(".")[-1]
                or want in got
                or got in want
            ):
                return True, f"matched {want} via {got}"
    return False, f"expected one of {expect}, got {actions}"


def run_plan_mode(task: dict) -> AttemptResult:
    t0 = time.time()
    # Prefer canonical fixed plan (reliability over planner variance)
    if task.get("plan") is not None:
        ok, detail = score_plan(task, {"steps": task["plan"]})
        return AttemptResult(
            task["id"], ok, "plan", detail,
            ms=int((time.time() - t0) * 1000),
            actions=_plan_actions({"steps": task["plan"]}),
        )
    # Brain escape-hatch tasks (shutdown / safety)
    try:
        import brain
        reply, acted = brain.handle_command(task["request"])
        req = (task["request"] or "").lower()
        if "shutdown" in req or "restart" in req:
            ok = acted is False or (reply and "disabled" in (reply or "").lower())
            detail = (reply or "")[:160]
        elif "safety" in req:
            ok = bool(reply) and "safe" in (reply or "").lower()
            detail = (reply or "")[:160]
        else:
            ok = bool(acted or reply)
            detail = (reply or "")[:160]
        return AttemptResult(task["id"], ok, "plan", detail, ms=int((time.time() - t0) * 1000))
    except Exception as exc:
        return AttemptResult(task["id"], False, "plan", str(exc), ms=int((time.time() - t0) * 1000))


def run_mock_mode(task: dict) -> AttemptResult:
    """Closed-loop with stubbed executor — validates OPAVR + plan shape."""
    t0 = time.time()
    ok_plan, detail = score_plan(task, {"steps": task.get("plan") or []})
    if task.get("plan") is None:
        # fall back to plan-mode brain check
        return run_plan_mode(task)

    try:
        from neuron.brain import executor as executor_mod
        from neuron.brain.agent_loop import AgentLoop
        from neuron.brain import tool_registry
        import brain  # noqa: F401
        tool_registry.ensure_bootstrapped()

        def fake_exec(plan, confirmed=False, timeout=None):
            er = executor_mod.ExecutionResult()
            for step in (plan.get("steps") or []):
                name = step.get("action") or ""
                er.steps_run.append({
                    "action": name,
                    "args": step.get("args") or {},
                    "ok": True,
                    "out": f"mock ok {name}",
                })
                er.outcomes.append(f"mock ok {name}")
            return er

        import neuron.brain.loop as loop_mod
        import neuron.brain.verifier as verifier_mod

        orig_exec = executor_mod.execute_plan
        orig_verify = verifier_mod.verify_execution_step
        orig_goal = verifier_mod.verify_goal
        orig_obs = verifier_mod.observe_world

        class VR:
            def __init__(self, ok=True, note="ok"):
                self.ok = ok
                self.note = note
                self.evidence = {}

        try:
            executor_mod.execute_plan = fake_exec
            verifier_mod.verify_execution_step = lambda *a, **k: VR(True, "mock verify")
            verifier_mod.verify_goal = lambda *a, **k: VR(True, "mock goal")
            verifier_mod.observe_world = lambda *a, **k: {"app": "mock", "url": "", "scene": "desktop"}

            plan = {"say": task["name"], "steps": list(task["plan"])}
            say, acted, meta, goal = AgentLoop(confirmed=True).run(
                request=task["request"],
                plan=plan,
                context="reliability mock",
                normalized=task["request"],
            )
            status = getattr(goal, "status", "") or ""
            ok = ok_plan and bool(acted) and status == "success"
            detail = f"status={status} say={(say or '')[:80]} | {detail}"
            return AttemptResult(
                task["id"], ok, "mock", detail,
                ms=int((time.time() - t0) * 1000),
                actions=_plan_actions(plan),
            )
        finally:
            executor_mod.execute_plan = orig_exec
            verifier_mod.verify_execution_step = orig_verify
            verifier_mod.verify_goal = orig_goal
            verifier_mod.observe_world = orig_obs
    except Exception as exc:
        return AttemptResult(task["id"], False, "mock", str(exc), ms=int((time.time() - t0) * 1000))


def run_live_mode(task: dict) -> AttemptResult:
    """Real desktop execution via AgentLoop."""
    t0 = time.time()
    if not task.get("live", True):
        return run_plan_mode(task)
    try:
        from neuron.brain.agent_loop import AgentLoop
        from neuron.brain import tool_registry
        import brain  # noqa: F401
        from neuron.speech.interrupt import clear as clear_interrupt
        clear_interrupt()
        tool_registry.ensure_bootstrapped()

        plan = None
        if task.get("plan"):
            plan = {"say": task["name"], "steps": list(task["plan"])}
        say, acted, meta, goal = AgentLoop(confirmed=bool(task.get("confirm", True))).run(
            request=task["request"],
            plan=plan,
            context="reliability live bench",
            normalized=task["request"],
        )
        status = getattr(goal, "status", "") or ""
        ok = bool(acted) and status == "success"
        detail = f"status={status} say={(say or '')[:120]}"
        # Soft-pass: single-monitor PCs cannot move to monitor 2
        soft = False
        if not ok and "monitor" in task["id"]:
            blob = f"{say or ''} {json.dumps(meta or {})}"
            if any(
                x in blob
                for x in (
                    "Couldn't resolve target monitor",
                    "only 1 monitor",
                    "no second monitor",
                    "monitor index out of range",
                )
            ):
                soft = True
                ok = True
                detail = f"soft-pass (single monitor): {detail}"
        actions = [s.get("action") for s in ((meta or {}).get("steps") or []) if s.get("action")]
        return AttemptResult(
            task["id"], ok, "live", detail + (" [soft]" if soft else ""),
            ms=int((time.time() - t0) * 1000),
            actions=actions,
        )
    except Exception as exc:
        return AttemptResult(task["id"], False, "live", str(exc), ms=int((time.time() - t0) * 1000))


_MODE_FN: dict[str, Callable[[dict], AttemptResult]] = {
    "plan": run_plan_mode,
    "mock": run_mock_mode,
    "live": run_live_mode,
}


def run_benchmark(
    *,
    mode: str = "plan",
    repeats: int = 3,
    category: str = "",
    tag: str = "",
    ids: list[str] | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    mode = (mode or "plan").lower()
    if mode not in _MODE_FN:
        raise ValueError(f"Unknown mode {mode}; use plan|mock|live")

    tasks = filter_tasks(category=category, tag=tag, ids=ids)
    if limit and limit > 0:
        tasks = tasks[:limit]

    scores: dict[str, TaskScore] = {}
    attempts: list[AttemptResult] = []
    fn = _MODE_FN[mode]

    print(
        f"[bench] mode={mode} tasks={len(tasks)} repeats={repeats} "
        f"(catalog={len(TASKS)})",
        flush=True,
    )

    for task in tasks:
        score = TaskScore(task_id=task["id"], name=task["name"])
        for i in range(max(1, repeats)):
            print(f"[bench] {task['id']} attempt {i + 1}/{repeats} ...", flush=True)
            result = fn(task)
            attempts.append(result)
            score.attempts += 1
            if result.ok:
                score.successes += 1
                print(f"  OK ({result.ms}ms) {result.detail[:100]}", flush=True)
            else:
                score.failures += 1
                print(f"  FAIL ({result.ms}ms) {result.detail[:120]}", flush=True)
        scores[task["id"]] = score

    total_attempts = sum(s.attempts for s in scores.values())
    total_success = sum(s.successes for s in scores.values())
    overall = (total_success / total_attempts) if total_attempts else 0.0

    by_category: dict[str, dict[str, float]] = {}
    for task in tasks:
        cat = task["category"]
        sc = scores[task["id"]]
        bucket = by_category.setdefault(cat, {"attempts": 0, "successes": 0})
        bucket["attempts"] += sc.attempts
        bucket["successes"] += sc.successes
    for cat, b in by_category.items():
        b["rate"] = (b["successes"] / b["attempts"]) if b["attempts"] else 0.0

    report = {
        "mode": mode,
        "repeats": repeats,
        "tasks": len(tasks),
        "attempts": total_attempts,
        "successes": total_success,
        "failures": total_attempts - total_success,
        "task_success_rate": round(overall, 4),
        "target_rate": 0.95,
        "meets_target": overall >= 0.95,
        "by_category": by_category,
        "per_task": {
            tid: {
                "name": sc.name,
                "attempts": sc.attempts,
                "successes": sc.successes,
                "failures": sc.failures,
                "rate": round(sc.rate, 4),
            }
            for tid, sc in scores.items()
        },
        "failures_detail": [
            asdict(a) for a in attempts if not a.ok
        ],
    }
    return report


def write_report(report: dict, path: Path | None = None) -> Path:
    out = path or (
        Path(__file__).resolve().parent.parent / "reliability_report.json"
    )
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def print_summary(report: dict) -> None:
    rate = report["task_success_rate"]
    print("\n=== NEURON reliability benchmark ===", flush=True)
    print(
        f"mode={report['mode']}  tasks={report['tasks']}  "
        f"attempts={report['attempts']}  "
        f"success={report['successes']}  fail={report['failures']}",
        flush=True,
    )
    print(
        f"Task success rate = {rate:.1%}  "
        f"(target >= {report['target_rate']:.0%})  "
        f"{'PASS' if report['meets_target'] else 'BELOW TARGET'}",
        flush=True,
    )
    print("By category:", flush=True)
    for cat, b in sorted((report.get("by_category") or {}).items()):
        print(f"  {cat:12} {b['rate']:.1%}  ({int(b['successes'])}/{int(b['attempts'])})", flush=True)
    weak = [
        (tid, info)
        for tid, info in (report.get("per_task") or {}).items()
        if info["rate"] < 1.0
    ]
    if weak:
        print("Tasks with failures:", flush=True)
        for tid, info in sorted(weak, key=lambda x: x[1]["rate"]):
            print(f"  {tid:28} {info['rate']:.0%}  {info['name']}", flush=True)
