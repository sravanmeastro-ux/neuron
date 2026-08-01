"""Deterministic verification strategies against DesktopWorldModel."""

from __future__ import annotations

from typing import Any

from neuron.v4.types import VerificationOutcome
from neuron.v4.verify.types import (
    CONF_HIGH,
    CONF_LOW,
    CONF_MEDIUM,
    CONF_SUCCESS_MIN,
    ExpectationKind,
    VerificationEvidence,
    VerificationExpectation,
    VerificationMethod,
)


def _desktop(world):
    if world is None:
        return None
    return getattr(world, "current", world)


def _app_window(world, app: str):
    if world is None or not app:
        return None
    try:
        return world.get_window_by_application(app)
    except Exception:
        return None


def check_expectation(
    expectation: VerificationExpectation,
    *,
    world_after=None,
    world_before=None,
    screen_diff=None,
    action_result: dict[str, Any] | None = None,
    revalidate_status: str = "",
) -> tuple[VerificationOutcome, float, VerificationEvidence, str, str]:
    """
    Returns (status, confidence, evidence, reason, method).
    Never upgrades weak evidence to SUCCESS.
    """
    ev = VerificationEvidence()
    after = _desktop(world_after) if world_after is not None else None
    before = _desktop(world_before) if world_before is not None else None
    if after is not None:
        try:
            ev.after_fp = getattr(after, "ensure_fingerprint", lambda: "")() or ""
        except Exception:
            pass
    if before is not None:
        try:
            ev.before_fp = getattr(before, "ensure_fingerprint", lambda: "")() or ""
        except Exception:
            pass

    kind = expectation.kind
    ar = action_result or {}

    if kind is ExpectationKind.NONE or expectation.params.get("not_observable"):
        ev.add("observable", False, source="policy")
        # Tool ok alone never SUCCESS for non-observable
        return (
            VerificationOutcome.UNCERTAIN,
            CONF_LOW,
            ev,
            "effect not observable in DesktopWorldModel",
            VerificationMethod.COMPOSITE.value,
        )

    if kind is ExpectationKind.APP_OPEN:
        return _check_app_open(expectation, world_after, ev, ar)

    if kind is ExpectationKind.WINDOW_EXISTS:
        return _check_window_exists(expectation, world_after, ev)

    if kind is ExpectationKind.WINDOW_FOCUSED:
        return _check_focused(expectation, world_after, ev)

    if kind is ExpectationKind.WINDOW_ON_MONITOR:
        return _check_on_monitor(expectation, world_after, ev)

    if kind is ExpectationKind.WINDOW_MAXIMIZED:
        return _check_maximized(expectation, world_after, ev, media=False)

    if kind is ExpectationKind.WINDOW_FULLSCREEN:
        return _check_maximized(expectation, world_after, ev, media=False, want_fullscreen=True)

    if kind is ExpectationKind.MEDIA_FULLSCREEN:
        return _check_media_fullscreen(expectation, world_after, ev)

    if kind is ExpectationKind.URL_MATCH:
        return _check_url(expectation, world_after, ev)

    if kind is ExpectationKind.ELEMENT_STATE_CHANGED:
        return _check_click_effect(expectation, world_before, world_after, screen_diff, ev, revalidate_status)

    if kind is ExpectationKind.ELEMENT_DISAPPEARED:
        return _check_element_gone(expectation, world_after, ev, revalidate_status)

    if kind is ExpectationKind.ELEMENT_EXISTS:
        return _check_element_exists(expectation, world_after, ev)

    if kind is ExpectationKind.TEXT_IN_FIELD:
        return _check_type(expectation, world_after, ev)

    if kind is ExpectationKind.SCREEN_CHANGED:
        return _check_screen_changed(expectation, screen_diff, ev)

    if kind is ExpectationKind.MEDIA_STATE:
        return _check_media_state(expectation, world_after, ev)

    ev.add("kind", kind.value, source="engine")
    return (
        VerificationOutcome.UNCERTAIN,
        CONF_LOW,
        ev,
        f"no strategy for {kind.value}",
        VerificationMethod.COMPOSITE.value,
    )


