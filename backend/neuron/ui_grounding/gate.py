"""Click gate — all UI clicks must pass visual grounding."""

from __future__ import annotations

from typing import Any

from neuron.ui_grounding.pipeline import run_pipeline
from neuron.windows.result import fail, ok


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("ui_grounding", True))
    except Exception:
        return True


def grounded_click(args: dict | None = None) -> Any:
    """
    Replacement for tool_registry `click`.
    Never executes a mouse click without visual grounding.
    """
    args = dict(args or {})
    if not _enabled():
        # Soft fallback to resolver when feature disabled
        if args.get("name") or args.get("text") or args.get("query"):
            from neuron.tools import uia_tools
            return uia_tools.click_element(args)
        return fail("UI grounding disabled and no semantic target — refusing coord click.")

    target = str(args.get("name") or args.get("text") or args.get("query") or args.get("target") or "").strip()
    app = args.get("app") or args.get("application")
    x = args.get("x")
    y = args.get("y")
    dry = bool(args.get("dry_run", False))
    min_c = float(args.get("min_confidence") or 0.35)

    if not target and x is None:
        return fail("Grounded click needs name/text/query or x,y to verify against detected UI.")

    # Coord-only: still require nearby element match
    result = run_pipeline(
        f"click:{target or f'@{x},{y}'}",
        target=target,  # keep empty for pure coordinate grounding via nearby element
        app=str(app) if app else None,
        min_confidence=min_c,
        max_retries=int(args.get("retries") or 3),
        allow_scroll=bool(args.get("scroll", True)),
        expect=str(args.get("expect") or ""),
        dry_run=dry,
        x=int(x) if x is not None else None,
        y=int(y) if y is not None else None,
        hint_bbox=args.get("bbox"),
        monitor_id=args.get("monitor"),
    )
    state = result.to_dict()
    if not result.grounded:
        return fail(result.say or result.error or "Ungrounded click refused.", state=state, method="ui_grounding")
    if dry:
        return ok(result.say, state=state, method="ui_grounding")
    if result.acted:
        return ok(result.say, state=state, method="ui_grounding")
    return fail(result.say or "Grounded click failed.", state=state, method="ui_grounding")


def require_grounding_for_xy(x: int, y: int, *, dry_run: bool = False) -> Any:
    return grounded_click({"x": x, "y": y, "dry_run": dry_run})
