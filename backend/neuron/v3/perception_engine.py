"""V3.4 PerceptionEngine — unified structured observations.

Control hierarchy (stop early when enough structure answers the query):
  1. application / API integration (windows list, YouTube tiles, …)
  2. browser DOM / Playwright
  3. Windows UI Automation / accessibility
  4. OCR (local RapidOCR)
  5. local vision (Ollama VLM) — only when still insufficient
  6. raw coordinates — never invented here; ElementResolver last resort

Does NOT send screenshots to a vision model when DOM/a11y already answers.
Does NOT make vision mandatory for normal desktop control.
Composes existing neuron.perception / browser / uia — does not replace them.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from neuron.v3.perception_types import Observation, PerceivedElement

_ENOUGH_ELEMENTS = 4

_COLOR_WORDS = (
    "blue", "red", "green", "yellow", "orange", "purple", "pink",
    "white", "black", "gray", "grey", "brown",
)

_ROLE_HINTS = re.compile(
    r"\b(video|videos|result|results|button|link|tab|tabs|window|windows|"
    r"menu|menuitem|file|files|search\s*box|text\s*field|textbox|input)\b",
    re.I,
)

_ORDINAL_HINT = re.compile(
    r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous|"
    r"the\s+one)\b",
    re.I,
)


def _log(msg: str) -> None:
    print(f"[perceive-v3] {msg}", flush=True)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _role_from_uia_type(ctype: str, name: str = "") -> str:
    c = (ctype or "").lower()
    n = _norm(name)
    if "button" in c or "splitbutton" in c:
        return "button"
    if "hyperlink" in c or "link" in c:
        return "link"
    if "edit" in c or "document" in c:
        return "text_field"
    if "menuitem" in c or "menu" in c:
        return "menu_item"
    if "tabitem" in c or (c.endswith("tab") and "table" not in c):
        return "tab"
    if "window" in c or "pane" in c:
        return "window"
    if "listitem" in c:
        return "list_item"
    if "checkbox" in c:
        return "checkbox"
    if "search" in n and ("edit" in c or "combo" in c):
        return "text_field"
    return "other"


def _role_from_dom(el: dict[str, Any]) -> str:
    role = _norm(str(el.get("role") or el.get("tag") or ""))
    prefer = _norm(str(el.get("prefer") or ""))
    name = _norm(str(el.get("name") or el.get("text") or ""))
    if prefer == "result" or el.get("is_result"):
        return "browser_result"
    if role in ("button", "submit"):
        return "button"
    if role in ("link", "a"):
        return "link"
    if role in ("textbox", "searchbox", "input", "textarea", "search"):
        return "text_field"
    if role == "tab":
        return "tab"
    if "search" in name and role in ("", "other", "generic"):
        return "text_field"
    return "other"


def _interactive_uia(ctype: str) -> bool:
    c = (ctype or "").lower()
    return any(
        x in c
        for x in (
            "button", "hyperlink", "edit", "menu", "tab", "listitem",
            "checkbox", "radio", "treeitem", "combo", "splitbutton",
        )
    )


def _next_id(prefix: str, n: int) -> str:
    return f"{prefix}:{n}"


class PerceptionEngine:
    """Gather structured UI observations using the control hierarchy."""

    def __init__(
        self,
        *,
        api_provider: Callable[[], list[PerceivedElement]] | None = None,
        dom_provider: Callable[[], list[PerceivedElement]] | None = None,
        uia_provider: Callable[[], list[PerceivedElement]] | None = None,
        ocr_provider: Callable[[], list[PerceivedElement]] | None = None,
        vision_provider: Callable[[str], str] | None = None,
    ) -> None:
        self._api = api_provider
        self._dom = dom_provider
        self._uia = uia_provider
        self._ocr = ocr_provider
        self._vision = vision_provider

    def observe(
        self,
        request: str = "",
        *,
        allow_ocr: bool = True,
        allow_vision: bool = False,
        force_vision: bool = False,
        prefer_roles: set[str] | None = None,
        limit: int = 60,
    ) -> Observation:
        """
        Build a structured Observation.

        Vision runs only when force_vision / allow_vision and structured
        sources are still insufficient for the request.
        """
        obs = Observation()
        app, title, mon, url = self._focus_meta()
        obs.application = app
        obs.window = title
        obs.monitor = mon
        obs.url = url

        req = (request or "").strip()
        need_color = bool(re.search(r"\b(" + "|".join(_COLOR_WORDS) + r")\b", req, re.I))
        need_text_read = bool(
            re.search(r"\b(read|text|written|ocr|label)\b", req, re.I)
        )
        descriptive = bool(
            re.search(
                r"\b(describe|what is on|what's on|look at|see|how many|vision)\b",
                req,
                re.I,
            )
        )

        seen: set[str] = set()

        def _add(els: list[PerceivedElement], source: str) -> None:
            if source not in obs.sources_used:
                obs.sources_used.append(source)
            for el in els:
                key = f"{el.role}|{_norm(el.name)}|{el.source}"
                if key in seen and el.name:
                    continue
                if el.name:
                    seen.add(key)
                el.application = el.application or app
                el.window = el.window or title
                el.monitor = el.monitor or mon
                obs.elements.append(el)

        # 1) Application / API
        try:
            api_els = (self._api or self._collect_api)()
            if api_els:
                _add(api_els, "api")
        except Exception as exc:
            _log(f"api skipped: {exc}")

        # 2) Browser DOM
        try:
            dom_els = (self._dom or self._collect_dom)()
            if dom_els:
                _add(dom_els, "dom")
        except Exception as exc:
            _log(f"dom skipped: {exc}")

        # 3) UIA
        try:
            uia_els = (self._uia or self._collect_uia)()
            if uia_els:
                _add(uia_els, "uia")
        except Exception as exc:
            _log(f"uia skipped: {exc}")

        structured_ok = self._answers_request(obs, req, prefer_roles)

        # 4) OCR — only if sparse, color/text ask, or not enough for request
        if allow_ocr and (not structured_ok or need_color or need_text_read):
            try:
                ocr_els = (self._ocr or self._collect_ocr)()
                if ocr_els:
                    _add(ocr_els, "ocr")
                    structured_ok = (
                        self._answers_request(obs, req, prefer_roles) or structured_ok
                    )
            except Exception as exc:
                _log(f"ocr skipped: {exc}")

        still_sparse = len([e for e in obs.elements if e.name]) < _ENOUGH_ELEMENTS
        need_vision = force_vision or (
            allow_vision
            and (
                descriptive
                or still_sparse
                or (need_color and "ocr" not in obs.sources_used)
            )
            and not structured_ok
        )

        # 5) Local vision — never if structured sources already answer
        if need_vision and not structured_ok:
            try:
                desc = ""
                if self._vision:
                    desc = self._vision(req) or ""
                else:
                    desc = self._collect_vision(req, obs)
                if desc:
                    obs.vision_used = True
                    if "vision" not in obs.sources_used:
                        obs.sources_used.append("vision")
                    obs.note = (obs.note + " " + desc).strip()[:500]
                    for m in re.finditer(r"[\"']([^\"']{2,60})[\"']", desc):
                        obs.elements.append(
                            PerceivedElement(
                                id=_next_id("vision", len(obs.elements) + 1),
                                role="other",
                                name=m.group(1),
                                source="vision",
                                confidence=0.45,
                                interactive=False,
                                clickable=False,
                            )
                        )
            except Exception as exc:
                _log(f"vision skipped: {exc}")

        obs.elements = self._finalize(obs.elements, limit=limit)
        if not obs.sources_used and not obs.elements:
            obs.error = "No perception sources available."
        return obs

    def _answers_request(
        self,
        obs: Observation,
        request: str,
        prefer_roles: set[str] | None,
    ) -> bool:
        named = [e for e in obs.elements if (e.name or "").strip()]
        if prefer_roles:
            role_hits = [e for e in named if e.role in prefer_roles]
            if len(role_hits) >= 1:
                return True
        if not request:
            return len(named) >= _ENOUGH_ELEMENTS

        req = _norm(request)
        if re.search(r"\b(video|videos)\b", req):
            return len(obs.by_role("video")) >= 1
        if re.search(r"\b(result|results)\b", req):
            return (
                len(obs.by_role("browser_result")) >= 1
                or len(obs.by_role("video")) >= 1
                or len(obs.by_role("link")) >= 1
            )
        if re.search(r"\b(search\s*box|search\s*field)\b", req):
            return any(e.role == "text_field" for e in named)
        if re.search(r"\bbutton\b", req):
            return len(obs.by_role("button")) >= 1
        if re.search(r"\bwindow\b", req):
            return len(obs.by_role("window")) >= 1 or bool(obs.window)
        if re.search(r"\btab\b", req):
            return len(obs.by_role("tab")) >= 1

        structured = [
            e for e in named if e.source in ("api", "dom", "uia") and e.interactive
        ]
        return len(structured) >= _ENOUGH_ELEMENTS

    def _finalize(
        self, elements: list[PerceivedElement], *, limit: int
    ) -> list[PerceivedElement]:
        # Prefer earlier hierarchy sources, but keep provider ordinal order
        # (do not alphabetical-sort — that breaks "first/second video").
        source_rank = {"api": 0, "dom": 1, "uia": 2, "ocr": 3, "vision": 4, "coords": 5}
        decorated = list(enumerate(elements))
        decorated.sort(
            key=lambda pair: (
                source_rank.get(pair[1].source, 9),
                pair[1].index if pair[1].index is not None else 10**6,
                pair[0],  # stable original order
            )
        )
        out: list[PerceivedElement] = []
        seen_names: set[str] = set()
        for _i, el in decorated:
            key = f"{el.role}:{_norm(el.name)}"
            if el.name and key in seen_names:
                continue
            if el.name:
                seen_names.add(key)
            out.append(el)
            if len(out) >= limit:
                break
        counters: dict[str, int] = {}
        for el in out:
            counters[el.role] = counters.get(el.role, 0) + 1
            if el.index is None:
                el.index = counters[el.role]
        return out

    def _focus_meta(self) -> tuple[str, str, int, str]:
        app, title, mon, url = "", "", 1, ""
        try:
            from neuron.windows import state as win_state
            fg = win_state.get_foreground()
            title = (fg.get("title") or "").strip()
        except Exception:
            pass
        try:
            import app_context
            app = (app_context.current_app() or "").strip()
        except Exception:
            pass
        if not app and title:
            parts = [p.strip() for p in title.split(" - ") if p.strip()]
            app = parts[-1][:60] if parts else title[:40]
        try:
            import browser
            url = (browser.current_url() or "").strip()
        except Exception:
            pass
        try:
            from neuron.brain.computer_state import get_last_state
            cs = get_last_state()
            if cs:
                mon = int(getattr(cs, "monitor_id", 1) or 1)
                if not url:
                    url = (getattr(cs, "browser_url", None) or "") or ""
        except Exception:
            pass
        return app, title, mon, url

    def _collect_api(self) -> list[PerceivedElement]:
        out: list[PerceivedElement] = []
        try:
            from neuron.windows import winops
            res = winops.get_windows({"limit": 24})
            wins = (res.state or {}).get("windows") or []
            for i, w in enumerate(wins, 1):
                title = (w.get("title") or "").strip()
                if not title:
                    continue
                out.append(
                    PerceivedElement(
                        id=_next_id("win", i),
                        role="window",
                        name=title,
                        application=(w.get("app") or w.get("process") or "")[:60],
                        window=title,
                        monitor=int(w.get("monitor_id") or 1),
                        interactive=True,
                        clickable=True,
                        bounds={
                            "left": int(w.get("left") or 0),
                            "top": int(w.get("top") or 0),
                            "right": int(w.get("right") or 0),
                            "bottom": int(w.get("bottom") or 0),
                        }
                        if w.get("left") is not None
                        else None,
                        source="api",
                        confidence=0.95,
                        index=i,
                        meta={"hwnd": w.get("hwnd")},
                    )
                )
        except Exception as exc:
            _log(f"windows api: {exc}")

        try:
            out.extend(self._youtube_videos_api())
        except Exception as exc:
            _log(f"youtube api: {exc}")
        return out

    def _youtube_videos_api(self) -> list[PerceivedElement]:
        out: list[PerceivedElement] = []
        try:
            import browser as br
            url = (br.current_url() or "").lower()
            if "youtube.com" not in url:
                return out
            ctrl = getattr(br, "_get", None)
            if not callable(ctrl):
                return out
            w = ctrl()
            if w is None:
                return out
            try:
                from browser import _active_page, _collect_watch_videos
                page = _active_page(w)
                videos = _collect_watch_videos(
                    page, limit=16, visible_only=True, nudge_scroll=False
                )
            except Exception:
                return out
            for i, v in enumerate(videos or [], 1):
                title = (v.get("title") or "").strip() or f"video {v.get('id') or i}"
                out.append(
                    PerceivedElement(
                        id=_next_id("yt", i),
                        role="video",
                        name=title,
                        application="Chrome",
                        window="YouTube",
                        interactive=True,
                        clickable=True,
                        source="api",
                        confidence=0.92,
                        index=i,
                        meta={"video_id": v.get("id"), "href": v.get("href")},
                    )
                )
        except Exception:
            return out
        return out

    def _collect_dom(self) -> list[PerceivedElement]:
        out: list[PerceivedElement] = []
        try:
            from neuron.browser import ops
            from neuron.browser import agent as br_agent

            url = ""
            try:
                import browser
                url = browser.current_url() or ""
            except Exception:
                pass
            if not url:
                return out

            def _submit_find(query: str, prefer: str) -> list[dict]:
                try:
                    data = br_agent._submit(  # type: ignore[attr-defined]
                        ops.op_find_element, query, "", prefer, 8
                    )
                    cands = list(data.get("candidates") or [])
                    best = data.get("best")
                    if best and best not in cands:
                        cands = [best] + cands
                    return cands
                except Exception:
                    return []

            for query, prefer, role_force in (
                ("search", "search", "text_field"),
                ("", "result", "browser_result"),
                ("", "click", ""),
            ):
                for el in _submit_find(query, prefer)[:10]:
                    name = (el.get("name") or el.get("text") or "").strip()
                    if not name and role_force != "text_field":
                        continue
                    role = role_force or _role_from_dom(el)
                    if role_force == "text_field" and not name:
                        name = "Search"
                    out.append(
                        PerceivedElement(
                            id=_next_id("dom", len(out) + 1),
                            role=role,
                            name=name or role,
                            source="dom",
                            confidence=min(
                                0.95, 0.5 + float(el.get("score") or 50) / 200.0
                            ),
                            interactive=True,
                            clickable=role != "text_field",
                            meta=dict(el),
                        )
                    )
        except Exception as exc:
            _log(f"dom collect: {exc}")
        return out

    def _collect_uia(self) -> list[PerceivedElement]:
        out: list[PerceivedElement] = []
        try:
            from neuron.uia import inspect as ui_inspect
            _win, elements = ui_inspect.walk_elements(
                max_depth=5, max_elements=50, interesting_only=True
            )
            for i, e in enumerate(elements[:50], 1):
                name = (e.name or "").strip()
                if not name:
                    continue
                ctype = e.control_type or ""
                role = _role_from_uia_type(ctype, name)
                inter = _interactive_uia(ctype)
                out.append(
                    PerceivedElement(
                        id=_next_id("uia", i),
                        role=role,
                        name=name,
                        source="uia",
                        confidence=0.88,
                        interactive=inter,
                        clickable=inter and role != "text_field",
                        bounds=e.bounds_dict() if hasattr(e, "bounds_dict") else None,
                        meta={
                            "control_type": ctype,
                            "automation_id": e.automation_id,
                            "center_x": e.center_x,
                            "center_y": e.center_y,
                        },
                    )
                )
        except Exception as exc:
            _log(f"uia collect: {exc}")
        return out

    def _collect_ocr(self) -> list[PerceivedElement]:
        out: list[PerceivedElement] = []
        try:
            from neuron.perception import capture_ops
            from neuron.perception.ocr import detect_text_regions

            cap = capture_ops.get_active_window_screenshot({})
            if not cap.success:
                cap = capture_ops.capture_screen({})
            if not cap.success:
                return out
            path = (cap.state or {}).get("path") or ""
            if not path:
                return out
            regions = detect_text_regions({"path": path})
            if not regions.success:
                return out
            ox = int((cap.state or {}).get("left") or 0)
            oy = int((cap.state or {}).get("top") or 0)
            for i, r in enumerate(((regions.state or {}).get("regions") or [])[:30], 1):
                text = (r.get("text") or "").strip()
                if not text or len(text) < 2:
                    continue
                cx = ox + int(r.get("center_x") or 0)
                cy = oy + int(r.get("center_y") or 0)
                role = "other"
                tl = text.lower()
                if any(w in tl for w in ("search", "find")):
                    role = "text_field"
                elif any(
                    w in tl for w in ("settings", "ok", "cancel", "save", "submit")
                ):
                    role = "button"
                out.append(
                    PerceivedElement(
                        id=_next_id("ocr", i),
                        role=role,
                        name=text[:120],
                        source="ocr",
                        confidence=min(
                            0.75, 0.35 + float(r.get("confidence") or 0) * 0.4
                        ),
                        interactive=True,
                        clickable=True,
                        bounds={"center_x": cx, "center_y": cy},
                        meta={"box": r.get("box"), "color_hint": None},
                    )
                )
        except Exception as exc:
            _log(f"ocr collect: {exc}")
        return out

    def _collect_vision(self, request: str, obs: Observation) -> str:
        try:
            from neuron.perception import pipeline
            from PIL import Image

            path = obs.screenshot_path
            if not path:
                from neuron.perception import capture_ops
                cap = capture_ops.get_active_window_screenshot({})
                if cap.success:
                    path = (cap.state or {}).get("path") or ""
                    obs.screenshot_path = path
            if not path:
                return ""
            img = Image.open(path)
            return pipeline._local_vlm(img, request or f"Describe: {obs.window}")
        except Exception as exc:
            _log(f"vision collect: {exc}")
            return ""


_engine: PerceptionEngine | None = None


def get_engine() -> PerceptionEngine:
    global _engine
    if _engine is None:
        _engine = PerceptionEngine()
    return _engine


def reset_engine(
    engine: PerceptionEngine | None = None,
) -> PerceptionEngine:
    global _engine
    _engine = engine if engine is not None else PerceptionEngine()
    return _engine


def observe(request: str = "", **kwargs: Any) -> Observation:
    return get_engine().observe(request, **kwargs)


def wants_ui_candidates(text: str) -> bool:
    """True when deixis / element language benefits from live UI candidates."""
    t = text or ""
    if _ORDINAL_HINT.search(t) and _ROLE_HINTS.search(t):
        return True
    if _ORDINAL_HINT.search(t) and re.search(r"\b(one|that|this)\b", t, re.I):
        return True
    if re.search(
        r"\b(search\s*box|settings\s*button|blue\s*button|\w+\s+window)\b", t, re.I
    ):
        return True
    return False


def prefer_roles_for(text: str) -> set[str]:
    t = _norm(text)
    roles: set[str] = set()
    if re.search(r"\bvideo", t):
        roles.add("video")
    if re.search(r"\bresult", t):
        roles.update({"browser_result", "video", "link"})
    if re.search(r"\bbutton", t):
        roles.add("button")
    if re.search(r"\b(search\s*box|text\s*field|textbox)", t):
        roles.add("text_field")
    if re.search(r"\bwindow", t):
        roles.add("window")
    if re.search(r"\btab", t):
        roles.add("tab")
    if re.search(r"\bmenu", t):
        roles.add("menu_item")
    if re.search(r"\blink", t):
        roles.add("link")
    return roles


def ui_candidates_for(
    text: str,
    *,
    engine: PerceptionEngine | None = None,
    observation: Observation | None = None,
    allow_ocr: bool = False,
    allow_vision: bool = False,
) -> list[dict[str, Any]]:
    """
    Produce ReferenceResolver-compatible ui_candidates from perception.

    Default: no OCR/vision — deixis should use DOM/UIA/API only.
    """
    eng = engine or get_engine()
    roles = prefer_roles_for(text) or None
    obs = observation or eng.observe(
        text,
        allow_ocr=allow_ocr,
        allow_vision=allow_vision,
        prefer_roles=roles,
    )
    if roles:
        cands = obs.ui_candidates(roles=roles)
        if cands:
            return cands
    for role_set in (
        {"video", "browser_result"},
        {"link", "list_item"},
        None,
    ):
        cands = obs.ui_candidates(roles=role_set)
        if cands:
            return cands
    return []