def _check_app_open(exp, world, ev, ar) -> tuple:
    app = exp.application
    if not app:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no application in expectation", VerificationMethod.WINDOW_QUERY.value

    w = _app_window(world, app)
    process_claimed = bool((ar.get("state") or {}).get("process")) or bool(ar.get("process"))
    verified_flag = (ar.get("state") or {}).get("verified")

    if w is not None:
        ev.add("window_hwnd", w.hwnd, source="WIN32")
        ev.add("window_title", (w.title or "")[:80], source="WIN32")
        ev.add("application", w.application, source="WIN32")
        conf = CONF_HIGH if w.hwnd else CONF_MEDIUM
        return (
            VerificationOutcome.SUCCESS,
            conf,
            ev,
            f"{app} window observed",
            VerificationMethod.WINDOW_QUERY.value,
        )

    # Process without window
    if process_claimed or verified_flag is False:
        ev.add("process_without_window", True, source="ActionResult")
        ev.add("conflicts", "process_vs_window", source="policy")
        ev.conflicts.append("process exists but no usable window")
        return (
            VerificationOutcome.UNCERTAIN,
            CONF_MEDIUM,
            ev,
            "process may exist but window not observed",
            VerificationMethod.WINDOW_QUERY.value,
        )

    desktop = _desktop(world)
    if desktop is None or (not getattr(desktop, "windows", None) and getattr(desktop, "observation_confidence", 0) < 0.3):
        ev.add("world", "empty_or_unknown", source="world")
        return (
            VerificationOutcome.UNCERTAIN,
            CONF_LOW,
            ev,
            "world state insufficient to confirm app open",
            VerificationMethod.WINDOW_QUERY.value,
        )

    # Have window enum, no match → FAILURE
    ev.add("window_found", False, source="WIN32")
    return (
        VerificationOutcome.FAILURE,
        CONF_HIGH,
        ev,
        f"{app} window not found",
        VerificationMethod.WINDOW_QUERY.value,
    )


def _check_window_exists(exp, world, ev) -> tuple:
    want_absent = bool(exp.params.get("want_absent"))
    w = _app_window(world, exp.application)
    if want_absent:
        if w is None:
            desktop = _desktop(world)
            if desktop is None or not getattr(desktop, "windows", None):
                return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "cannot confirm close", VerificationMethod.WINDOW_QUERY.value
            ev.add("window_absent", True, source="WIN32")
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, f"{exp.application} closed", VerificationMethod.WINDOW_QUERY.value
        ev.add("window_still_present", True, source="WIN32")
        return VerificationOutcome.FAILURE, CONF_HIGH, ev, f"{exp.application} still open", VerificationMethod.WINDOW_QUERY.value
    if w is not None:
        ev.add("window_hwnd", w.hwnd, source="WIN32")
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "window exists", VerificationMethod.WINDOW_QUERY.value
    return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, "window missing", VerificationMethod.WINDOW_QUERY.value


def _check_focused(exp, world, ev) -> tuple:
    app = exp.application
    if world is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no world", VerificationMethod.WINDOW_QUERY.value
    try:
        active = (world.get_active_application() or "").strip()
    except Exception:
        active = ""
    fg = None
    try:
        fg = world.get_foreground_window()
    except Exception:
        pass
    ev.add("active_application", active, source="WIN32")
    if fg:
        ev.add("fg_title", (fg.title or "")[:80], source="WIN32")
        ev.add("fg_app", fg.application, source="WIN32")

    if not active and fg is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "foreground unknown", VerificationMethod.WINDOW_QUERY.value

    needle = app.lower()
    hit = False
    if needle and needle in active.lower():
        hit = True
    if fg and needle and (
        needle in (fg.application or "").lower() or needle in (fg.title or "").lower()
    ):
        hit = True
    if hit:
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, f"{app} is foreground", VerificationMethod.WINDOW_QUERY.value
    if active or fg:
        return VerificationOutcome.FAILURE, CONF_HIGH, ev, f"foreground is {active or (fg.application if fg else '?')}", VerificationMethod.WINDOW_QUERY.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "focus undetermined", VerificationMethod.WINDOW_QUERY.value


