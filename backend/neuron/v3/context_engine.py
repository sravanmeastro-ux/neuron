"""V3 ContextEngine — session-scoped short-term context + WorldState events.

Composes (does not replace):
  - WorldState (verified computer picture)
  - ComputerState / observe_world (live capture)
  - memory.scopes Session/Working (conversation + apps)

Does NOT continuously record user activity.
Does NOT store passwords / credentials / private field contents.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from neuron.v3.world_state import WorldState, _is_sensitive_key, _scrub_args


@dataclass
class EntityRef:
    kind: str  # app | site | file | folder | ui | other
    name: str
    at: float = 0.0


@dataclass
class CommandRecord:
    text: str
    at: float
    role: str = "user"


@dataclass
class ActionRecord:
    action: str
    args: dict[str, Any]
    ok: bool
    detail: str
    verified: bool
    at: float


@dataclass
class TaskResult:
    goal: str
    status: str
    say: str
    at: float


class ContextEngine:
    """Central short-term context + event API for AgentLoop."""

    MAX_COMMANDS = 20
    MAX_ACTIONS = 30
    MAX_ENTITIES = 40
    MAX_FILES = 20
    MAX_RESULTS = 16

    def __init__(self) -> None:
        self.world = WorldState()
        self.recent_commands: deque[CommandRecord] = deque(maxlen=self.MAX_COMMANDS)
        self.recent_actions: deque[ActionRecord] = deque(maxlen=self.MAX_ACTIONS)
        self.recent_entities: deque[EntityRef] = deque(maxlen=self.MAX_ENTITIES)
        self.recent_files: deque[str] = deque(maxlen=self.MAX_FILES)
        self.task_results: deque[TaskResult] = deque(maxlen=self.MAX_RESULTS)
        self._task_started_at: float = 0.0
        self._enabled = True

    # ------------------------------------------------------------------ events

    def on_user_command(self, text: str) -> None:
        scrubbed = scrub_text(text)
        if not scrubbed:
            return
        self.recent_commands.append(
            CommandRecord(text=scrubbed[:240], at=time.time(), role="user")
        )
        try:
            from neuron.memory import scopes
            scopes.session().log("user", scrubbed[:400])
        except Exception:
            pass

    def on_task_started(self, goal: str) -> None:
        g = scrub_text(goal)[:200]
        self.world.begin_task(g)
        self._task_started_at = time.time()
        try:
            from neuron.memory import scopes
            scopes.working().begin_task(g)
        except Exception:
            pass

    def on_action_attempted(self, action: str, args: dict | None = None) -> None:
        clean_args = _scrub_args(args or {})
        self.world.record_attempt(action, clean_args)
        self._note_entities_from_args(action, clean_args)
        # Intentionally do NOT set world.active_app from open_app args here.

    def on_action_verified(
        self,
        action: str,
        result: str,
        observation: dict | None = None,
        *,
        args: dict | None = None,
    ) -> None:
        prior_args = {}
        if self.world.pending_attempt:
            prior_args = dict(self.world.pending_attempt.args or {})
        if args:
            prior_args.update(_scrub_args(args))
        self.world.confirm_action(
            action=action,
            result=scrub_text(result)[:240],
            observation=observation,
            ok=True,
        )
        self.recent_actions.append(
            ActionRecord(
                action=(action or "")[:80],
                args=prior_args,
                ok=True,
                detail=scrub_text(result)[:200],
                verified=True,
                at=time.time(),
            )
        )
        self._note_entities_from_args(action, prior_args)
        if observation:
            self._sync_session_from_obs(observation)

    def on_action_failed(
        self,
        action: str,
        error: str,
        observation: dict | None = None,
        *,
        args: dict | None = None,
    ) -> None:
        prior_args = {}
        if self.world.pending_attempt:
            prior_args = dict(self.world.pending_attempt.args or {})
        if args:
            prior_args.update(_scrub_args(args))
        self.world.fail_action(action, scrub_text(error)[:240], observation)
        self.recent_actions.append(
            ActionRecord(
                action=(action or "")[:80],
                args=prior_args,
                ok=False,
                detail=scrub_text(error)[:200],
                verified=False,
                at=time.time(),
            )
        )
        if observation:
            self._sync_session_from_obs(observation)

    def on_window_changed(self, observation: dict | None = None) -> None:
        if not observation:
            return
        changed = self.world.apply_observation(observation)
        if changed:
            self._sync_session_from_obs(observation)

    def on_task_completed(self, status: str, say: str = "") -> None:
        self.world.complete_task(status)
        self.task_results.append(
            TaskResult(
                goal=self.world.current_goal[:160],
                status=(status or "")[:40],
                say=scrub_text(say)[:200],
                at=time.time(),
            )
        )
        try:
            from neuron.memory import scopes
            if say:
                scopes.session().log("neuron", scrub_text(say)[:400])
            scopes.working().sync_goal_state(
                type("G", (), {
                    "goal": self.world.current_goal,
                    "status": self.world.task_status,
                    "pending_steps": [],
                    "completed_steps": [],
                    "errors": [self.world.last_error] if self.world.last_error else [],
                    "action_history": [],
                })()
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ load

    def load_for_command(self, text: str = "") -> str:
        """Return planner-facing context blob (session-scoped, bounded)."""
        if text:
            # soft refresh — do not treat as full command event if already logged
            pass
        chunks = [
            self.world.compact(480),
            self._recent_commands_blob(),
            self._recent_entities_blob(),
            self._recent_files_blob(),
        ]
        try:
            from neuron.memory import scopes
            chunks.append(scopes.session().compact(400))
            chunks.append(scopes.working().compact(350))
        except Exception:
            pass
        text_out = "\n\n".join(c for c in chunks if c)
        return text_out[:2200]

    def refresh_observation(self, hint: str = "") -> dict[str, Any]:
        """Optional live peek via existing verifier (may be slow)."""
        try:
            from neuron.brain import verifier
            world = verifier.observe_world(hint or self.world.current_goal or "desktop")
            self.world.apply_observation(world)
            return world
        except Exception as exc:
            return {"error": str(exc)}

    def reset_session(self) -> None:
        self.world = WorldState()
        self.recent_commands.clear()
        self.recent_actions.clear()
        self.recent_entities.clear()
        self.recent_files.clear()
        self.task_results.clear()
        self._task_started_at = 0.0
        try:
            from neuron.memory import scopes
            scopes.session().clear()
            scopes.working().clear()
        except Exception:
            pass

    # ------------------------------------------------------------------ views

    def snapshot(self) -> dict[str, Any]:
        return {
            "world": self.world.to_dict(),
            "recent_commands": [asdict(c) for c in self.recent_commands],
            "recent_actions": [asdict(a) for a in self.recent_actions],
            "recent_entities": [asdict(e) for e in self.recent_entities],
            "recent_files": list(self.recent_files),
            "task_results": [asdict(t) for t in self.task_results],
        }

    def compact_for_planner(self, max_chars: int = 1200) -> str:
        blob = self.load_for_command()
        return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"

    # ------------------------------------------------------------------ helpers

    def _note_entities_from_args(self, action: str, args: dict[str, Any]) -> None:
        act = (action or "").lower()
        for key, val in (args or {}).items():
            if _is_sensitive_key(str(key)):
                continue
            s = str(val or "").strip()
            if not s or s == "[redacted]":
                continue
            kind = "other"
            kl = str(key).lower()
            if kl in ("name", "app", "application", "title") or "open_app" in act or "focus_app" in act:
                kind = "app"
            elif kl in ("site", "url") or "website" in act or "http" in s:
                kind = "site"
            elif kl in ("path", "file", "query") and (
                "/" in s or "\\" in s or s.endswith((".pdf", ".png", ".blend", ".txt", ".docx"))
            ):
                kind = "file"
                self._note_file(s)
            elif kl in ("location", "folder", "root") or "folder" in act:
                kind = "folder"
                self._note_file(s)
            elif kl in ("query",) and "search" in act:
                kind = "other"
            self._note_entity(kind, s)

    def _note_entity(self, kind: str, name: str) -> None:
        name = scrub_text(name)[:80]
        if not name:
            return
        # de-dupe keeping newest
        existing = [e for e in self.recent_entities if e.name.lower() != name.lower()]
        self.recent_entities = deque(existing, maxlen=self.MAX_ENTITIES)
        self.recent_entities.append(EntityRef(kind=kind, name=name, at=time.time()))

    def _note_file(self, path: str) -> None:
        p = scrub_text(path)[:160]
        if not p or _is_sensitive_key(p):
            return
        items = [x for x in self.recent_files if x.lower() != p.lower()]
        self.recent_files = deque(items, maxlen=self.MAX_FILES)
        self.recent_files.append(p)

    def _sync_session_from_obs(self, world: dict[str, Any]) -> None:
        try:
            from neuron.memory import scopes
            app = world.get("active_application") or world.get("app")
            if app:
                scopes.session().note_app(str(app))
                self._note_entity("app", str(app))
            mid = world.get("focused_monitor")
            if mid is not None:
                scopes.session().note_monitor(mid)
            url = world.get("url") or world.get("browser_url")
            if url:
                scopes.session().note_site(str(url)[:80])
                self._note_entity("site", str(url)[:80])
        except Exception:
            pass

    def _recent_commands_blob(self) -> str:
        if not self.recent_commands:
            return ""
        lines = ["RECENT_COMMANDS:"]
        for c in list(self.recent_commands)[-5:]:
            lines.append(f"- {c.text[:100]}")
        return "\n".join(lines)

    def _recent_entities_blob(self) -> str:
        if not self.recent_entities:
            return ""
        bits = [f"{e.kind}:{e.name}" for e in list(self.recent_entities)[-8:]]
        return "ENTITIES=[" + ", ".join(bits) + "]"

    def _recent_files_blob(self) -> str:
        if not self.recent_files:
            return ""
        return "FILES=[" + ", ".join(list(self.recent_files)[-6:]) + "]"


# ---------------------------------------------------------------------------
# Sensitive scrubbing
# ---------------------------------------------------------------------------

_SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token|credential|ssn|credit\s*card)\s*[:=]\s*\S+"
)


def scrub_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = _SENSITIVE_RE.sub(r"\1=[redacted]", t)
    return t


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_ENGINE: ContextEngine | None = None


def get_engine() -> ContextEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = ContextEngine()
    return _ENGINE


def reset_engine() -> ContextEngine:
    """Test helper — wipe singleton."""
    global _ENGINE
    _ENGINE = ContextEngine()
    return _ENGINE
