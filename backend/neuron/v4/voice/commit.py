"""Route commit — prevents legacy fallback after hierarchical mutation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteCommitState:
    request_id: str
    committed: bool = False
    first_mutation_tool: str = ""
    committed_at: float = 0.0
    mutations: list[str] = field(default_factory=list)


_lock = threading.Lock()
_active: RouteCommitState | None = None


def begin_route(request_id: str) -> RouteCommitState:
    global _active
    with _lock:
        st = RouteCommitState(request_id=request_id)
        _active = st
        return st


def mark_mutation(tool: str, *, request_id: str = "") -> None:
    global _active
    with _lock:
        if _active is None:
            return
        if request_id and _active.request_id != request_id:
            return
        if not _active.committed:
            _active.committed = True
            _active.first_mutation_tool = tool
            _active.committed_at = time.time()
        _active.mutations.append(tool)


def is_committed(request_id: str = "") -> bool:
    with _lock:
        if _active is None:
            return False
        if request_id and _active.request_id != request_id:
            return False
        return _active.committed


def clear_route(request_id: str = "") -> None:
    global _active
    with _lock:
        if _active is None:
            return
        if request_id and _active.request_id != request_id:
            return
        _active = None


def snapshot() -> dict[str, Any] | None:
    with _lock:
        if _active is None:
            return None
        return {
            "request_id": _active.request_id,
            "committed": _active.committed,
            "first_mutation_tool": _active.first_mutation_tool,
            "n_mutations": len(_active.mutations),
        }


def may_fallback_to_legacy(request_id: str = "") -> bool:
    """Safe fallback only before first external mutation."""
    return not is_committed(request_id)


__all__ = [
    "RouteCommitState",
    "begin_route",
    "mark_mutation",
    "is_committed",
    "clear_route",
    "snapshot",
    "may_fallback_to_legacy",
]