def _check_on_monitor(exp, world, ev) -> tuple:
    app = exp.application
    mon_ref = exp.monitor
    if world is None or not app or mon_ref is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "missing app/monitor/world", VerificationMethod.MONITOR_GEOMETRY.value

    w = _app_window(world, app)
    if w is None:
        return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, f"{app} window missing", VerificationMethod.MONITOR_GEOMETRY.value

    try:
        # Do NOT pass application= — that resolves "monitor with app" (current placement).
        target = world.resolve_monitor_reference(mon_ref, relative_to=w.monitor_id)
    except Exception:
        target = None
    if target is None:
        try:
            target = world.get_monitor_by_id(int(mon_ref))
        except (TypeError, ValueError):
            target = None
    if target is None:
        ev.add("monitor_resolve", "failed", source="world")
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "could not resolve target monitor", VerificationMethod.MONITOR_GEOMETRY.value

    placed = None
    try:
        placed = world.get_monitor_for_window(w)
    except Exception:
        pass
    before_id = w.monitor_id
    after_id = placed.id if placed else w.monitor_id
    ev.add("before_monitor_id", before_id, source="WIN32")
    ev.add("after_monitor_id", after_id, source="WIN32")
    ev.add("target_monitor_id", target.id, source="geometry")
    if w.bounds_dict():
        b = w.bounds_dict()
        ev.add("geometry", f"{b.get('left')},{b.get('top')} {b.get('width')}x{b.get('height')}", source="WIN32")

    if after_id is not None and int(after_id) == int(target.id):
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, f"{app} on monitor {target.id}", VerificationMethod.MONITOR_GEOMETRY.value
    if after_id is not None:
        return VerificationOutcome.FAILURE, CONF_HIGH, ev, f"{app} on monitor {after_id}, want {target.id}", VerificationMethod.MONITOR_GEOMETRY.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "window monitor unknown", VerificationMethod.MONITOR_GEOMETRY.value


def _check_maximized(exp, world, ev, *, media: bool, want_fullscreen: bool = False) -> tuple:
    from neuron.v4.perception.engine import classify_fullscreen
    from neuron.v4.perception.types import FullscreenKind

    desktop = _desktop(world)
    if desktop is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no desktop", VerificationMethod.WINDOW_QUERY.value
    w = _app_window(world, exp.application) if exp.application else getattr(desktop, "foreground_window", None)
    if w is None:
        w = getattr(desktop, "foreground_window", None)
    if w is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no window", VerificationMethod.WINDOW_QUERY.value
    kind = classify_fullscreen(w, list(getattr(desktop, "monitors", None) or []))
    ev.add("window_fullscreen_kind", kind.value, source="geometry")
    if want_fullscreen:
        if kind is FullscreenKind.WINDOW_FULLSCREEN:
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "window fullscreen", VerificationMethod.WINDOW_QUERY.value
        if kind is FullscreenKind.WINDOW_MAXIMIZED:
            ev.conflicts.append("maximized_not_fullscreen")
            return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "maximized ≠ fullscreen", VerificationMethod.WINDOW_QUERY.value
        if kind is FullscreenKind.UNKNOWN:
            return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "fullscreen unknown", VerificationMethod.WINDOW_QUERY.value
        return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, "not fullscreen", VerificationMethod.WINDOW_QUERY.value
    if kind is FullscreenKind.WINDOW_MAXIMIZED:
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "window maximized", VerificationMethod.WINDOW_QUERY.value
    return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, f"kind={kind.value}", VerificationMethod.WINDOW_QUERY.value


