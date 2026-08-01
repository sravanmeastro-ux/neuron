"""In-process message bus — agents communicate via request/reply + history."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable

from neuron.agents.types import AgentMessage, AgentResult

Handler = Callable[[AgentMessage], AgentResult]


class MessageBus:
    """Thread-safe in-proc pub/sub + request/reply for specialized agents."""

    def __init__(self, *, history_limit: int = 200) -> None:
        self._handlers: dict[str, Handler] = {}
        self._lock = threading.RLock()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._inbox: dict[str, deque[AgentMessage]] = defaultdict(deque)

    def register(self, role: str, handler: Handler) -> None:
        with self._lock:
            self._handlers[role] = handler

    def unregister(self, role: str) -> None:
        with self._lock:
            self._handlers.pop(role, None)

    def roles(self) -> list[str]:
        with self._lock:
            return sorted(self._handlers.keys())

    def publish(self, message: AgentMessage) -> None:
        with self._lock:
            self._history.append(message.to_dict())
            if message.to_role:
                self._inbox[message.to_role].append(message)
            else:
                for role in list(self._handlers.keys()):
                    if role != message.from_role:
                        self._inbox[role].append(message)

    def request(
        self,
        to_role: str,
        payload: dict[str, Any] | None = None,
        *,
        from_role: str = "coordinator",
        kind: str = "request",
        timeout: float = 60.0,
        correlation_id: str = "",
    ) -> AgentResult:
        msg = AgentMessage(
            kind=kind,
            from_role=from_role,
            to_role=to_role,
            payload=dict(payload or {}),
            correlation_id=correlation_id or "",
        )
        self.publish(msg)
        handler = self._handlers.get(to_role)
        if handler is None:
            return AgentResult(ok=False, role=to_role, error=f"No agent registered: {to_role}")
        t0 = time.perf_counter()
        try:
            result = handler(msg)
        except Exception as exc:
            result = AgentResult(ok=False, role=to_role, error=str(exc), say=str(exc))
        if not isinstance(result, AgentResult):
            result = AgentResult(ok=True, role=to_role, say=str(result), data={"raw": result})
        result.role = result.role or to_role
        # Log reply
        reply = AgentMessage(
            kind="result",
            from_role=to_role,
            to_role=from_role,
            payload=result.to_dict(),
            correlation_id=msg.correlation_id,
        )
        self.publish(reply)
        elapsed = (time.perf_counter() - t0) * 1000
        result.data = dict(result.data or {})
        result.data.setdefault("latency_ms", round(elapsed, 2))
        return result

    def broadcast(
        self,
        payload: dict[str, Any],
        *,
        from_role: str = "coordinator",
        kind: str = "broadcast",
    ) -> list[AgentResult]:
        results = []
        for role in self.roles():
            if role == from_role:
                continue
            results.append(self.request(role, payload, from_role=from_role, kind=kind))
        return results

    def history(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        return items[-limit:]

    def drain(self, role: str) -> list[AgentMessage]:
        with self._lock:
            items = list(self._inbox.get(role) or [])
            self._inbox[role].clear()
        return items


_BUS: MessageBus | None = None


def get_bus() -> MessageBus:
    global _BUS
    if _BUS is None:
        _BUS = MessageBus()
    return _BUS


def reset_bus() -> MessageBus:
    global _BUS
    _BUS = MessageBus()
    return _BUS
