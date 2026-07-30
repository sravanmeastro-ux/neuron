"""Phase 3 UI actions: find, click, text, bounds — UIA first, OCR/vision last."""

from __future__ import annotations

import time
from typing import Any

from neuron.uia import inspect as ui_inspect
from neuron.uia.rank import rank_candidates
from neuron.uia.types import ElementInfo
from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[uia] {msg}", flush=True)


def _query(args: dict) -> str:
    return (
        args.get("name")
        or args.get("text")
        or args.get("query")
        or args.get("element")
        or ""
    ).strip()


def get_ui_tree(args: dict | None = None) -> ToolResult:
    args = args or {}
    depth = int(args.get("depth") or 5)
    limit = int(args.get("limit") or 60)
    try:
        win, elements = ui_inspect.walk_elements(
            max_depth=depth,
            max_elements=limit,
            interesting_only=bool(args.get("interesting_only", True)),
        )
        if not win and not elements:
            return fail("No foreground window / empty UI tree.", method="uia")
        tree = ui_inspect.format_tree(win, elements, limit=limit)
        return ok(
            tree,
            state={
                "window": win.to_dict() if win else {},
                "elements": [e.to_dict() for e in elements[:limit]],
                "count": len(elements),
            },
            method="uia",
        )
    except Exception as exc:
        return fail(f"UIA tree failed: {exc}", method="uia")


def get_active_window_elements(args: dict | None = None) -> ToolResult:
    args = args or {}
    limit = int(args.get("limit") or 80)
    try:
        win, elements = ui_inspect.walk_elements(
            max_depth=int(args.get("depth") or 6),
            max_elements=limit,
            interesting_only=True,
        )
        if not win:
            return fail("No active window.", method="uia")
        # Compact spoken summary
        roles: dict[str, int] = {}
        for e in elements:
            roles[e.role] = roles.get(e.role, 0) + 1
        summary = f"Active '{win.name[:60]}' — {len(elements)} elements"
        if roles:
            top = sorted(roles.items(), key=lambda x: -x[1])[:6]
            summary += " (" + ", ".join(f"{n} {r}" for r, n in top) + ")"
        return ok(
            summary,
            state={
                "window": win.to_dict(),
                "elements": [e.to_dict() for e in elements],
                "role_counts": roles,
            },
            method="uia",
        )
    except Exception as exc:
        return fail(f"Couldn't read active window elements: {exc}", method="uia")


def find_ui_element(args: dict | None = None) -> ToolResult:
    args = args or {}
    query = _query(args)
    if not query:
        return fail("Need element name/query.")
    control_type = (args.get("control_type") or args.get("type") or args.get("role") or "").strip() or None
    try:
        win, elements = ui_inspect.walk_elements(
            max_depth=int(args.get("depth") or 8),
            max_elements=int(args.get("scan_limit") or 200),
            interesting_only=False,
        )
        ranked = rank_candidates(
            elements,
            query,
            control_type=control_type,
            prefer_clickable=bool(args.get("prefer_clickable", True)),
            limit=int(args.get("top") or 8),
        )
        if not ranked:
            # Optional OCR fallback for discovery only
            if bool(args.get("allow_ocr_fallback", True)):
                ocr_hit = _ocr_fallback_hint(query)
                if ocr_hit:
                    return fail(
                        f"UIA found no '{query}'. OCR saw nearby text: {ocr_hit}. "
                        f"Try computer_use or refine the name.",
                        state={"window": win.to_dict() if win else {}, "candidates": [], "ocr_hint": ocr_hit},
                        method="uia+ocr",
                    )
            return fail(
                f"Not found: {query}",
                state={"window": win.to_dict() if win else {}, "candidates": []},
                method="uia",
            )

        best = ranked[0]
        alts = [
            {"name": c.name, "type": c.control_type, "score": c.score, "bounds": c.bounds_dict()}
            for c in ranked[:5]
        ]
        msg = (
            f"Found '{best.name}' ({best.control_type}) "
            f"at ({best.center_x},{best.center_y}) score={best.score:.0f}"
        )
        if len(ranked) > 1:
            msg += f" [{len(ranked)} candidates]"
        return ok(
            msg,
            state={
                "window": win.to_dict() if win else {},
                "element": best.to_dict(),
                "candidates": alts,
                "query": query,
            },
            method="uia",
        )
    except Exception as exc:
        return fail(f"find_ui_element failed: {exc}", method="uia")


def click_ui_element(args: dict | None = None) -> ToolResult:
    """Click by semantic name via Element Resolver (DOM → UIA → OCR → Vision)."""
    from neuron.brain.element_resolver import click as resolver_click
    return resolver_click(args or {})