def _check_media_fullscreen(exp, world, ev) -> tuple:
    """MEDIA_FULLSCREEN — maximized browser is NOT success."""
    from neuron.v4.perception.engine import classify_fullscreen
    from neuron.v4.perception.types import FullscreenKind

    desktop = _desktop(world)
    if desktop is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no desktop", VerificationMethod.BROWSER_STATE.value

    br = getattr(desktop, "browser", None)
    media_fs = None
    if br is not None:
        media_fs = getattr(br, "fullscreen", None)
        media_state = getattr(br, "media_state", "") or ""
        ev.add("browser_fullscreen", media_fs, source="BROWSER")
        ev.add("media_state", media_state, source="BROWSER")

    w = getattr(desktop, "foreground_window", None)
    win_kind = FullscreenKind.UNKNOWN
    if w is not None:
        win_kind = classify_fullscreen(w, list(desktop.monitors or []))
        ev.add("window_kind", win_kind.value, source="geometry")

    if exp.params.get("exit"):
        if media_fs is False:
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "exited media fullscreen", VerificationMethod.BROWSER_STATE.value
        if media_fs is None and win_kind is FullscreenKind.WINDOW_NORMAL:
            return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "exit fullscreen unconfirmed", VerificationMethod.BROWSER_STATE.value

    if media_fs is True:
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "media fullscreen true", VerificationMethod.BROWSER_STATE.value

    if media_fs is False:
        return VerificationOutcome.FAILURE, CONF_HIGH, ev, "media fullscreen false", VerificationMethod.BROWSER_STATE.value

    # media unknown
    if win_kind is FullscreenKind.WINDOW_MAXIMIZED:
        ev.conflicts.append("maximized_vs_media_fullscreen_unknown")
        return (
            VerificationOutcome.UNCERTAIN,
            CONF_MEDIUM,
            ev,
            "window maximized; media fullscreen UNKNOWN",
            VerificationMethod.BROWSER_STATE.value,
        )
    if win_kind is FullscreenKind.WINDOW_FULLSCREEN:
        ev.conflicts.append("window_fullscreen_vs_media_unknown")
        return (
            VerificationOutcome.UNCERTAIN,
            CONF_MEDIUM,
            ev,
            "window fullscreen; media fullscreen UNKNOWN",
            VerificationMethod.BROWSER_STATE.value,
        )
    return (
        VerificationOutcome.UNCERTAIN,
        CONF_LOW,
        ev,
        "media fullscreen UNKNOWN",
        VerificationMethod.BROWSER_STATE.value,
    )


def _check_url(exp, world, ev) -> tuple:
    desktop = _desktop(world)
    if desktop is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no desktop", VerificationMethod.BROWSER_STATE.value

    br = getattr(desktop, "browser", None)
    url = (br.url if br else "") or ""
    title = (br.tab_title if br else "") or ""
    if not url and not title:
        # fallback window title
        w = getattr(desktop, "foreground_window", None)
        title = (w.title if w else "") or ""
        ev.add("url", "", source="BROWSER")
        ev.add("title_only", title[:80], source="WIN32")
        needle = (exp.url_substr or "").lower()
        q = str(exp.params.get("query") or exp.text or "").lower()
        if needle and needle.replace(".com", "") in title.lower():
            # title-only → medium/low, not high SUCCESS for navigation certainty
            if exp.params.get("watch") and "youtube" in title.lower():
                return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "title suggests video; URL unknown", VerificationMethod.BROWSER_STATE.value
            return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "title-only match; URL unknown", VerificationMethod.BROWSER_STATE.value
        if not needle and not q:
            return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "browser state unknown", VerificationMethod.BROWSER_STATE.value
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no URL/title evidence", VerificationMethod.BROWSER_STATE.value

    ev.add("url", url[:120], source="BROWSER")
    ev.add("title", title[:80], source="BROWSER")
    needle = (exp.url_substr or "").lower()
    url_l = url.lower()
    if needle and needle in url_l:
        q = str(exp.params.get("query") or "").lower()
        if q and exp.params.get("prefer_results"):
            # search: results URL or query in URL
            q_token = q.replace(" ", "+")[:40]
            if "search" in url_l or "results" in url_l or q_token.lower() in url_l or q.split()[0] in url_l:
                return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "search URL consistent", VerificationMethod.BROWSER_STATE.value
            # youtube.com alone after search is weak
            return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "on youtube but search not confirmed", VerificationMethod.BROWSER_STATE.value
        if exp.params.get("watch") and "/watch" not in url_l:
            return VerificationOutcome.FAILURE, CONF_HIGH, ev, "not a watch URL", VerificationMethod.BROWSER_STATE.value
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "URL matches", VerificationMethod.BROWSER_STATE.value
    if needle and url:
        return VerificationOutcome.FAILURE, CONF_HIGH, ev, f"URL mismatch want~{needle}", VerificationMethod.BROWSER_STATE.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "URL evidence inconclusive", VerificationMethod.BROWSER_STATE.value


