"""Scoped memory for NEURON — Working / Session / Persistent.

Working memory  — current task + recent actions (RAM, task-lifetime).
Session memory  — conversation + apps used this run (RAM, until clear/restart).
Persistent memory — durable preferences/facts only, with allowlist controls.

Does not replace memory.py / neuron.memory.store — composes them.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Working memory — current task only
# ---------------------------------------------------------------------------


@dataclass
class WorkingMemory:
    """Ephemeral task state for the AgentLoop."""

    goal: str = ""
    status: str = ""  # running | success | failed | idle
    pending_steps: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    recent_actions: list[dict[str, Any]] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    updated_at: float = 0.0

    MAX_ACTIONS = 24
    MAX_OBS = 16

    def clear(self) -> None:
        self.goal = ""
        self.status = "idle"
        self.pending_steps = []
        self.completed_steps = []
        self.recent_actions = []
        self.observations = []
        self.errors = []
        self.started_at = 0.0
        self.updated_at = time.time()

    def begin_task(self, goal: str) -> None:
        self.clear()
        self.goal = (goal or "").strip()
        self.status = "running"
        self.started_at = time.time()
        self.updated_at = self.started_at

    def note_action(
        self,
        action: str,
        *,
        ok: bool = True,
        detail: str = "",
        args: dict | None = None,
    ) -> None:
        self.recent_actions.append({
            "t": time.strftime("%H:%M:%S"),
            "action": action,
            "ok": bool(ok),
            "detail": (detail or "")[:200],
            "args": {k: str(v)[:60] for k, v in (args or {}).items()},
        })
        if len(self.recent_actions) > self.MAX_ACTIONS:
            self.recent_actions = self.recent_actions[-self.MAX_ACTIONS:]
        self.updated_at = time.time()

    def note_observation(self, note: str) -> None:
        if not note:
            return
        self.observations.append(str(note)[:240])
        if len(self.observations) > self.MAX_OBS:
            self.observations = self.observations[-self.MAX_OBS:]
        self.updated_at = time.time()

    def sync_goal_state(self, goal_state: Any) -> None:
        """Pull fields from neuron.brain.goal.GoalState."""
        if goal_state is None:
            return
        self.goal = getattr(goal_state, "goal", None) or self.goal
        self.status = getattr(goal_state, "status", None) or self.status
        self.pending_steps = [
            str(s.get("action") or "?") for s in (getattr(goal_state, "pending_steps", None) or [])
        ]
        self.completed_steps = [
            str(s.get("action") or "?") for s in (getattr(goal_state, "completed_steps", None) or [])
        ]
        self.errors = list(getattr(goal_state, "errors", None) or [])[-8:]
        rebuilt: list[dict[str, Any]] = []
        for entry in (getattr(goal_state, "action_history", None) or [])[-self.MAX_ACTIONS:]:
            args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
            rebuilt.append({
                "t": time.strftime("%H:%M:%S"),
                "action": str(entry.get("action") or "?"),
                "ok": bool(entry.get("ok")),
                "detail": str(entry.get("out") or "")[:200],
                "args": {k: str(v)[:60] for k, v in args.items()},
            })
        if rebuilt:
            self.recent_actions = rebuilt
        self.updated_at = time.time()

    def compact(self, max_chars: int = 600) -> str:
        if not self.goal and not self.recent_actions:
            return ""
        lines = ["WORKING_MEMORY:"]
        if self.goal:
            lines.append(f"goal={self.goal} status={self.status or 'idle'}")
        if self.completed_steps:
            lines.append("done=[" + ", ".join(self.completed_steps[-6:]) + "]")
        if self.pending_steps:
            lines.append("next=[" + ", ".join(self.pending_steps[:4]) + "]")
        if self.recent_actions:
            bits = []
            for a in self.recent_actions[-5:]:
                mark = "ok" if a.get("ok") else "FAIL"
                bits.append(f"{a.get('action')}[{mark}]")
            lines.append("actions=[" + " | ".join(bits) + "]")
        if self.errors:
            lines.append("errors=[" + "; ".join(self.errors[-2:])[:180] + "]")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Session memory — this run only
# ---------------------------------------------------------------------------


@dataclass
class SessionMemory:
    """Conversation + apps touched since process start (or last clear)."""

    conversation: list[dict[str, str]] = field(default_factory=list)
    apps_used: list[str] = field(default_factory=list)
    sites_used: list[str] = field(default_factory=list)
    monitors_focused: list[int] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    MAX_CONV = 30
    MAX_APPS = 20

    def clear(self) -> None:
        self.conversation = []
        self.apps_used = []
        self.sites_used = []
        self.monitors_focused = []
        self.started_at = time.time()
        self.updated_at = self.started_at

    def log(self, role: str, text: str) -> None:
        self.conversation.append({
            "t": time.strftime("%H:%M:%S"),
            "role": (role or "").strip(),
            "text": (text or "").strip()[:400],
        })
        if len(self.conversation) > self.MAX_CONV:
            self.conversation = self.conversation[-self.MAX_CONV:]
        self.updated_at = time.time()

    def note_app(self, app: str) -> None:
        name = (app or "").strip()
        if not name:
            return
        # Keep unique, most-recent last
        self.apps_used = [a for a in self.apps_used if a.lower() != name.lower()]
        self.apps_used.append(name)
        if len(self.apps_used) > self.MAX_APPS:
            self.apps_used = self.apps_used[-self.MAX_APPS:]
        self.updated_at = time.time()

    def note_site(self, site: str) -> None:
        s = (site or "").strip()
        if not s:
            return
        self.sites_used = [x for x in self.sites_used if x.lower() != s.lower()]
        self.sites_used.append(s[:80])
        if len(self.sites_used) > self.MAX_APPS:
            self.sites_used = self.sites_used[-self.MAX_APPS:]
        self.updated_at = time.time()

    def note_monitor(self, monitor_id: int | None) -> None:
        if monitor_id is None:
            return
        try:
            mid = int(monitor_id)
        except (TypeError, ValueError):
            return
        self.monitors_focused = [m for m in self.monitors_focused if m != mid]
        self.monitors_focused.append(mid)
        if len(self.monitors_focused) > 6:
            self.monitors_focused = self.monitors_focused[-6:]
        self.updated_at = time.time()

    def compact(self, max_chars: int = 700) -> str:
        lines = ["SESSION_MEMORY:"]
        if self.apps_used:
            lines.append("apps=[" + ", ".join(self.apps_used[-8:]) + "]")
        if self.sites_used:
            lines.append("sites=[" + ", ".join(self.sites_used[-6:]) + "]")
        if self.monitors_focused:
            lines.append("monitors=[" + ", ".join(str(m) for m in self.monitors_focused[-4:]) + "]")
        if self.conversation:
            lines.append("chat:")
            for h in self.conversation[-4:]:
                lines.append(f"- {h.get('role')}: {(h.get('text') or '')[:80]}")
        if len(lines) == 1:
            return ""
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Persistent memory — durable facts with allowlist controls
# ---------------------------------------------------------------------------

# Only these key patterns may be written to durable storage by default.
PERSISTENT_ALLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^user\."),           # user.favorite_color
    re.compile(r"^pref\."),           # pref.tts_rate
    re.compile(r"^voice\."),          # voice.wake_required
    re.compile(r"^sticky\."),         # sticky.app / sticky.monitor
    re.compile(r"^default_"),         # default_browser
    re.compile(r"^(name|favorite|favourite|timezone|city|language)$"),
    re.compile(r"^(preferred_|my_).+"),
)

# Keys that must never be persisted (safety)
PERSISTENT_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"password|secret|token|api[_-]?key|credential|ssn|credit.?card", re.I),
    re.compile(r"^tmp\.|^working\.|^session\."),
)


@dataclass
class PersistentMemory:
    """Durable preferences/facts — SQLite/JSON via existing store, gated by policy."""

    last_write: str = ""
    last_denied: str = ""

    def is_allowed(self, key: str, *, force: bool = False) -> tuple[bool, str]:
        k = (key or "").strip().lower()
        if not k:
            return False, "empty key"
        for pat in PERSISTENT_DENY_PATTERNS:
            if pat.search(k):
                return False, f"denied by policy: '{k}' looks sensitive"
        if force:
            return True, "forced"
        for pat in PERSISTENT_ALLOW_PATTERNS:
            if pat.match(k):
                return True, "allowlisted"
        # Natural phrases like "favorite color" from voice → treat as user.*
        if " " in k or len(k.split()) <= 4:
            # Will be stored as user.<slug>
            return True, "user-fact"
        return False, (
            f"'{k}' is not allowlisted for persistent memory. "
            f"Use user./pref./voice. prefix, or say 'remember that my … is …'."
        )

    def _slug(self, key: str) -> str:
        k = (key or "").strip().lower()
        if k.startswith(("user.", "pref.", "voice.", "sticky.")):
            return k
        if re.match(r"^(name|favorite|favourite|timezone|city|language)$", k):
            return k
        if k.startswith(("preferred_", "my_", "default_")):
            return k
        # "favorite color" → user.favorite_color
        slug = re.sub(r"[^a-z0-9]+", "_", k).strip("_")
        return f"user.{slug}" if slug else k

    def remember(self, key: str, value: str, *, force: bool = False) -> tuple[bool, str]:
        allowed, reason = self.is_allowed(key, force=force)
        if not allowed:
            self.last_denied = reason
            return False, reason
        store_key = self._slug(key) if reason == "user-fact" else (key or "").strip().lower()
        if reason == "user-fact" and not store_key.startswith("user."):
            store_key = self._slug(key)
        val = (value or "").strip()
        if not val:
            return False, "empty value"
        try:
            import memory as mem
            # Write JSON + SQL via legacy API (bypass scopes recursion)
            data = mem._load()
            data.setdefault("facts", {})[store_key] = val
            mem._save(data)
        except Exception as exc:
            return False, f"json write failed: {exc}"
        try:
            from neuron.memory import store as sql
            sql.remember(store_key, val)
        except Exception:
            pass
        self.last_write = store_key
        return True, f"Remembered {store_key}."

    def recall(self, key: str) -> str | None:
        k = self._slug(key)
        try:
            from neuron.memory import store as sql
            val = sql.recall(k)
            if val is not None:
                return val
            # Also try raw key
            raw = sql.recall((key or "").strip().lower())
            if raw is not None:
                return raw
        except Exception:
            pass
        try:
            import memory as mem
            facts = mem._load().get("facts") or {}
            return facts.get(k) or facts.get((key or "").strip().lower())
        except Exception:
            return None

    def forget(self, key: str) -> tuple[bool, str]:
        k = self._slug(key)
        raw = (key or "").strip().lower()
        removed = False
        try:
            import memory as mem
            data = mem._load()
            facts = data.setdefault("facts", {})
            for cand in {k, raw}:
                if cand in facts:
                    del facts[cand]
                    removed = True
            mem._save(data)
        except Exception:
            pass
        try:
            from neuron.memory import store as sql
            sql.ensure()
            conn = sql._conn()
            for cand in {k, raw}:
                cur = conn.execute("DELETE FROM facts WHERE key=?", (cand,))
                if cur.rowcount:
                    removed = True
            conn.commit()
            conn.close()
        except Exception:
            pass
        if removed:
            return True, f"Forgot {k}."
        return False, f"No persistent fact named '{key}'."

    def list_facts(self, limit: int = 20) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            from neuron.memory import store as sql
            sql.ensure()
            conn = sql._conn()
            rows = conn.execute(
                "SELECT key, value FROM facts ORDER BY updated DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            conn.close()
            for r in rows:
                out[str(r["key"])] = str(r["value"])
        except Exception:
            try:
                import memory as mem
                facts = mem._load().get("facts") or {}
                for i, (k, v) in enumerate(facts.items()):
                    if i >= limit:
                        break
                    out[str(k)] = str(v)
            except Exception:
                pass
        return out

    def clear(self, *, confirm: bool = False) -> tuple[bool, str]:
        if not confirm:
            return False, "Refusing to clear persistent memory without confirm=True."
        try:
            import memory as mem
            data = mem._load()
            data["facts"] = {}
            mem._save(data)
        except Exception as exc:
            return False, str(exc)
        try:
            from neuron.memory import store as sql
            sql.ensure()
            conn = sql._conn()
            conn.execute("DELETE FROM facts")
            conn.commit()
            conn.close()
        except Exception:
            pass
        return True, "Cleared all persistent facts."

    def compact(self, max_chars: int = 500) -> str:
        facts = self.list_facts(10)
        if not facts:
            return ""
        lines = ["PERSISTENT_MEMORY:"]
        for k, v in facts.items():
            lines.append(f"- {k}: {v}")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

_working = WorkingMemory()
_session = SessionMemory()
_persistent = PersistentMemory()


def working() -> WorkingMemory:
    return _working


def session() -> SessionMemory:
    return _session


def persistent() -> PersistentMemory:
    return _persistent


def clear_working() -> str:
    _working.clear()
    return "Cleared working memory (current task)."


def clear_session() -> str:
    _session.clear()
    return "Cleared session memory (conversation + apps this session)."


def clear_persistent(*, confirm: bool = False) -> str:
    ok, msg = _persistent.clear(confirm=confirm)
    return msg


def clear_all(*, confirm_persistent: bool = False) -> str:
    parts = [clear_working(), clear_session()]
    if confirm_persistent:
        parts.append(clear_persistent(confirm=True))
    else:
        parts.append("Persistent memory kept (say 'forget everything permanently' to wipe facts).")
    return " ".join(parts)


def context_blob(request: str = "", *, include_persistent: bool = True) -> str:
    """Scoped context for the planner — working → session → persistent."""
    chunks: list[str] = []
    w = _working.compact()
    if w:
        chunks.append(w)
    s = _session.compact()
    if s:
        chunks.append(s)
    if include_persistent:
        p = _persistent.compact()
        if p:
            chunks.append(p)
    return "\n\n".join(chunks)


def status() -> dict[str, Any]:
    return {
        "working": {
            "goal": _working.goal,
            "status": _working.status,
            "actions": len(_working.recent_actions),
        },
        "session": {
            "apps": list(_session.apps_used),
            "chat_turns": len(_session.conversation),
            "started_at": _session.started_at,
        },
        "persistent": {
            "facts": len(_persistent.list_facts(100)),
            "last_write": _persistent.last_write,
            "last_denied": _persistent.last_denied,
        },
    }
