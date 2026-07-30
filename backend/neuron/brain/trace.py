"""Phase 9 — structured OPAVR trace logs."""

from __future__ import annotations

import json
import time
from typing import Any


PHASES = (
    "USER",
    "CONTEXT",
    "PLAN",
    "OBSERVE",
    "ACTION",
    "RESULT",
    "VERIFICATION",
    "DIAGNOSE",
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
        compact = [_compact_step(s) for s in steps]
        self._emit("PLAN", {"say": (plan.get("say") or "")[:200], "steps": compact})

    def observe(self, world: dict | None = None, note: str = "") -> None:
        data = dict(world or {})
        if note:
            data["note"] = note
        slim = {
            k: data.get(k)
            for k in (
                "note", "app", "window", "url", "scene", "hint",
                "screen_sources", "hint_on_screen", "focused_monitor",
                "active_application",
            )
            if data.get(k) not in (None, "", [])
        }
        # Compact screen evidence without dumping full OCR blobs into logs
        if data.get("visible_text"):
            vt = data["visible_text"]
            if isinstance(vt, list):
                slim["visible_text"] = vt[:8]
            else:
                slim["visible_text"] = str(vt)[:200]
        if data.get("world_model"):
            # Keep first ~400 chars of the structured multi-monitor map
            slim["world_model"] = str(data["world_model"])[:400]
        if data.get("ui_changed") is not None:
            slim["ui_changed"] = data.get("ui_changed")
        if data.get("ui_change") and isinstance(data["ui_change"], dict):
            slim["ui_change"] = (data["ui_change"].get("reason") or "")[:120]
        if data.get("fingerprint"):
            slim["fingerprint"] = data.get("fingerprint")
        self._emit("OBSERVE", slim or data)

    def action(self, step: dict) -> None:
        self._emit("ACTION", _compact_step(step))

    def result(self, ok: bool, message: str = "", **extra: Any) -> None:
        data = {"ok": bool(ok), "message": str(message or "")[:400]}
        data.update(extra)
        self._emit("RESULT", data)

    def verification(self, ok: bool, note: str = "", **extra: Any) -> None:
        data = {"ok": bool(ok), "note": str(note or "")[:400]}
        data.update(extra)
        self._emit("VERIFICATION", data)

    def diagnose(self, diagnosis: dict | None = None) -> None:
        self._emit("DIAGNOSE", dict(diagnosis or {}))

    def replan(self, reason: str, new_steps: list | None = None) -> None:
        self._emit(
            "REPLAN",
            {
                "reason": str(reason or "")[:300],
                "steps": [_compact_step(s) for s in (new_steps or [])],
            },
        )

    def final(self, status: str, say: str = "", **extra: Any) -> None:
        data = {"status": status, "say": str(say or "")[:400]}
        data.update(extra)
        self._emit("FINAL", data)

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)


def _compact_step(s: dict | None) -> dict:
    s = s or {}
    out = {
        "action": s.get("action"),
        "args": s.get("args") or {},
    }
    if s.get("target"):
        out["target"] = s.get("target")
    if s.get("expected_result"):
        out["expected_result"] = str(s.get("expected_result"))[:120]
    if s.get("timeout") is not None:
        out["timeout"] = s.get("timeout")
    if s.get("retry_limit") is not None:
        out["retry_limit"] = s.get("retry_limit")
    return out


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