def _check_click_effect(exp, before, after, screen_diff, ev, revalidate_status) -> tuple:
    method = VerificationMethod.ELEMENT_REVALIDATE.value
    if revalidate_status:
        ev.add("revalidate", revalidate_status, source="semantic")
        rs = revalidate_status.upper()
        if rs in ("CHANGED", "MISSING"):
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, f"element {rs}", method
        if rs == "STILL_VALID":
            # still there — weak unless other evidence
            pass
        if rs == "UNCERTAIN":
            return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "revalidate uncertain", method

    changed = False
    score = 0.0
    if screen_diff is not None:
        changed = bool(getattr(screen_diff, "changed", False) or (screen_diff.get("changed") if isinstance(screen_diff, dict) else False))
        score = float(getattr(screen_diff, "change_score", 0) or (screen_diff.get("change_score") if isinstance(screen_diff, dict) else 0) or 0)
        ev.add("screen_changed", changed, source="screen_diff")
        ev.add("change_score", round(score, 3), source="screen_diff")

    # Unrelated tiny cursor flicker
    if changed and score < 0.08:
        ev.conflicts.append("trivial_pixel_change")
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "trivial screen change only", VerificationMethod.SCREEN_DIFF.value

    if changed and score >= 0.25:
        # Stronger but still not alone SUCCESS without expectation detail
        if exp.description and "click" in exp.description.lower():
            return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "screen changed; click effect not proven", VerificationMethod.SCREEN_DIFF.value
        return VerificationOutcome.UNCERTAIN, CONF_MEDIUM, ev, "screen changed; insufficient semantic proof", VerificationMethod.SCREEN_DIFF.value

    if not changed:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no observable state change after click", VerificationMethod.SCREEN_DIFF.value

    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "click effect unproven", method


def _check_element_gone(exp, world, ev, revalidate_status) -> tuple:
    if revalidate_status.upper() == "MISSING":
        ev.add("revalidate", "MISSING", source="semantic")
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "element disappeared", VerificationMethod.ELEMENT_REVALIDATE.value
    if exp.element_id and world is not None:
        els = getattr(_desktop(world), "visible_elements", None) or []
        ids = {getattr(e, "id", "") for e in els}
        if exp.element_id not in ids:
            return VerificationOutcome.SUCCESS, CONF_MEDIUM, ev, "element id absent", VerificationMethod.ELEMENT_REVALIDATE.value
        return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, "element still present", VerificationMethod.ELEMENT_REVALIDATE.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "cannot confirm disappearance", VerificationMethod.ELEMENT_REVALIDATE.value


def _check_element_exists(exp, world, ev) -> tuple:
    if not exp.element_id or world is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no element_id", VerificationMethod.ELEMENT_REVALIDATE.value
    els = getattr(_desktop(world), "visible_elements", None) or []
    for e in els:
        if getattr(e, "id", "") == exp.element_id:
            ev.add("element_id", exp.element_id[:48], source="world")
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "element exists", VerificationMethod.ELEMENT_REVALIDATE.value
    return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, "element not found", VerificationMethod.ELEMENT_REVALIDATE.value


