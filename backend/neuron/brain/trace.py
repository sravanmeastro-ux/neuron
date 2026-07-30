"""Phase 9 — structured OPAVR trace logs."""

from __future__ import annotations

import json
import time
from typing import Any


PHASES = (
    "USER",
    "CONTEXT",
    "PLAN",
    "ACTION",
    "RESULT",
    "VERIFICATION",
    "REPLAN",
    "FINAL",
)


class Trace:
    """Collects and prints structured agent-loop events."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.t0 = time.time()

    def _emit(self, phase: str, payload: Any = None, **extra: Any) -> None:
        phase = (phase or "").upper()
        entry: dict[str, Any] = {
            "phase": phase,
            "t_ms": int((time.time() - self.t0) * 1000),
        }
        if payload is not None:
            entry["data"] = payload
        entry.update(extra)
        self.events.append(entry)
        text = _fmt(payload if payload is not None else extra)
        print(f"[opavr] {phase}: {text}", flush=True)

    def user(self, text: str) -> None:
        self._emit("USER", str(text or "")[:500])

    def context(self, blob: str | dict) -> None:
        if isinstance(blob, dict):
            self._emit("CONTEXT", blob)
        else:
            self._emit("CONTEXT", str(blob or "")[:800])

    def plan(self, plan: dict | None) -> None:
        if not plan:
            self._emit("PLAN", {"steps": [], "say": ""})
            return
        steps = plan.get("steps") or []
        compact = [
            {"action": s.get("action"), "args": s.get("args") or {}}
            for s in steps
        ]
        self._emit("PLAN", {"say": (plan.get("say") or "")[:200], "steps": compact})

    def action(self, step: dict) -> None:
        self._emit(
            "ACTION",
            {"action": step.get("action"), "args": step.get("args") or {}},
        )

    def result(self, ok: bool, message: str = "", **extra: Any) -> None:
        data = {"ok": bool(ok), "message": str(message or "")[:400]}
        data.update(extra)
        self._emit("RESULT", data)

    def verification(self, ok: bool, note: str = "", **extra: Any) -> None:
        data = {"ok": bool(ok), "note": str(note or "")[:400]}
        data.update(extra)
        self._emit("VERIFICATION", data)

    def replan(self, reason: str, new_steps: list | None = None) -> None:
        self._emit(
            "REPLAN",
            {
                "reason": str(reason or "")[:300],
                "steps": [
                    {"action": s.get("action"), "args": s.get("args") or {}}
                    for s in (new_steps or [])
                ],
            },
        )

    def final(self, status: str, say: str = "", **extra: Any) -> None:
        data = {"status": status, "say": str(say or "")[:400]}
        data.update(extra)
        self._emit("FINAL", data)

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)


def _fmt(payload: Any) -> str:
    try:
        if isinstance(payload, str):
            text = payload.replace("\n", " | ")[:500]
        else:
            text = json.dumps(payload, ensure_ascii=True, default=str)[:500]
    except Exception:
        text = str(payload)[:500]
    # Windows consoles (cp1252) can't print many unicode chars
    try:
        return text.encode("ascii", "replace").decode("ascii")
    except Exception:
        return text
