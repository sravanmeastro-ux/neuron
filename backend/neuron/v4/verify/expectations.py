"""Derive typed VerificationExpectation from tools / GroundedAction / steps."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.verify.types import (
    ExpectationKind,
    VerificationExpectation,
    timeout_for,
)


def derive_expectation(
    tool: str,
    args: dict[str, Any] | None = None,
    *,
    expected_result: str = "",
    element_id: str = "",
    intent: str = "",
) -> VerificationExpectation:
    args = dict(args or {})
    tool_l = (tool or "").strip().lower()
    intent_l = (intent or "").strip().lower()
    app = str(args.get("name") or args.get("app") or args.get("title") or "").strip()
    mon = args.get("monitor")
    eid = element_id or str(args.get("element_id") or "")
    site = str(args.get("site") or "").lower()
    query = str(args.get("query") or "")
    url = str(args.get("url") or "")

    # Sensitive typing
    sensitive = bool(
        args.get("password")
        or args.get("secret")
        or "password" in tool_l
        or str(args.get("field") or "").lower() in ("password", "passwd")
    )

    if tool_l in ("open_app", "windows.open_app") or intent_l in ("open_app", "ensure_app"):
        return VerificationExpectation(
            kind=ExpectationKind.APP_OPEN,
            application=app,
            timeout_s=timeout_for(ExpectationKind.APP_OPEN, tool_l),
            description=expected_result or f"{app} window exists",
            params={"require_window": True},
        )

    if tool_l in ("focus_app", "windows.focus_app", "focus_window") or intent_l == "focus_app":
        return VerificationExpectation(
            kind=ExpectationKind.WINDOW_FOCUSED,
            application=app,
            timeout_s=timeout_for(ExpectationKind.WINDOW_FOCUSED, tool_l),
            description=expected_result or f"{app} focused",
        )

    if (
        tool_l in ("move_window_to_monitor", "windows.move_to_monitor", "move_window")
        or intent_l in ("move_monitor", "place_monitor")
    ):
        return VerificationExpectation(
            kind=ExpectationKind.WINDOW_ON_MONITOR,
            application=app,
            monitor=mon,
            timeout_s=timeout_for(ExpectationKind.WINDOW_ON_MONITOR, tool_l),
            description=expected_result or f"{app} on monitor {mon}",
        )

    if tool_l in ("close_app", "windows.close_app"):
        return VerificationExpectation(
            kind=ExpectationKind.WINDOW_EXISTS,
            application=app,
            timeout_s=timeout_for("default", tool_l),
            description=expected_result or f"{app} closed",
            params={"want_absent": True},
        )

    if "fullscreen" in tool_l or intent_l == "youtube_fullscreen":
        return VerificationExpectation(
            kind=ExpectationKind.MEDIA_FULLSCREEN,
            application=app or "Chrome",
            timeout_s=timeout_for(ExpectationKind.MEDIA_FULLSCREEN, tool_l),
            description=expected_result or "media fullscreen",
            params={"exit": bool(args.get("exit"))},
        )

    if tool_l in ("youtube.search",) or (
        tool_l in ("browser_search", "search_site") and site == "youtube"
    ) or intent_l == "youtube_search":
        q = query or str(args.get("q") or "")
        return VerificationExpectation(
            kind=ExpectationKind.URL_MATCH,
            url_substr="youtube.com",
            text=q,
            timeout_s=timeout_for(ExpectationKind.URL_MATCH, tool_l),
            description=expected_result or f"youtube search {q}",
            params={"query": q, "prefer_results": True},
        )

    if tool_l in ("youtube.play_result", "play_result") or intent_l == "youtube_play":
        return VerificationExpectation(
            kind=ExpectationKind.URL_MATCH,
            url_substr="youtube.com/watch",
            timeout_s=timeout_for(ExpectationKind.URL_MATCH, tool_l),
            description=expected_result or "video playing / watch URL",
            params={"watch": True},
        )

    if tool_l in ("youtube.home", "youtube_home", "open_website") or intent_l in (
        "ensure_youtube",
        "youtube_home",
    ):
        return VerificationExpectation(
            kind=ExpectationKind.URL_MATCH,
            url_substr="youtube.com",
            application=app or "Chrome",
            timeout_s=timeout_for(ExpectationKind.URL_MATCH, tool_l),
            description=expected_result or "YouTube loaded",
        )

    if tool_l in ("browser_navigate", "open_url") or url:
        return VerificationExpectation(
            kind=ExpectationKind.URL_MATCH,
            url_substr=_url_hint(url or str(args.get("site") or "")),
            timeout_s=timeout_for(ExpectationKind.URL_MATCH, tool_l),
            description=expected_result or f"navigated to {url or site}",
        )

    if eid or tool_l in ("click", "uia_click", "browser_click", "click_text", "click_element"):
        return VerificationExpectation(
            kind=ExpectationKind.ELEMENT_STATE_CHANGED,
            element_id=eid,
            timeout_s=timeout_for(ExpectationKind.ELEMENT_STATE_CHANGED, tool_l),
            description=expected_result or "click effect",
            params={"reference": str(args.get("reference") or args.get("text") or "")},
        )

    if tool_l in ("type_text", "uia_type", "browser_type", "type"):
        return VerificationExpectation(
            kind=ExpectationKind.TEXT_IN_FIELD,
            text=str(args.get("text") or args.get("value") or ""),
            element_id=eid,
            sensitive=sensitive,
            timeout_s=timeout_for(ExpectationKind.TEXT_IN_FIELD, tool_l),
            description=expected_result or ("typed (sensitive)" if sensitive else "text entered"),
        )

    if tool_l == "volume" or intent_l in ("mute", "volume"):
        # System volume rarely observable in world model
        return VerificationExpectation(
            kind=ExpectationKind.NONE,
            timeout_s=0.5,
            description=expected_result or "volume change (not world-observable)",
            params={"not_observable": True, "action": args.get("action")},
        )

    # Fallback: parse expected_result prose lightly into kind hints
    er = (expected_result or "").lower()
    if "monitor" in er and app:
        return VerificationExpectation(
            kind=ExpectationKind.WINDOW_ON_MONITOR,
            application=app,
            monitor=_extract_monitor(er) or mon,
            description=expected_result,
        )
    if app and ("window" in er or "running" in er or "open" in er):
        return VerificationExpectation(
            kind=ExpectationKind.APP_OPEN,
            application=app,
            description=expected_result,
        )

    return VerificationExpectation(
        kind=ExpectationKind.SCREEN_CHANGED,
        description=expected_result or f"{tool} effect",
        timeout_s=timeout_for(ExpectationKind.SCREEN_CHANGED, tool_l),
        params={"weak": True},
    )


def from_grounded_action(ga) -> VerificationExpectation:
    return derive_expectation(
        getattr(ga, "tool", "") or "",
        getattr(ga, "arguments", None) or {},
        expected_result=getattr(ga, "expected_result", "") or "",
        element_id=getattr(ga, "element_id", "") or "",
        intent="",
    )


def from_step(step: dict[str, Any] | None) -> VerificationExpectation:
    step = step or {}
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    return derive_expectation(
        str(step.get("action") or step.get("tool") or ""),
        args,
        expected_result=str(step.get("expected_result") or ""),
        element_id=str(args.get("element_id") or step.get("element_id") or ""),
    )


def _url_hint(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if "youtube" in s or s == "yt":
        return "youtube.com"
    s = re.sub(r"^https?://", "", s)
    return s[:80]


def _extract_monitor(text: str) -> Any:
    m = re.search(r"monitor\s*(\d+)", text or "")
    if m:
        return int(m.group(1))
    return None


__all__ = ["derive_expectation", "from_grounded_action", "from_step"]