def _check_type(exp, world, ev) -> tuple:
    if exp.sensitive:
        ev.add("sensitive", True, source="policy")
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "sensitive field — value not verified", VerificationMethod.ELEMENT_REVALIDATE.value
    want = (exp.text or "").strip()
    if not want:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no expected text", VerificationMethod.ELEMENT_REVALIDATE.value
    desktop = _desktop(world)
    if desktop is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no world", VerificationMethod.ELEMENT_REVALIDATE.value
    # Look at focused / matching element text — never log full secrets (already gated)
    for e in list(getattr(desktop, "visible_elements", None) or [])[:40]:
        if exp.element_id and getattr(e, "id", "") != exp.element_id:
            continue
        val = (getattr(e, "value", None) or getattr(e, "text", None) or getattr(e, "name", None) or "")
        if want.lower() in str(val).lower():
            ev.add("field_match", True, source="UIA")
            return VerificationOutcome.SUCCESS, CONF_HIGH, ev, "field contains text", VerificationMethod.ELEMENT_REVALIDATE.value
        if exp.element_id and getattr(e, "id", "") == exp.element_id:
            ev.add("field_match", False, source="UIA")
            return VerificationOutcome.FAILURE, CONF_HIGH, ev, "field text mismatch", VerificationMethod.ELEMENT_REVALIDATE.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "typed value not observable", VerificationMethod.ELEMENT_REVALIDATE.value


def _check_screen_changed(exp, screen_diff, ev) -> tuple:
    if screen_diff is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no screen diff", VerificationMethod.SCREEN_DIFF.value
    changed = bool(getattr(screen_diff, "changed", False) or (screen_diff.get("changed") if isinstance(screen_diff, dict) else False))
    score = float(getattr(screen_diff, "change_score", 0) or (screen_diff.get("change_score") if isinstance(screen_diff, dict) else 0) or 0)
    ev.add("changed", changed, source="screen_diff")
    ev.add("score", round(score, 3), source="screen_diff")
    if exp.params.get("weak"):
        # Screen change alone is never SUCCESS
        if not changed:
            return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no change; effect unproven", VerificationMethod.SCREEN_DIFF.value
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "screen changed but expectation weak", VerificationMethod.SCREEN_DIFF.value
    if changed and score >= 0.35:
        return VerificationOutcome.SUCCESS, min(CONF_MEDIUM, score), ev, "significant screen change", VerificationMethod.SCREEN_DIFF.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "insufficient screen evidence", VerificationMethod.SCREEN_DIFF.value


def _check_media_state(exp, world, ev) -> tuple:
    desktop = _desktop(world)
    br = getattr(desktop, "browser", None) if desktop else None
    if br is None:
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no browser state", VerificationMethod.BROWSER_STATE.value
    state = (br.media_state or "").lower()
    ev.add("media_state", state or "unknown", source="BROWSER")
    want = (exp.media_want or "").lower()
    if not state or state == "unknown":
        return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "media state UNKNOWN", VerificationMethod.BROWSER_STATE.value
    if want and want in state:
        return VerificationOutcome.SUCCESS, CONF_HIGH, ev, f"media {state}", VerificationMethod.BROWSER_STATE.value
    if want:
        return VerificationOutcome.FAILURE, CONF_MEDIUM, ev, f"media {state} want {want}", VerificationMethod.BROWSER_STATE.value
    return VerificationOutcome.UNCERTAIN, CONF_LOW, ev, "no media want specified", VerificationMethod.BROWSER_STATE.value


def finalize_status(
    status: VerificationOutcome,
    confidence: float,
) -> VerificationOutcome:
    """Enforce: SUCCESS requires confidence >= CONF_SUCCESS_MIN."""
    if status is VerificationOutcome.SUCCESS and confidence < CONF_SUCCESS_MIN:
        return VerificationOutcome.UNCERTAIN
    return status


__all__ = ["check_expectation", "finalize_status"]
