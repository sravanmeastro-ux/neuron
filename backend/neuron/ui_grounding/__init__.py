"""NEURON UI Grounding Engine — never click without visual verification (compose-only)."""

from __future__ import annotations

from neuron.ui_grounding.bridge import maybe_handle_ui_grounding
from neuron.ui_grounding.detect import looks_like_ui_grounding
from neuron.ui_grounding.gate import grounded_click
from neuron.ui_grounding.orchestrator import dispatch, orchestrate
from neuron.ui_grounding.pipeline import run_pipeline
from neuron.ui_grounding.types import UGCapability


def tool_ui_ground_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(UGCapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="ui_grounding")


def tool_ui_ground_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    # Direct grounded click tool
    if args.get("name") or args.get("text") or args.get("query") or args.get("target") or (
        args.get("x") is not None and args.get("y") is not None
    ):
        if str(args.get("capability") or "") in ("", "click", "pipeline"):
            return grounded_click(args)
    text = str(args.get("request") or args.get("goal") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="ui_grounding") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request, target, or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)))
    return ok(say, state=meta, method="ui_grounding") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_ui_grounding",
    "looks_like_ui_grounding",
    "orchestrate",
    "dispatch",
    "grounded_click",
    "run_pipeline",
    "UGCapability",
    "tool_ui_ground_status",
    "tool_ui_ground_run",
]
