"""Bounded condition-based wait for verification effects."""

from __future__ import annotations

import time
from typing import Any, Callable

from neuron.v4.types import VerificationOutcome
from neuron.v4.verify.types import VerificationExpectation, VerificationReport


def interrupted() -> bool:
    try:
        from neuron.speech import interrupt as interrupt_mod
        return bool(interrupt_mod.interrupted())
    except Exception:
        return False


def wait_until(
    predicate: Callable[[], tuple[VerificationOutcome, float, Any, str, str]],
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.15,
    cancel_check: Callable[[], bool] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> tuple[VerificationOutcome, float, Any, str, str, bool, float]:
    """
    Poll predicate until SUCCESS/FAILURE or timeout.
    UNCERTAIN continues polling until timeout → final UNCERTAIN.
    Returns (status, conf, evidence, reason, method, cancelled, elapsed_ms).
    """
    t0 = time.perf_counter()
    cancel_check = cancel_check or interrupted
    last = (VerificationOutcome.UNCERTAIN, 0.0, None, "not started", "WAIT_POLL")
    timeout_s = max(0.05, float(timeout_s))
    poll_s = max(0.05, float(poll_s))

    while True:
        if cancel_check():
            status, conf, ev, reason, method = last
            return status, conf, ev, "cancelled", method, True, (time.perf_counter() - t0) * 1000
        if on_poll:
            try:
                on_poll()
            except Exception:
                pass
        last = predicate()
        status = last[0]
        if status is VerificationOutcome.SUCCESS or status is VerificationOutcome.FAILURE:
            return (*last, False, (time.perf_counter() - t0) * 1000)
        elapsed = time.perf_counter() - t0
        if elapsed >= timeout_s:
            return (*last, False, elapsed * 1000)
        # Remaining sleep bounded
        time.sleep(min(poll_s, max(0.0, timeout_s - elapsed)))


__all__ = ["wait_until", "interrupted"]
