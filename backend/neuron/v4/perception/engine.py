"""V4.2 PerceptionEngine — authoritative observe() → DesktopWorldModel.

Priority: WIN32 → UIA/a11y → browser → OCR → screen → coords (never primary).
Composes existing neuron.windows / uia / perception / browser — does not fork them.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.v4.perception.element_ids import (
    looks_sensitive_element,
    normalize_uia_role,
    stable_element_id,
)
from neuron.v4.perception.screen_diff import cheap_image_fingerprint, diff_desktop_states
from neuron.v4.perception.types import (
    CaptureMeta,
    FullscreenKind,
    PerceptionErrorCode,
    PerceptionFailure,
    PerceptionResult,
    PerceptionSource,
    ScreenDiffResult,
)
from neuron.v4.world import adapters
from neuron.v4.world.model import DesktopWorldModel, get_world_model
from neuron.v4.world.models import (
    ApplicationState,
    BrowserState,
    DesktopState,
    KnowledgeLevel,
    MonitorState,
    UIElementState,
    WindowState,
)


def _log(msg: str) -> None:
    print(f"[perceive-v4] {msg}", flush=True)


class PerceptionEngine:
    """Unified V4 observation entry point."""

    def __init__(self) -> None:
        self._last: PerceptionResult | None = None
        self._uia_timeout_s = 2.5
        self._ocr_probed: bool | None = None

    @property
    def last(self) -> PerceptionResult | None:
        return self._last

    # ------------------------------------------------------------------ public

    def observe(
        self,
        hint: str = "",
        *,
        deep: bool = False,
        use_ocr: bool = False,
        use_uia: bool = True,
        use_browser: bool = True,
        use_capture: bool = False,
        world: DesktopWorldModel | None = None,
        push_world: bool = True,
        target: str = "desktop",
    ) -> PerceptionResult:
        """Full / light desktop observation. Never claims success when empty."""
        t0 = time.perf_counter()
        timing: dict[str, float] = {}
        failures: list[PerceptionFailure] = []
        sources: list[str] = []

        # 1) Monitors (WIN32)
        t = time.perf_counter()
        monitors, mon_err = self._gather_monitors()
        timing["monitors_ms"] = (time.perf_counter() - t) * 1000
        if mon_err:
            failures.append(mon_err)
        else:
            sources.append(PerceptionSource.WIN32.value)

        # 2) Windows + foreground
        t = time.perf_counter()
        windows, fg, app, win_errs = self._gather_windows(monitors)
        timing["windows_ms"] = (time.perf_counter() - t) * 1000
        failures.extend(win_errs)
        if windows or fg:
            sources.append(PerceptionSource.WIN32.value)

        # 3) Cursor
        t = time.perf_counter()
        cursor = self._gather_cursor()
        timing["cursor_ms"] = (time.perf_counter() - t) * 1000

        active_mon = None
        if fg and fg.monitor_id is not None:
            active_mon = fg.monitor_id
        elif cursor.get("monitor") is not None:
            active_mon = cursor.get("monitor")

        # 4) UIA elements (optional / deep)
        elements: list[UIElementState] = []
        if use_uia and (deep or target in ("window", "desktop")):
            t = time.perf_counter()
            elements, uia_err = self._gather_uia(
                application=(app.name if app else ""),
                window=(fg.title if fg else ""),
                window_hwnd=(fg.hwnd if fg else 0),
                monitor_id=active_mon,
                limit=50 if deep else 24,
            )
            timing["uia_ms"] = (time.perf_counter() - t) * 1000
            if uia_err:
                failures.append(uia_err)
            elif elements:
                sources.append(PerceptionSource.UI_AUTOMATION.value)

        # 5) Browser
        browser = None
        if use_browser:
            t = time.perf_counter()
            browser, br_err = self._gather_browser(fg, app)
            timing["browser_ms"] = (time.perf_counter() - t) * 1000
            if br_err:
                failures.append(br_err)
            elif browser and (browser.url or browser.tab_title):
                sources.append(PerceptionSource.BROWSER.value)

        # 6) Optional capture + OCR (bounded, not every loop)
        capture = None
        ocr_text: list[str] = []
        ocr_available = self._ocr_probed
        if use_capture or use_ocr:
            t = time.perf_counter()
            capture, cap_err = self._capture_target(
                target=target, monitors=monitors, fg=fg, hint=hint
            )
            timing["capture_ms"] = (time.perf_counter() - t) * 1000
            if cap_err:
                failures.append(cap_err)
            elif capture:
                sources.append(PerceptionSource.SCREEN.value)

        if use_ocr:
            t = time.perf_counter()
            ocr_text, ocr_available, ocr_err = self._gather_ocr(capture, hint=hint)
            timing["ocr_ms"] = (time.perf_counter() - t) * 1000
            self._ocr_probed = ocr_available
            if ocr_err:
                failures.append(ocr_err)
            elif ocr_text:
                sources.append(PerceptionSource.OCR.value)
                # OCR lines as low-confidence text elements (skip sensitive)
                for i, line in enumerate(ocr_text[:20]):
                    if looks_sensitive_element(name=line):
                        continue
                    eid, conf = stable_element_id(
                        application=app.name if app else "",
                        window=fg.title if fg else "",
                        role="ocr_text",
                        name=line[:80],
                        source="ocr",
                    )
                    elements.append(
                        UIElementState(
                            id=eid,
                            role="other",
                            name=line[:80],
                            text=line[:120],
                            source="ocr",
                            application=app.name if app else "",
                            window=fg.title if fg else "",
                            monitor_id=active_mon,
                            interactive=False,
                            clickable=False,
                            confidence=min(0.55, conf),
                            knowledge=KnowledgeLevel.INFERRED,
                            attributes={"ocr_index": i},
                        )
                    )

        desktop = DesktopState(
            monitors=monitors,
            windows=windows,
            foreground_window=fg,
            foreground_application=app,
            active_monitor_id=active_mon,
            cursor_x=cursor.get("x"),
            cursor_y=cursor.get("y"),
            cursor_monitor_id=cursor.get("monitor"),
            visible_elements=elements,
            browser=browser,
            timestamp=time.time(),
            sources=list(dict.fromkeys(sources)),
            ocr_text=ocr_text[:40],
            error="; ".join(f.detail for f in failures[:3]) if failures and not (monitors or windows or fg) else None,
        )
        desktop.observation_confidence = _confidence(desktop, failures)
        desktop.ensure_fingerprint()

        # Diff vs world previous
        wm = world if world is not None else get_world_model()
        prev = wm.current if wm.current.ensure_fingerprint() else None
        # Prefer explicit previous snapshot when world already has history
        prev_state = wm.previous if (push_world and wm.previous) else (
            wm.current if (wm.current.windows or wm.current.foreground_window) else None
        )
        # Before update, previous for diff is current
        before_for_diff = wm.current if (wm.current.monitors or wm.current.windows or wm.current.foreground_window) else None
        region_fps = None
        if capture and capture.fingerprint and before_for_diff is not None:
            # compare only if we had a prior capture fingerprint stored in raw
            prev_cap = (before_for_diff.raw or {}).get("capture_fingerprint")
            if prev_cap:
                region_fps = (str(prev_cap), capture.fingerprint)

        screen_diff = diff_desktop_states(before_for_diff, desktop, region_fingerprints=region_fps)
        if capture and capture.fingerprint:
            desktop.raw["capture_fingerprint"] = capture.fingerprint

        timing["total_ms"] = (time.perf_counter() - t0) * 1000
        result = PerceptionResult(
            timestamp=desktop.timestamp,
            desktop=desktop,
            sources_used=list(dict.fromkeys(sources)),
            failures=failures,
            timing_ms={k: round(v, 2) for k, v in timing.items()},
            capture=capture,
            screen_diff=screen_diff,
            ocr_available=ocr_available,
            target=target,
            confidence=desktop.observation_confidence,
            note=(hint or "")[:80],
        )
        if push_world:
            wm.update(desktop.clone(), push_previous=True)
            # Recompute diff against the stored previous after push
            result.screen_diff = diff_desktop_states(wm.previous, wm.current, region_fingerprints=region_fps)
        self._last = result
        return result

    def observe_window(
        self,
        hwnd: int | None = None,
        title: str = "",
        **kwargs: Any,
    ) -> PerceptionResult:
        kwargs.setdefault("target", "window")
        kwargs.setdefault("deep", True)
        # Full observe then filter elements/windows emphasis
        res = self.observe(**kwargs)
        if hwnd or title:
            needle = (title or "").lower()
            wins = [
                w
                for w in res.desktop.windows
                if (hwnd and w.hwnd == int(hwnd))
                or (needle and needle in (w.title or "").lower())
            ]
            if wins:
                res.desktop.foreground_window = wins[0]
                res.desktop.windows = wins + [w for w in res.desktop.windows if w not in wins]
        return res

    def observe_monitor(self, monitor_id: int, **kwargs: Any) -> PerceptionResult:
        kwargs.setdefault("target", "monitor")
        res = self.observe(**kwargs)
        mid = int(monitor_id)
        res.desktop.windows = [w for w in res.desktop.windows if w.monitor_id == mid]
        res.desktop.active_monitor_id = mid
        res.target = "monitor"
        return res

    def observe_region(
        self,
        bounds: dict[str, int],
        **kwargs: Any,
    ) -> PerceptionResult:
        kwargs.setdefault("target", "region")
        kwargs.setdefault("use_capture", True)
        kwargs["_region_bounds"] = bounds
        # stash region on instance for capture
        self._region_bounds = dict(bounds or {})
        try:
            return self.observe(**{k: v for k, v in kwargs.items() if not k.startswith("_")})
        finally:
            self._region_bounds = None

    def observe_for_action(self, step: dict[str, Any] | None, **kwargs: Any) -> PerceptionResult:
        """Targeted observation hints from a plan step (verification prep)."""
        step = step or {}
        action = str(step.get("action") or "").lower()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if "monitor" in action or args.get("monitor"):
            mid = args.get("monitor") or args.get("monitor_id")
            try:
                return self.observe_monitor(int(mid), deep=True, **kwargs)
            except (TypeError, ValueError):
                pass
        if action.startswith("open_") or action in ("focus_window", "switch_window"):
            return self.observe(deep=True, use_uia=True, **kwargs)
        if "browser" in action or "youtube" in action or "search" in action:
            return self.observe(deep=True, use_browser=True, use_uia=True, **kwargs)
        if action in ("click", "click_ui_element", "type_text", "press_keys"):
            return self.observe(deep=True, use_uia=True, **kwargs)
        return self.observe(deep=bool(kwargs.pop("deep", False)), **kwargs)

    def normalize_into_world(
        self,
        observe_dict: dict[str, Any] | None,
        *,
        world: DesktopWorldModel | None = None,
        push_world: bool = True,
    ) -> PerceptionResult:
        """
        Cheap path: normalize an existing observe_world / ComputerState blob
        into DesktopWorldModel with stable element IDs + screen diff.
        Avoids a second full desktop scan inside AgentLoop.
        """
        t0 = time.perf_counter()
        wm = world if world is not None else get_world_model()
        before = wm.current if (wm.current.monitors or wm.current.windows or wm.current.foreground_window) else None
        desktop = adapters.from_observe_dict(observe_dict, previous=wm.current)
        # Assign stable IDs to elements
        app = desktop.foreground_application.name if desktop.foreground_application else ""
        win = desktop.foreground_window.title if desktop.foreground_window else ""
        hwnd = desktop.foreground_window.hwnd if desktop.foreground_window else 0
        enriched: list[UIElementState] = []
        for e in desktop.visible_elements:
            if looks_sensitive_element(name=e.name, role=e.role):
                continue
            eid, conf = stable_element_id(
                application=e.application or app,
                window=e.window or win,
                window_hwnd=hwnd,
                automation_id=str((e.attributes or {}).get("automation_id") or ""),
                role=e.role,
                name=e.name,
                hierarchy=str((e.attributes or {}).get("path") or ""),
                bounds=e.bounds,
                source=e.source,
            )
            e.id = eid
            e.confidence = max(e.confidence, conf * 0.9)
            if e.source:
                e.source = e.source
            else:
                e.source = "uia"
            enriched.append(e)
        desktop.visible_elements = enriched
        # Improve display_mode on fg window when bounds+monitors known
        if desktop.foreground_window and desktop.monitors:
            mode = classify_fullscreen(desktop.foreground_window, desktop.monitors)
            if mode is FullscreenKind.WINDOW_FULLSCREEN:
                desktop.foreground_window.fullscreen = True
            elif mode is FullscreenKind.WINDOW_MAXIMIZED:
                desktop.foreground_window.maximized = True
            elif mode is FullscreenKind.WINDOW_NORMAL:
                desktop.foreground_window.fullscreen = False
                desktop.foreground_window.maximized = False
            desktop.raw["fg_display_mode"] = mode.value

        desktop.sources = list(
            dict.fromkeys(
                list(desktop.sources)
                + [PerceptionSource.OBSERVE_DICT.value]
                + (["COMPUTER_STATE"] if (observe_dict or {}).get("computer_state") else [])
            )
        )
        desktop.ensure_fingerprint()
        screen_diff = diff_desktop_states(before, desktop)
        if push_world:
            wm.update(desktop.clone(), push_previous=True)
            screen_diff = diff_desktop_states(wm.previous, wm.current)

        result = PerceptionResult(
            timestamp=desktop.timestamp or time.time(),
            desktop=desktop,
            sources_used=list(desktop.sources),
            failures=[],
            timing_ms={"normalize_ms": round((time.perf_counter() - t0) * 1000, 2)},
            screen_diff=screen_diff,
            ocr_available=self._ocr_probed,
            target="desktop",
            confidence=desktop.observation_confidence,
            note="normalize_into_world",
        )
        self._last = result
        return result

    # ------------------------------------------------------------------ gather

    def _gather_monitors(self) -> tuple[list[MonitorState], PerceptionFailure | None]:
        try:
            from neuron.windows import monitors as mon_mod
            raw = mon_mod.list_monitor_dicts() or []
            return [MonitorState.from_dict(m) for m in raw], None
        except Exception as exc:
            return [], PerceptionFailure(
                code=PerceptionErrorCode.MONITOR_ENUM_FAILED,
                source=PerceptionSource.WIN32.value,
                detail=str(exc)[:160],
            )

    def _gather_windows(
        self, monitors: list[MonitorState]
    ) -> tuple[list[WindowState], WindowState | None, ApplicationState | None, list[PerceptionFailure]]:
        errs: list[PerceptionFailure] = []
        windows: list[WindowState] = []
        fg_win: WindowState | None = None
        app_state: ApplicationState | None = None

        fg_raw: dict[str, Any] = {}
        try:
            from neuron.windows import state as win_state
            fg_raw = win_state.get_foreground() or {}
        except Exception as exc:
            errs.append(
                PerceptionFailure(
                    code=PerceptionErrorCode.WINDOW_ENUM_FAILED,
                    source=PerceptionSource.WIN32.value,
                    detail=f"foreground: {exc}"[:160],
                )
            )

        try:
            from neuron.windows import state as win_state
            rows = win_state.list_top_windows(40) or []
        except Exception as exc:
            rows = []
            errs.append(
                PerceptionFailure(
                    code=PerceptionErrorCode.WINDOW_ENUM_FAILED,
                    source=PerceptionSource.WIN32.value,
                    detail=str(exc)[:160],
                )
            )

        mon_dicts = [m.to_dict() for m in monitors]
        for row in rows:
            w = _window_from_row(row, mon_dicts)
            windows.append(w)

        if fg_raw:
            fg_win = _window_from_row(fg_raw, mon_dicts)
            fg_win.focused = True
            # merge into list
            if fg_win.hwnd:
                windows = [fg_win] + [w for w in windows if w.hwnd != fg_win.hwnd]
            mode = classify_fullscreen(fg_win, monitors)
            if mode is FullscreenKind.WINDOW_FULLSCREEN:
                fg_win.fullscreen = True
            elif mode is FullscreenKind.WINDOW_MAXIMIZED:
                fg_win.maximized = True
            elif mode is FullscreenKind.WINDOW_NORMAL:
                fg_win.fullscreen = False
                fg_win.maximized = False
            # else UNKNOWN — leave None

            app_name = fg_win.application
            know = fg_win.application_knowledge
            if app_name:
                app_state = ApplicationState(
                    name=app_name,
                    focused=True,
                    window_hwnds=[fg_win.hwnd] if fg_win.hwnd else [],
                    confidence=0.9 if know is KnowledgeLevel.KNOWN else 0.55,
                    knowledge=know,
                )

        return windows, fg_win, app_state, errs

    def _gather_cursor(self) -> dict[str, Any]:
        try:
            from neuron.perception import capture_ops
            r = capture_ops.get_cursor_position({})
            if r.success and r.state:
                return {
                    "x": r.state.get("x"),
                    "y": r.state.get("y"),
                    "monitor": r.state.get("monitor"),
                }
        except Exception:
            pass
        return {}

    def _gather_uia(
        self,
        *,
        application: str,
        window: str,
        window_hwnd: int,
        monitor_id: int | None,
        limit: int,
    ) -> tuple[list[UIElementState], PerceptionFailure | None]:
        try:
            from neuron.uia import inspect as uia_inspect
            t0 = time.perf_counter()
            _win, elements = uia_inspect.walk_elements(
                max_depth=5, max_elements=limit, interesting_only=True
            )
            if (time.perf_counter() - t0) > self._uia_timeout_s + 5:
                # walk itself may be slow; soft note only
                pass
            out: list[UIElementState] = []
            for e in elements[:limit]:
                name = (getattr(e, "name", None) or "")[:120]
                ctype = getattr(e, "control_type", "") or ""
                aid = getattr(e, "automation_id", "") or ""
                if looks_sensitive_element(name=name, automation_id=aid, role=ctype):
                    continue
                role = normalize_uia_role(ctype, name)
                bounds = {
                    "left": int(getattr(e, "left", 0) or 0),
                    "top": int(getattr(e, "top", 0) or 0),
                    "width": int(getattr(e, "width", 0) or 0),
                    "height": int(getattr(e, "height", 0) or 0),
                    "center_x": int(getattr(e, "center_x", 0) or 0),
                    "center_y": int(getattr(e, "center_y", 0) or 0),
                }
                path = getattr(e, "path", "") or ""
                eid, conf = stable_element_id(
                    application=application,
                    window=window,
                    window_hwnd=window_hwnd,
                    automation_id=aid,
                    role=role,
                    name=name,
                    hierarchy=path,
                    bounds=bounds,
                    source="uia",
                )
                out.append(
                    UIElementState(
                        id=eid,
                        role=role,
                        name=name,
                        text=(getattr(e, "value", None) or name)[:120],
                        bounds=bounds,
                        source="uia",
                        application=application,
                        window=window,
                        monitor_id=monitor_id,
                        interactive=True,
                        clickable=role in ("button", "link", "tab", "menu_item", "list_item", "checkbox"),
                        confidence=conf,
                        knowledge=KnowledgeLevel.KNOWN if aid else KnowledgeLevel.INFERRED,
                        attributes={
                            "automation_id": aid,
                            "control_type": ctype,
                            "path": path[:120],
                            "enabled": bool(getattr(e, "enabled", True)),
                        },
                    )
                )
            return out, None
        except Exception as exc:
            return [], PerceptionFailure(
                code=PerceptionErrorCode.UIA_TIMEOUT
                if "timeout" in str(exc).lower()
                else PerceptionErrorCode.ACCESS_DENIED,
                source=PerceptionSource.UI_AUTOMATION.value,
                detail=str(exc)[:160],
            )

    def _gather_browser(
        self,
        fg: WindowState | None,
        app: ApplicationState | None,
    ) -> tuple[BrowserState | None, PerceptionFailure | None]:
        app_name = (app.name if app else "") or (fg.application if fg else "")
        low = app_name.lower()
        is_browser = any(b in low for b in ("chrome", "edge", "firefox", "opera", "brave", "msedge"))
        url = ""
        try:
            import browser
            url = (browser.current_url() or "").strip()
        except Exception as exc:
            if is_browser:
                return (
                    BrowserState(
                        browser=_browser_token(app_name),
                        window_hwnd=fg.hwnd if fg else 0,
                        tab_title=fg.title if fg else "",
                        url="",
                        page_type="",
                        media_state="",
                        confidence=0.35,
                        knowledge=KnowledgeLevel.INFERRED,
                    ),
                    PerceptionFailure(
                        code=PerceptionErrorCode.BROWSER_UNAVAILABLE,
                        source=PerceptionSource.BROWSER.value,
                        detail=str(exc)[:120],
                    ),
                )
            return None, None

        if not url and not is_browser:
            return None, None

        # URL from integration → KNOWN; title-only browser guess → INFERRED low conf
        if url:
            bs = BrowserState(
                browser=_browser_token(app_name) or _browser_from_url(url),
                window_hwnd=fg.hwnd if fg else 0,
                tab_title=fg.title if fg else "",
                url=url[:400],
                page_type=_page_type(url),
                media_state="",  # UNKNOWN — do not fake
                confidence=0.85,
                knowledge=KnowledgeLevel.KNOWN,
            )
            return bs, None

        return (
            BrowserState(
                browser=_browser_token(app_name),
                window_hwnd=fg.hwnd if fg else 0,
                tab_title=fg.title if fg else "",
                url="",
                page_type="",
                media_state="",
                confidence=0.3,
                knowledge=KnowledgeLevel.INFERRED,
            ),
            None,
        )

    def _capture_target(
        self,
        *,
        target: str,
        monitors: list[MonitorState],
        fg: WindowState | None,
        hint: str,
    ) -> tuple[CaptureMeta | None, PerceptionFailure | None]:
        try:
            import screen_capture as sc
            from neuron.perception.capture_ops import prepare_image

            img = None
            kind = target
            bounds: dict[str, int] = {}
            mon_id = None
            hwnd = fg.hwnd if fg else 0
            region = getattr(self, "_region_bounds", None)
            if target == "region" and region:
                # Best-effort: capture monitor containing region, fingerprint only
                mon_id = region.get("monitor")
                if mon_id is None and monitors:
                    for m in monitors:
                        if m.contains_point(int(region.get("left") or 0), int(region.get("top") or 0)):
                            mon_id = m.id
                            break
                if mon_id is not None:
                    raw_mons = sc.list_monitors() or []
                    mon = next((m for m in raw_mons if int(getattr(m, "id", 0) or 0) == int(mon_id)), None)
                    if mon is not None:
                        img = sc.capture_monitor(mon)
                        bounds = {
                            "left": int(region.get("left") or 0),
                            "top": int(region.get("top") or 0),
                            "width": int(region.get("width") or 0),
                            "height": int(region.get("height") or 0),
                        }
                        kind = "region"
            elif target == "monitor" and monitors:
                mon_id = monitors[0].id
                raw_mons = sc.list_monitors() or []
                mon = next((m for m in raw_mons if int(getattr(m, "id", 0) or 0) == int(mon_id)), raw_mons[0] if raw_mons else None)
                if mon is not None:
                    img = sc.capture_monitor(mon)
                    bounds = {
                        "left": int(getattr(mon, "left", 0) or 0),
                        "top": int(getattr(mon, "top", 0) or 0),
                        "width": int(getattr(mon, "width", 0) or 0),
                        "height": int(getattr(mon, "height", 0) or 0),
                    }
                    kind = "monitor"
            else:
                # Active window / primary monitor — transient, not persisted by default
                try:
                    from neuron.perception import capture_ops
                    cap = capture_ops.get_active_window_screenshot({})
                    if cap.success and (cap.state or {}).get("path"):
                        # Use fingerprint only; avoid relying on permanent file
                        from PIL import Image
                        path = (cap.state or {}).get("path")
                        img = Image.open(path)
                        bounds = {
                            "width": int(img.width),
                            "height": int(img.height),
                        }
                        kind = "window"
                except Exception:
                    raw_mons = sc.list_monitors() or []
                    if raw_mons:
                        img = sc.capture_monitor(raw_mons[0])
                        kind = "monitor"

            if img is None:
                return None, PerceptionFailure(
                    code=PerceptionErrorCode.CAPTURE_FAILED,
                    source=PerceptionSource.SCREEN.value,
                    detail="no image",
                )
            img = prepare_image(img, max_width=640)
            fp = cheap_image_fingerprint(img)
            return (
                CaptureMeta(
                    bounds=bounds,
                    width=int(getattr(img, "width", 0) or 0),
                    height=int(getattr(img, "height", 0) or 0),
                    monitor_id=int(mon_id) if mon_id is not None else None,
                    window_hwnd=int(hwnd or 0),
                    timestamp=time.time(),
                    path="",  # do not advertise permanent path
                    kind=kind,
                    fingerprint=fp,
                ),
                None,
            )
        except Exception as exc:
            return None, PerceptionFailure(
                code=PerceptionErrorCode.CAPTURE_FAILED,
                source=PerceptionSource.SCREEN.value,
                detail=str(exc)[:160],
            )

    def _gather_ocr(
        self,
        capture: CaptureMeta | None,
        *,
        hint: str,
    ) -> tuple[list[str], bool, PerceptionFailure | None]:
        try:
            from neuron.perception import ocr as ocr_mod
            # Probe availability
            try:
                ocr_mod._engine()
                available = True
            except Exception as exc:
                return [], False, PerceptionFailure(
                    code=PerceptionErrorCode.OCR_UNAVAILABLE,
                    source=PerceptionSource.OCR.value,
                    detail=str(exc)[:160],
                )
            # Region OCR only when we have a path from legacy capture_ops — soft
            r = ocr_mod.ocr_image({})
            if not r.success:
                return [], available, PerceptionFailure(
                    code=PerceptionErrorCode.OCR_UNAVAILABLE,
                    source=PerceptionSource.OCR.value,
                    detail=(r.error or "ocr failed")[:160],
                )
            texts = list((r.state or {}).get("text") or (r.state or {}).get("visible_text") or [])
            # Privacy: drop sensitive-looking lines
            cleaned = [t for t in texts if not looks_sensitive_element(name=str(t))]
            return [str(t)[:120] for t in cleaned[:40]], available, None
        except Exception as exc:
            return [], False, PerceptionFailure(
                code=PerceptionErrorCode.OCR_UNAVAILABLE,
                source=PerceptionSource.OCR.value,
                detail=str(exc)[:160],
            )


# ------------------------------------------------------------------ helpers


def classify_fullscreen(window: WindowState, monitors: list[MonitorState]) -> FullscreenKind:
    """Deterministic geometry classification. MEDIA_FULLSCREEN stays UNKNOWN here."""
    if (
        window.left is None
        or window.top is None
        or window.width is None
        or window.height is None
        or not monitors
    ):
        return FullscreenKind.UNKNOWN
    mon = None
    if window.monitor_id is not None:
        mon = next((m for m in monitors if m.id == window.monitor_id), None)
    if mon is None:
        cx = int(window.left) + int(window.width) // 2
        cy = int(window.top) + int(window.height) // 2
        mon = next((m for m in monitors if m.contains_point(cx, cy)), None)
    if mon is None:
        return FullscreenKind.UNKNOWN

    wl = int(window.left)
    wt = int(window.top)
    ww = int(window.width)
    wh = int(window.height)

    # Fullscreen: matches monitor outer bounds closely
    if (
        abs(wl - mon.left) <= 2
        and abs(wt - mon.top) <= 2
        and abs(ww - mon.width) <= 4
        and abs(wh - mon.height) <= 4
    ):
        return FullscreenKind.WINDOW_FULLSCREEN

    work_l = mon.work_left if mon.work_left is not None else mon.left
    work_t = mon.work_top if mon.work_top is not None else mon.top
    work_w = mon.work_width if mon.work_width is not None else mon.width
    work_h = mon.work_height if mon.work_height is not None else mon.height
    if (
        abs(wl - int(work_l)) <= 8
        and abs(wt - int(work_t)) <= 8
        and abs(ww - int(work_w)) <= 16
        and abs(wh - int(work_h)) <= 24
    ):
        return FullscreenKind.WINDOW_MAXIMIZED

    return FullscreenKind.WINDOW_NORMAL


def _window_from_row(row: dict[str, Any], monitors: list[dict[str, Any]]) -> WindowState:
    left = row.get("left")
    top = row.get("top")
    width = row.get("width")
    height = row.get("height")
    if width is None and row.get("right") is not None and left is not None:
        try:
            width = int(row["right"]) - int(left)
        except (TypeError, ValueError):
            width = None
    if height is None and row.get("bottom") is not None and top is not None:
        try:
            height = int(row["bottom"]) - int(top)
        except (TypeError, ValueError):
            height = None
    mon_id = row.get("monitor_id") or row.get("monitor")
    if mon_id is None and left is not None and top is not None and monitors:
        try:
            from neuron.windows import monitors as mon_mod
            hit = mon_mod.monitor_for_rect(
                int(left),
                int(top),
                int(width or 100),
                int(height or 100),
                monitors,
            )
            if hit:
                mon_id = hit.get("id")
        except Exception:
            cx = int(left) + int(width or 0) // 2
            cy = int(top) + int(height or 0) // 2
            for m in monitors:
                try:
                    if (
                        int(m["left"]) <= cx < int(m["left"]) + int(m["width"])
                        and int(m["top"]) <= cy < int(m["top"]) + int(m["height"])
                    ):
                        mon_id = m.get("id")
                        break
                except Exception:
                    continue
    return WindowState.from_dict(
        {
            "hwnd": row.get("hwnd") or 0,
            "title": row.get("title") or "",
            "app": row.get("app") or row.get("process") or "",
            "process": row.get("process") or "",
            "monitor_id": mon_id,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "focused": bool(row.get("focused")),
            "visible": True,
            "confidence": 0.9 if row.get("hwnd") else 0.5,
        }
    )


def _confidence(desktop: DesktopState, failures: list[PerceptionFailure]) -> float:
    score = 0.15
    if desktop.monitors:
        score += 0.2
    if desktop.windows:
        score += 0.15
    if desktop.foreground_window and desktop.foreground_window.hwnd:
        score += 0.25
    elif desktop.foreground_window:
        score += 0.1
    if desktop.visible_elements:
        score += 0.15
    if desktop.browser and desktop.browser.url:
        score += 0.1
    if failures:
        score -= min(0.25, 0.05 * len(failures))
    return max(0.0, min(1.0, score))


def _browser_token(app: str) -> str:
    low = (app or "").lower()
    for b in ("chrome", "edge", "firefox", "opera", "brave", "msedge"):
        if b in low:
            return "edge" if b == "msedge" else b
    return ""


def _browser_from_url(url: str) -> str:
    return ""


def _page_type(url: str) -> str:
    u = (url or "").lower()
    if not u:
        return ""
    if "youtube.com/watch" in u or "youtu.be/" in u:
        return "watch"
    if "youtube.com/results" in u or "search_query=" in u:
        return "search"
    if "youtube.com" in u:
        return "home"
    return "unknown"


_ENGINE: PerceptionEngine | None = None


def get_perception_engine() -> PerceptionEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = PerceptionEngine()
    return _ENGINE


def reset_perception_engine() -> PerceptionEngine:
    global _ENGINE
    _ENGINE = PerceptionEngine()
    return _ENGINE
