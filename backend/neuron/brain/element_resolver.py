"""Element Resolver — Agent click("Search") → actual target → mouse/action.

Cascade (reliable structured sources first):
  browser DOM / a11y
  → Windows UI Automation
  → local OCR (RapidOCR boxes)
  → vision model (computer_use)
  → raw coordinates (only if explicitly provided)

Does not replace vision_agent or UIA/browser tools — composes them.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from neuron.windows.result import ToolResult, fail, ok


@dataclass
class ResolvedTarget:
    """Concrete clickable target resolved from a semantic query."""

    query: str
    name: str = ""
    x: int = 0
    y: int = 0
    source: str = ""  # dom | uia | ocr | vision | coords
    confidence: float = 0.0
    element: dict[str, Any] = field(default_factory=dict)
    action_hint: str = ""  # playwright | invoke | uia-click | mouse | vision
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_coords(self) -> bool:
        return bool(self.x or self.y)


def _log(msg: str) -> None:
    print(f"[resolver] {msg}", flush=True)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _query_from_args(args: dict | None) -> str:
    args = args or {}
    return (
        args.get("name")
        or args.get("text")
        or args.get("query")
        or args.get("element")
        or args.get("target")
        or ""
    ).strip()


def _browser_context() -> bool:
    """True when the controlled browser / a browser window is the likely surface."""
    try:
        from neuron.brain.computer_state import get_last_state, capture
        cs = get_last_state() or capture(deep=False, remember=False)
        app = (cs.looking_at() or "").lower()
        title = (cs.focused_window_title or "").lower()
        if cs.browser_url:
            return True
        if cs.scene in ("youtube", "browser"):
            return True
        if any(b in app or b in title for b in ("chrome", "edge", "firefox", "opera", "brave", "youtube")):
            return True
    except Exception:
        pass
    try:
        import browser
        url = browser.current_url() or ""
        if url:
            return True
    except Exception:
        pass
    return False


# ------------------------------------------------------------------ resolve cascade


def resolve_dom(query: str, *, role: str = "", index: int | None = None) -> ResolvedTarget | None:
    """Browser DOM / a11y resolve (no click yet)."""
    if not query and index is None:
        return None
    try:
        from neuron.browser import agent as br
        if index is not None:
            # Index clicks are acted via browser_click; mark as resolved-by-index
            return ResolvedTarget(
                query=query or f"#{index}",
                name=query or f"index {index}",
                source="dom",
                confidence=0.85,
                element={"index": index, "name": query},
                action_hint="playwright",
                note="dom-index",
            )
        found = br.browser_find_element({"name": query, "role": role or ""})
        if not found.success:
            return None
        el = (found.state or {}).get("best") or (found.state or {}).get("element") or {}
        if not el and (found.state or {}).get("candidates"):
            el = (found.state or {}).get("candidates")[0] or {}
        name = (el.get("name") or el.get("text") or query).strip()
        score = float(el.get("score") or 70)
        return ResolvedTarget(
            query=query,
            name=name,
            x=int(el.get("center_x") or el.get("x") or 0),
            y=int(el.get("center_y") or el.get("y") or 0),
            source="dom",
            confidence=min(0.99, 0.5 + score / 200.0),
            element=dict(el),
            action_hint="playwright",
            note="dom-find",
        )
    except Exception as exc:
        _log(f"DOM resolve skipped: {exc}")
        return None


def resolve_uia(query: str, *, control_type: str = "") -> ResolvedTarget | None:
    """Windows UI Automation resolve."""
    if not query:
        return None
    try:
        from neuron.uia import actions as uia_actions
        found = uia_actions.find_ui_element({
            "name": query,
            "control_type": control_type or "",
            "allow_ocr_fallback": False,
            "prefer_clickable": True,
        })
        if not found.success:
            return None
        el = (found.state or {}).get("element") or {}
        name = (el.get("name") or query).strip()
        return ResolvedTarget(
            query=query,
            name=name,
            x=int(el.get("center_x") or 0),
            y=int(el.get("center_y") or 0),
            source="uia",
            confidence=0.9,
            element=dict(el),
            action_hint="invoke",
            note="uia-find",
        )
    except Exception as exc:
        _log(f"UIA resolve skipped: {exc}")
        return None


def resolve_ocr(query: str) -> ResolvedTarget | None:
    """Local RapidOCR — match text boxes and return screen coordinates."""
    if not query:
        return None
    q = _norm(query)
    try:
        import screen_capture as sc
        from neuron.perception.ocr import detect_text_regions
        from neuron.perception.capture_ops import prepare_image, _out_dir

        fg = sc.capture_foreground(padding=0)
        if not fg or not fg.get("image"):
            # Full focused monitor fallback
            from neuron.perception import capture_ops
            cap = capture_ops.get_active_window_screenshot({})
            if not cap.success:
                cap = capture_ops.capture_screen({})
            if not cap.success:
                return None
            path = (cap.state or {}).get("path") or ""
            ox = int((cap.state or {}).get("left") or 0)
            oy = int((cap.state or {}).get("top") or 0)
        else:
            img = prepare_image(fg["image"], max_width=1600)
            path = str(_out_dir() / "resolver_ocr.png")
            img.save(path)
            ox = int(fg.get("left") or 0)
            oy = int(fg.get("top") or 0)

        regions = detect_text_regions({"path": path})
        if not regions.success:
            return None
        best = None
        best_score = -1.0
        for r in (regions.state or {}).get("regions") or []:
            text = _norm(r.get("text") or "")
            if not text:
                continue
            score = 0.0
            if text == q:
                score = 100.0
            elif text.startswith(q) or q.startswith(text):
                score = 80.0
            elif q in text:
                score = 60.0
            else:
                tokens = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 3]
                hits = sum(1 for t in tokens if t in text)
                if hits:
                    score = 20.0 * hits
            conf = float(r.get("confidence") or 0)
            score += conf * 10
            if score > best_score:
                best_score = score
                best = r
        if not best or best_score < 15:
            return None
        # Image-relative centers → screen coords
        cx = ox + int(best.get("center_x") or 0)
        cy = oy + int(best.get("center_y") or 0)
        return ResolvedTarget(
            query=query,
            name=(best.get("text") or query)[:80],
            x=cx,
            y=cy,
            source="ocr",
            confidence=min(0.85, 0.4 + best_score / 200.0),
            element={
                "text": best.get("text"),
                "confidence": best.get("confidence"),
                "box": best.get("box"),
                "image_center": (best.get("center_x"), best.get("center_y")),
                "offset": (ox, oy),
            },
            action_hint="mouse",
            note=f"ocr-score={best_score:.0f}",
        )
    except Exception as exc:
        _log(f"OCR resolve skipped: {exc}")
        return None


def resolve_coords(args: dict | None) -> ResolvedTarget | None:
    """Explicit x,y from the agent/planner — last structured option before vision."""
    args = args or {}
    try:
        x = args.get("x", args.get("cx", args.get("center_x")))
        y = args.get("y", args.get("cy", args.get("center_y")))
        if x is None or y is None:
            return None
        return ResolvedTarget(
            query=_query_from_args(args) or "coords",
            name="coords",
            x=int(x),
            y=int(y),
            source="coords",
            confidence=0.5,
            element={"x": int(x), "y": int(y)},
            action_hint="mouse",
            note="explicit-coords",
        )
    except Exception:
        return None


def resolve(
    query: str = "",
    *,
    args: dict | None = None,
    prefer_browser: bool | None = None,
    allow_dom: bool = True,
    allow_uia: bool = True,
    allow_ocr: bool = True,
    allow_vision: bool = False,  # vision resolves by acting; use click() for full cascade
    control_type: str = "",
) -> ResolvedTarget | None:
    """
    Resolve a semantic label to a concrete target.

    Order: DOM → UIA → OCR → explicit coords.
    Vision is handled in click() because it performs the action itself.
    """
    args = dict(args or {})
    query = (query or _query_from_args(args)).strip()
    index = args.get("index")
    if index is not None and index != "":
        try:
            index = int(index)
        except Exception:
            index = None
    else:
        index = None

    if prefer_browser is None:
        prefer_browser = _browser_context() or index is not None

    tried: list[str] = []

    # 1) DOM first when browser-ish
    if allow_dom and (prefer_browser or index is not None):
        tried.append("dom")
        hit = resolve_dom(query, role=args.get("role") or "", index=index)
        if hit:
            _log(f"resolved via DOM: {hit.name!r}")
            return hit

    # 2) UIA
    if allow_uia and query:
        tried.append("uia")
        hit = resolve_uia(query, control_type=control_type or args.get("control_type") or "")
        if hit:
            _log(f"resolved via UIA: {hit.name!r} @({hit.x},{hit.y})")
            return hit

    # 3) If DOM wasn't preferred earlier, try it once more (Chrome in background)
    if allow_dom and not prefer_browser and query:
        tried.append("dom-late")
        hit = resolve_dom(query, role=args.get("role") or "")
        if hit:
            _log(f"resolved via DOM (late): {hit.name!r}")
            return hit

    # 4) OCR
    if allow_ocr and query:
        tried.append("ocr")
        hit = resolve_ocr(query)
        if hit:
            _log(f"resolved via OCR: {hit.name!r} @({hit.x},{hit.y})")
            return hit

    # 5) Explicit coords
    hit = resolve_coords(args)
    if hit:
        tried.append("coords")
        _log(f"resolved via coords: ({hit.x},{hit.y})")
        return hit

    _log(f"unresolved '{query}' tried={tried}")
    return None


# ------------------------------------------------------------------ act


def act(target: ResolvedTarget, *, args: dict | None = None) -> ToolResult:
    """Perform the click/invoke on an already-resolved target."""
    args = args or {}
    if target.source == "dom" or target.action_hint == "playwright":
        try:
            from neuron.browser import agent as br
            click_args: dict[str, Any] = {}
            if target.element.get("index") is not None:
                click_args["index"] = target.element["index"]
            if target.query or target.name:
                click_args["name"] = target.query or target.name
            if args.get("role"):
                click_args["role"] = args["role"]
            result = br.browser_click(click_args)
            if result.success:
                st = dict(result.state or {})
                st["resolved"] = target.to_dict()
                st["resolver_source"] = "dom"
                return ok(result.message, state=st, method=f"resolver:dom:{result.method}")
            return result
        except Exception as exc:
            return fail(f"DOM click failed: {exc}", state={"resolved": target.to_dict()}, method="resolver:dom")

    if target.source == "uia" or target.action_hint in ("invoke", "uia-click"):
        try:
            from neuron.uia import actions as uia_actions
            el = target.element or {}
            query = target.name or target.query
            ctrl = uia_actions._locate_control(query, el)
            clicked_how = ""
            if ctrl is not None:
                try:
                    inv = ctrl.GetInvokePattern()
                    if inv:
                        inv.Invoke()
                        clicked_how = "invoke"
                except Exception:
                    pass
                if not clicked_how:
                    try:
                        ctrl.Click(simulateMove=False)
                        clicked_how = "uia-click"
                    except Exception:
                        pass
            if not clicked_how and target.has_coords:
                return _mouse_click(ResolvedTarget(
                    query=target.query,
                    name=target.name,
                    x=target.x,
                    y=target.y,
                    source="uia",
                    confidence=target.confidence,
                    element=el,
                    action_hint="mouse",
                    note="uia-bounds-mouse",
                ))
            if not clicked_how:
                return fail(
                    f"Couldn't bind/click UIA control for '{query}'.",
                    state={"resolved": target.to_dict()},
                    method="resolver:uia",
                )
            time.sleep(0.2)
            return ok(
                f"Clicked '{el.get('name') or query}'.",
                state={
                    "resolved": target.to_dict(),
                    "element": el,
                    "method_detail": clicked_how,
                    "resolver_source": "uia",
                    "verified": True,
                },
                method=f"resolver:uia:{clicked_how}",
            )
        except Exception as exc:
            if target.has_coords:
                return _mouse_click(target)
            return fail(f"UIA click failed: {exc}", state={"resolved": target.to_dict()}, method="resolver:uia")

    if target.source in ("ocr", "coords") or target.action_hint == "mouse":
        return _mouse_click(target)

    if target.source == "vision" or target.action_hint == "vision":
        return _vision_act(target.query)

    return fail(
        f"Don't know how to act on source={target.source}",
        state={"resolved": target.to_dict()},
        method="resolver",
    )


def _mouse_click(target: ResolvedTarget) -> ToolResult:
    if not target.has_coords:
        return fail("No coordinates for mouse click.", state={"resolved": target.to_dict()}, method="resolver:mouse")
    try:
        import pyautogui
        pyautogui.click(int(target.x), int(target.y))
        time.sleep(0.15)
        return ok(
            f"Clicked '{target.name or target.query}' at ({target.x},{target.y}) via {target.source}.",
            state={"resolved": target.to_dict(), "verified": True},
            method=f"resolver:{target.source}:mouse",
        )
    except Exception as exc:
        return fail(f"Mouse click failed: {exc}", state={"resolved": target.to_dict()}, method="resolver:mouse")


def _vision_act(query: str) -> ToolResult:
    _log(f"vision fallback for click '{query}'")
    try:
        import vision_agent
        if not vision_agent or not vision_agent.is_enabled():
            return fail(f"Couldn't resolve '{query}' and vision is unavailable.", method="resolver:vision")
        msg = vision_agent.computer_use(f"click {query}")
        return ok(
            msg if isinstance(msg, str) else f"Used vision to click {query}.",
            state={
                "resolved": ResolvedTarget(
                    query=query, name=query, source="vision", confidence=0.55, action_hint="vision"
                ).to_dict(),
                "resolver_source": "vision",
            },
            method="resolver:vision",
        )
    except Exception as exc:
        return fail(f"Vision click failed for '{query}': {exc}", method="resolver:vision")


# ------------------------------------------------------------------ public click API


def click(args: dict | None = None) -> ToolResult:
    """
    Unified click entry used by AgentLoop tools.

      Agent → click("Search") → Element Resolver → DOM/UIA/OCR/Vision → action
    """
    args = dict(args or {})
    query = _query_from_args(args)
    index = args.get("index")
    allow_vision = bool(args.get("allow_vision_fallback", args.get("allow_vision", True)))
    allow_ocr = bool(args.get("allow_ocr", True))
    allow_dom = bool(args.get("allow_dom", True))
    allow_uia = bool(args.get("allow_uia", True))

    if not query and index is None and args.get("x") is None:
        return fail("Need element name, index, or x/y to click.", method="resolver")

    target = resolve(
        query,
        args=args,
        allow_dom=allow_dom,
        allow_uia=allow_uia,
        allow_ocr=allow_ocr,
        control_type=(args.get("control_type") or args.get("type") or args.get("role") or ""),
    )

    if target:
        result = act(target, args=args)
        if result.success:
            return result
        _log(f"act via {target.source} failed: {result.error}; continuing cascade")

    # Vision last resort (acts as resolve+click)
    if allow_vision and query:
        return _vision_act(query)

    err = f"Couldn't resolve click target '{query or index}'."
    if target:
        err += f" Last attempt ({target.source}): {target.note}"
    return fail(
        err,
        state={"query": query, "resolved": target.to_dict() if target else None},
        method="resolver",
    )


def find(args: dict | None = None) -> ToolResult:
    """Resolve only — report source + coords without clicking."""
    args = dict(args or {})
    query = _query_from_args(args)
    if not query and args.get("index") is None:
        return fail("Need element name to find.", method="resolver")
    target = resolve(
        query,
        args=args,
        allow_ocr=bool(args.get("allow_ocr", True)),
        control_type=(args.get("control_type") or "") ,
    )
    if not target:
        return fail(f"Not found: {query}", method="resolver")
    msg = (
        f"Found '{target.name}' via {target.source}"
        + (f" at ({target.x},{target.y})" if target.has_coords else "")
        + f" conf={target.confidence:.2f}"
    )
    return ok(msg, state={"resolved": target.to_dict(), "element": target.element}, method=f"resolver:{target.source}")
