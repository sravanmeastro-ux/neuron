"""Phase 9 — GoalState for multi-step Observe→Plan→Act→Verify→Recover."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GoalState:
    """Tracks a user goal across steps without restarting the whole task."""

    goal: str = ""
    current_state: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    pending_steps: list[dict[str, Any]] = field(default_factory=list)
    action_history: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    status: str = "running"  # running | success | failed | needs_confirm
    plan_say: str = ""
    observations: list[str] = field(default_factory=list)
    verify_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_plan(cls, goal: str, plan: dict | None, *, max_retries: int = 3) -> "GoalState":
        plan = plan or {}
        steps = list(plan.get("steps") or [])
        return cls(
            goal=(goal or "").strip(),
            pending_steps=[dict(s) for s in steps],
            plan_say=(plan.get("say") or "").strip(),
            max_retries=int(max_retries),
            status="running",
        )

    def compact(self, max_chars: int = 1200) -> str:
        lines = [
            f"GOAL: {self.goal}",
            f"STATUS: {self.status}",
            f"RETRY: {self.retry_count}/{self.max_retries}",
            f"COMPLETED: {len(self.completed_steps)}",
            f"PENDING: {len(self.pending_steps)}",
        ]
        if self.current_state:
            bits = []
            for k in ("app", "window", "url", "scene", "process_running", "window_exists"):
                if k in self.current_state and self.current_state[k] not in (None, ""):
                    bits.append(f"{k}={self.current_state[k]}")
            if bits:
                lines.append("STATE: " + "; ".join(bits)[:300])
        if self.completed_steps:
            done = []
            for s in self.completed_steps[-4:]:
                done.append(f"{s.get('action')}(ok)")
            lines.append("DONE: " + ", ".join(done))
        if self.pending_steps:
            pend = []
            for s in self.pending_steps[:4]:
                pend.append(str(s.get("action") or "?"))
            lines.append("NEXT: " + ", ".join(pend))
        if self.errors:
            lines.append("ERRORS: " + "; ".join(self.errors[-3:])[:280])
        if self.verify_notes:
            lines.append("VERIFY: " + "; ".join(self.verify_notes[-3:])[:280])
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def update_observation(self, obs: dict[str, Any] | None, note: str = "") -> None:
        if obs:
            self.current_state.update(obs)
        if note:
            self.observations.append(note[:300])
            if len(self.observations) > 20:
                self.observations = self.observations[-20:]

    def record_action(self, step: dict, result: dict[str, Any]) -> None:
        entry = {
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": bool(result.get("ok")),
            "out": str(result.get("out") or "")[:400],
            "ms": result.get("ms"),
        }
        self.action_history.append(entry)
        if len(self.action_history) > 40:
            self.action_history = self.action_history[-40:]

    def complete_current(self, step: dict, result: dict[str, Any], verify_note: str = "") -> None:
        self.record_action(step, result)
        done = dict(step)
        done["result"] = result
        done["verify"] = verify_note
        self.completed_steps.append(done)
        if self.pending_steps and self.pending_steps[0].get("action") == step.get("action"):
            self.pending_steps.pop(0)
        elif step in self.pending_steps:
            self.pending_steps.remove(step)
        else:
            # Pop by identity of first pending when actions match after recover rewrite
            if self.pending_steps:
                self.pending_steps.pop(0)
        if verify_note:
            self.verify_notes.append(verify_note[:300])

    def fail_current(self, step: dict, error: str, result: dict[str, Any] | None = None) -> None:
        self.errors.append(error[:400])
        if result is not None:
            self.record_action(step, result)
        else:
            self.record_action(step, {"ok": False, "out": error})

    def set_pending(self, steps: list[dict]) -> None:
        self.pending_steps = [dict(s) for s in (steps or []) if s]

    def bump_retry(self) -> bool:
        """Increment retry; return False if budget exhausted."""
        self.retry_count += 1
        return self.retry_count <= self.max_retries

    def mark_success(self) -> None:
        self.status = "success"
        self.pending_steps = []

    def mark_failed(self, reason: str = "") -> None:
        self.status = "failed"
        if reason:
            self.errors.append(reason[:400])

    def honest_failure_message(self) -> str:
        """Explain failure — never pretend success."""
        parts = [f"I couldn't complete: {self.goal or 'the request'}."]
        if self.completed_steps:
            done = ", ".join(s.get("action") or "?" for s in self.completed_steps)
            parts.append(f"Finished: {done}.")
        if self.errors:
            parts.append("Problem: " + self.errors[-1])
        elif self.verify_notes:
            parts.append("Verification: " + self.verify_notes[-1])
        if self.pending_steps:
            pend = ", ".join(s.get("action") or "?" for s in self.pending_steps[:3])
            parts.append(f"Still pending: {pend}.")
        return " ".join(parts)