def get_element_text(args: dict | None = None) -> ToolResult:
    args = args or {}
    query = _query(args)
    if not query:
        # Foreground window name / selected text-ish
        try:
            win, elements = ui_inspect.walk_elements(max_depth=3, max_elements=40, interesting_only=True)
            edits = [e for e in elements if e.control_type in ("EditControl", "DocumentControl", "TextControl") and (e.value or e.name)]
            if edits:
                e = edits[0]
                text = e.value or e.name
                return ok(text, state={"element": e.to_dict(), "text": text}, method="uia")
            if win:
                return ok(win.name, state={"element": win.to_dict(), "text": win.name}, method="uia")
            return fail("No text element in active window.")
        except Exception as exc:
            return fail(str(exc))

    found = find_ui_element({**args, "name": query, "prefer_clickable": False})
    if not found.success:
        return found
    el = (found.state or {}).get("element") or {}
    text = (el.get("value") or el.get("name") or el.get("help_text") or "").strip()
    if not text:
        return fail(f"Element '{query}' has no text.", state=found.state, method="uia")
    return ok(text, state={"element": el, "text": text}, method="uia")


def get_element_bounds(args: dict | None = None) -> ToolResult:
    args = args or {}
    query = _query(args)
    if not query:
        return fail("Need element name.")
    found = find_ui_element({**args, "name": query})
    if not found.success:
        return found
    el = (found.state or {}).get("element") or {}
    bounds = {
        "left": el.get("left"),
        "top": el.get("top"),
        "right": el.get("right"),
        "bottom": el.get("bottom"),
        "width": el.get("width"),
        "height": el.get("height"),
        "center_x": el.get("center_x"),
        "center_y": el.get("center_y"),
    }
    msg = (
        f"'{el.get('name')}' bounds "
        f"({bounds['left']},{bounds['top']})-({bounds['right']},{bounds['bottom']}) "
        f"center=({bounds['center_x']},{bounds['center_y']})"
    )
    return ok(msg, state={"element": el, "bounds": bounds}, method="uia")


def _locate_control(query: str, el: dict):
    """Re-acquire a live UIA control matching the ranked element."""
    from neuron.windows.com import com_uia
    import uiautomation as auto

    name = (el.get("name") or query or "").strip()
    aid = (el.get("automation_id") or "").strip()
    ctype = (el.get("control_type") or "").strip()
    cx = int(el.get("center_x") or 0)
    cy = int(el.get("center_y") or 0)

    with com_uia():
        fg = auto.GetForegroundControl()
        if not fg:
            return None
        # AutomationId is strongest
        if aid:
            try:
                c = fg.Control(AutomationId=aid, searchDepth=12)
                if c and c.Exists(0, 0):
                    return c
            except Exception:
                pass
        if name:
            try:
                kwargs = {"Name": name, "searchDepth": 12}
                c = fg.Control(**kwargs)
                if c and c.Exists(0, 0):
                    return c
            except Exception:
                pass

        # Walk + match name/type/near center
        best = None
        best_dist = 1e18

        def walk(ctrl, d=0):
            nonlocal best, best_dist
            if d > 10:
                return
            try:
                children = ctrl.GetChildren()
            except Exception:
                return
            for child in children[:60]:
                try:
                    n = (child.Name or "").strip()
                    ct = (child.ControlTypeName or "").strip()
                    if name and n.lower() != name.lower() and name.lower() not in n.lower():
                        walk(child, d + 1)
                        continue
                    if ctype and ct and ct != ctype and name.lower() != n.lower():
                        walk(child, d + 1)
                        continue
                    r = child.BoundingRectangle
                    dx = (r.xcenter() - cx) if cx else 0
                    dy = (r.ycenter() - cy) if cy else 0
                    dist = dx * dx + dy * dy
                    if dist < best_dist:
                        best_dist = dist
                        best = child
                    walk(child, d + 1)
                except Exception:
                    continue

        walk(fg)
        return best


def _ocr_fallback_hint(query: str) -> str:
    try:
        from neuron.perception import ocr
        text = ocr.read_screen() or ""
        q = query.lower()
        for line in text.splitlines():
            if q in line.lower():
                return line.strip()[:80]
        return text[:120] if text and "UIA" not in text[:20] else ""
    except Exception as exc:
        _log(f"ocr fallback skipped: {exc}")
        return ""


def _vision_click_fallback(query: str, prior: ToolResult) -> ToolResult:
    """Last resort: vision computer_use — only when UIA cannot expose the element."""
    _log(f"vision fallback for click '{query}'")
    try:
        import vision_agent
        if not vision_agent or not vision_agent.is_enabled():
            return fail(
                prior.error or f"Couldn't find UI element '{query}'.",
                state=prior.state,
                method="uia",
            )
        msg = vision_agent.computer_use(f"click {query}")
        return ok(
            msg if isinstance(msg, str) else f"Used vision to click {query}.",
            state={"prior": prior.to_dict(), "fallback": "computer_use"},
            method="vision-fallback",
        )
    except Exception as exc:
        return fail(
            f"Couldn't find UI element '{query}' (vision fallback failed: {exc}).",
            state=prior.state,
            method="uia",
        )
