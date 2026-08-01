"""DesktopWorldModel — V4 authoritative desktop state owner.

Update flow:
  raw observation (observe_world / ComputerState / …)
      → adapters.normalize
      → DesktopWorldModel.update(...)
      → new DesktopState snapshot (previous retained)
      → AgentLoop / planner / verifier consume via queries / to_observe_dict

Do not mutate DesktopState fields in place from call sites.
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.v4.world import adapters
from neuron.v4.world.models import (
    DesktopState,
    InteractionRecord,
    KnowledgeLevel,
    MonitorState,
    UIElementState,
    WindowState,
)

_DEFAULT_HISTORY = 40
_SENSITIVE_KEYS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "ssn", "credit", "cvv", "private_key",
)


class DesktopWorldModel:
    """Single owner of current + previous DesktopState snapshots."""

    def __init__(self, *, max_interactions: int = _DEFAULT_HISTORY):
        self._current = DesktopState(timestamp=time.time())
        self._previous: DesktopState | None = None
        self._max_interactions = max(4, int(max_interactions))
        self._task_id: str = ""

    # ------------------------------------------------------------------ snapshots

    @property
    def current(self) -> DesktopState:
        return self._current

    @property
    def previous(self) -> DesktopState | None:
        return self._previous

    def snapshot(self) -> DesktopState:
        """Deep copy of current state (safe to retain across actions)."""
        return self._current.clone()

    def snapshot_previous(self) -> DesktopState | None:
        return self._previous.clone() if self._previous else None

    def set_task_id(self, task_id: str) -> None:
        self._task_id = (task_id or "").strip()

    # ------------------------------------------------------------------ updates

    def update(self, state: DesktopState, *, push_previous: bool = True) -> DesktopState:
        """Replace current snapshot. Returns the new current state."""
        if state is None:
            raise ValueError("DesktopWorldModel.update requires a DesktopState")
        # Preserve interaction history across observation refreshes
        if push_previous:
            self._previous = self._current.clone()
            # Carry history forward unless the new state already has a longer one
            if not state.recent_interactions and self._current.recent_interactions:
                state.recent_interactions = list(self._current.recent_interactions)
        state.ensure_fingerprint()
        if not state.timestamp:
            state.timestamp = time.time()
        self._current = state
        return self._current

    def update_from_observe_dict(
        self,
        raw: dict[str, Any] | None,
        *,
        push_previous: bool = True,
    ) -> DesktopState:
        state = adapters.from_observe_dict(raw, previous=self._current)
        return self.update(state, push_previous=push_previous)

    def update_from_computer_state(self, cs: Any, *, push_previous: bool = True) -> DesktopState:
        state = adapters.from_computer_state(cs, previous=self._current)
        return self.update(state, push_previous=push_previous)

    def update_from_world_state(self, ws: Any, *, push_previous: bool = True) -> DesktopState:
        state = adapters.from_world_state(ws, previous=self._current)
        return self.update(state, push_previous=push_previous)

    def update_from_v3_observation(self, obs: Any, *, push_previous: bool = True) -> DesktopState:
        state = adapters.from_v3_observation(obs, previous=self._current)
        return self.update(state, push_previous=push_previous)

    def update_from_screen_context(self, sc: Any, *, push_previous: bool = True) -> DesktopState:
        state = adapters.from_screen_context(sc, previous=self._current)
        return self.update(state, push_previous=push_previous)

    def update_from_perception(
        self,
        result: Any,
        *,
        push_previous: bool = True,
    ) -> DesktopState:
        """Apply a V4.2 PerceptionResult.desktop snapshot."""
        desktop = getattr(result, "desktop", None)
        if desktop is None:
            raise ValueError("update_from_perception requires PerceptionResult with desktop")
        return self.update(desktop.clone() if hasattr(desktop, "clone") else desktop, push_previous=push_previous)

    def reset(self) -> None:
        self._previous = None
        self._current = DesktopState(timestamp=time.time())
        self._task_id = ""

    # ------------------------------------------------------------------ interactions

    def record_interaction(
        self,
        action: str,
        *,
        target: str = "",
        result: str = "",
        ok: bool | None = None,
        application: str = "",
        window: str = "",
        monitor_id: int | None = None,
        task_id: str = "",
        args: dict[str, Any] | None = None,
    ) -> InteractionRecord:
        fw = self._current.foreground_window
        app = application or (
            self._current.foreground_application.name if self._current.foreground_application else ""
        ) or (fw.application if fw else "")
        win = window or (fw.title if fw else "")
        mon = monitor_id if monitor_id is not None else self._current.active_monitor_id
        tgt = (target or "").strip()
        if not tgt and args:
            for k in ("name", "app", "query", "url", "title", "text"):
                if args.get(k) and not _is_sensitive_key(k):
                    val = str(args.get(k))
                    if not _looks_secret(val):
                        tgt = val[:80]
                        break
        rec = InteractionRecord(
            timestamp=time.time(),
            action=(action or "").strip()[:80],
            target=tgt[:120],
            application=str(app)[:80],
            window=str(win)[:120],
            monitor_id=mon,
            result=_scrub_result(result)[:200],
            ok=ok,
            task_id=(task_id or self._task_id)[:64],
        )
        hist = list(self._current.recent_interactions)
        hist.append(rec)
        if len(hist) > self._max_interactions:
            hist = hist[-self._max_interactions :]
        self._current.recent_interactions = hist
        return rec

    # ------------------------------------------------------------------ queries

    def get_foreground_window(self) -> WindowState | None:
        return self._current.foreground_window

    def get_active_application(self) -> str:
        if self._current.foreground_application and self._current.foreground_application.name:
            return self._current.foreground_application.name
        fw = self._current.foreground_window
        return (fw.application if fw else "") or ""

    def get_window_by_application(self, name: str) -> WindowState | None:
        wins = self.get_windows_by_application(name)
        # Prefer focused, then highest confidence
        if not wins:
            return None
        focused = [w for w in wins if w.focused]
        pool = focused or wins
        return max(pool, key=lambda w: (w.confidence, 1 if w.hwnd else 0))

    def get_windows_by_application(self, name: str) -> list[WindowState]:
        needle = (name or "").strip().lower()
        if not needle:
            return []
        scored: list[tuple[int, WindowState]] = []
        for w in self._current.windows:
            app = (w.application or "").lower()
            title = (w.title or "").lower()
            process = (w.process or "").lower()
            score = 0
            if needle == app or needle == process:
                score = 3
            elif needle in app or needle in process:
                score = 2
            elif needle in title:
                # Title-only match is weaker — avoid "Blender" matching a YouTube title
                score = 1
            if score:
                scored.append((score, w))
        if not scored:
            return []
        best = max(s for s, _ in scored)
        # Prefer strong app/process hits; fall back to title only if nothing stronger
        if best >= 2:
            return [w for s, w in scored if s >= 2]
        return [w for s, w in scored]

    def get_monitor_for_window(self, window: WindowState | dict | int | None) -> MonitorState | None:
        if window is None:
            return None
        if isinstance(window, int):
            w = next((x for x in self._current.windows if x.hwnd == window), None)
            if w is None:
                return None
            window = w
        if isinstance(window, dict):
            window = WindowState.from_dict(window)
        if window.monitor_id is not None:
            hit = self.get_monitor_by_id(int(window.monitor_id))
            if hit:
                return hit
        bounds = window.bounds_dict()
        if not bounds:
            return None
        cx = int(bounds["left"]) + int(bounds["width"]) // 2
        cy = int(bounds["top"]) + int(bounds["height"]) // 2
        for m in self._current.monitors:
            if m.contains_point(cx, cy):
                return m
        return None

    def get_monitor_by_id(self, monitor_id: int) -> MonitorState | None:
        for m in self._current.monitors:
            if int(m.id) == int(monitor_id):
                return m
        return None

    def resolve_monitor_reference(
        self,
        ref: Any,
        *,
        relative_to: int | None = None,
        application: str | None = None,
    ) -> MonitorState | None:
        """
        Resolve NL/numeric monitor refs against *this* world snapshot.

        Preserves V4.0 semantics: when relative_to is provided (e.g. window's
        current monitor), "other" uses that — not live foreground.
        """
        text = str(ref or "").strip().lower()
        # "the monitor with Chrome" / "screen with Discord"
        if application or re.search(r"\b(?:with|showing|displaying)\s+[\w .+-]+", text):
            app = application or ""
            if not app:
                m = re.search(
                    r"\b(?:with|showing|displaying)\s+(?:the\s+)?([\w .+-]+?)(?:\s+(?:on it|open))?\s*$",
                    text,
                )
                if m:
                    app = m.group(1).strip()
                else:
                    m = re.search(r"\bmonitor with\s+([\w .+-]+)", text)
                    if m:
                        app = m.group(1).strip()
            if app:
                w = self.get_window_by_application(app)
                mon = self.get_monitor_for_window(w) if w else None
                if mon:
                    return mon
                if w and w.monitor_id is not None:
                    return self.get_monitor_by_id(int(w.monitor_id))

        mons_dicts = [m.to_dict() for m in self._current.monitors]
        if not mons_dicts:
            return None
        # Prefer in-model resolve; fall back to windows.monitors with our geometry
        try:
            from neuron.windows import monitors as mon_mod
            hit = mon_mod.resolve_monitor_ref(
                ref,
                relative_to=relative_to,
                monitors=mons_dicts,
            )
            if hit:
                return MonitorState.from_dict(hit)
        except Exception:
            pass
        return self._resolve_monitor_local(ref, relative_to=relative_to)

    def get_visible_elements(
        self,
        *,
        role: str | None = None,
        limit: int = 40,
    ) -> list[UIElementState]:
        els = list(self._current.visible_elements)
        if role:
            r = role.strip().lower()
            els = [e for e in els if (e.role or "").lower() == r]
        return els[:limit]

    def get_recent_interactions(self, *, limit: int = 20) -> list[InteractionRecord]:
        return list(self._current.recent_interactions)[-limit:]

    def diff_snapshots(
        self,
        before: DesktopState | None = None,
        after: DesktopState | None = None,
    ) -> dict[str, Any]:
        """Compare two snapshots (defaults: previous vs current)."""
        a = before if before is not None else self._previous
        b = after if after is not None else self._current
        if a is None:
            return {
                "changed": True,
                "reason": "no_previous_state",
                "diffs": ["first_observation"],
                "before_fp": "",
                "after_fp": b.ensure_fingerprint() if b else "",
            }
        if b is None:
            return {
                "changed": False,
                "reason": "no_after_state",
                "diffs": [],
                "before_fp": a.ensure_fingerprint(),
                "after_fp": "",
            }
        diffs: list[str] = []
        aw = a.foreground_window
        bw = b.foreground_window
        if (aw.title if aw else "") != (bw.title if bw else ""):
            diffs.append(
                f"focus_title: {(aw.title if aw else '')[:40]!r} -> {(bw.title if bw else '')[:40]!r}"
            )
        if int(aw.hwnd if aw else 0) != int(bw.hwnd if bw else 0):
            diffs.append(f"hwnd: {aw.hwnd if aw else 0} -> {bw.hwnd if bw else 0}")
        aa = a.foreground_application.name if a.foreground_application else ""
        ba = b.foreground_application.name if b.foreground_application else ""
        if aa.lower() != ba.lower():
            diffs.append(f"app: {aa} -> {ba}")
        if a.active_monitor_id != b.active_monitor_id:
            diffs.append(f"monitor: {a.active_monitor_id} -> {b.active_monitor_id}")
        au = a.browser.url if a.browser else ""
        bu = b.browser.url if b.browser else ""
        if au != bu:
            diffs.append(f"url: {au[:60]} -> {bu[:60]}")
        prev_names = {(e.name or "").strip().lower() for e in a.visible_elements if e.name}
        cur_names = {(e.name or "").strip().lower() for e in b.visible_elements if e.name}
        if prev_names or cur_names:
            added = sorted(cur_names - prev_names)[:8]
            removed = sorted(prev_names - cur_names)[:8]
            if added:
                diffs.append("elements_added: " + ", ".join(added))
            if removed:
                diffs.append("elements_removed: " + ", ".join(removed))
        afp = a.ensure_fingerprint()
        bfp = b.ensure_fingerprint()
        if afp != bfp and not diffs:
            diffs.append("fingerprint_changed")
        return {
            "changed": bool(diffs),
            "reason": diffs[0] if diffs else "unchanged",
            "diffs": diffs,
            "before_fp": afp,
            "after_fp": bfp,
        }

    def to_observe_dict(self) -> dict[str, Any]:
        return self._current.to_observe_dict()

    def sync_to_v3_world_state(self, ws: Any) -> None:
        adapters.sync_world_state_from_desktop(ws, self._current)

    # ------------------------------------------------------------------ helpers

    def _resolve_monitor_local(
        self,
        ref: Any,
        *,
        relative_to: int | None = None,
    ) -> MonitorState | None:
        mons = list(self._current.monitors)
        if not mons:
            return None
        if isinstance(ref, (int, float)) and not isinstance(ref, bool):
            return self.get_monitor_by_id(int(ref))
        text = str(ref or "").strip().lower()
        if not text:
            return None
        if re.fullmatch(r"\d{1,2}", text):
            return self.get_monitor_by_id(int(text))
        if re.search(r"\b(main|primary)\b", text):
            return next((m for m in mons if m.primary or "main" in m.roles), mons[0])
        if re.search(r"\bleft\b", text):
            return min(mons, key=lambda m: m.center_x)
        if re.search(r"\bright\b", text):
            return max(mons, key=lambda m: m.center_x)
        if re.search(r"\b(other|another|secondary|opposite)\b", text):
            cur = relative_to if relative_to is not None else self._current.active_monitor_id
            if cur is not None:
                for m in mons:
                    if int(m.id) != int(cur):
                        return m
            for m in mons:
                if not m.primary:
                    return m
            return mons[-1] if len(mons) > 1 else mons[0]
        return None


# Process-wide model used by AgentLoop (reset in tests via reset_world_model)
_WORLD: DesktopWorldModel | None = None


def get_world_model() -> DesktopWorldModel:
    global _WORLD
    if _WORLD is None:
        _WORLD = DesktopWorldModel()
    return _WORLD


def reset_world_model() -> DesktopWorldModel:
    global _WORLD
    _WORLD = DesktopWorldModel()
    return _WORLD


def _is_sensitive_key(key: str) -> bool:
    k = (key or "").lower()
    return any(s in k for s in _SENSITIVE_KEYS)


def _looks_secret(s: str) -> bool:
    low = (s or "").lower()
    if any(x in low for x in ("password=", "bearer ", "api_key=", "secret=")):
        return True
    digits = "".join(c for c in s if c.isdigit())
    return len(digits) >= 13 and len(digits) <= 19 and len(s) <= 24


def _scrub_result(result: str) -> str:
    s = result or ""
    if _looks_secret(s):
        return "[redacted]"
    return s
