"""Spotify skill workflows."""

from __future__ import annotations

import time
import urllib.parse

from neuron.skills._util import arg, as_result, handler
from neuron.skills import windows as win_skill
from neuron.windows.result import ToolResult, fail, ok


def open() -> ToolResult:
    return win_skill.open_app("spotify")


def play(query: str = "") -> ToolResult:
    """Focus Spotify and play. If query given, open Spotify search first."""
    q = (query or "").strip()
    r = open()
    if not r.success:
        # Still try media key if Spotify might already be running silently
        pass
    time.sleep(0.6)
    if q:
        # Deep-link search (desktop protocol) then play
        uri = "spotify:search:" + urllib.parse.quote(q)
        try:
            import os
            os.startfile(uri)
            time.sleep(1.2)
        except Exception:
            try:
                import brain
                brain._web_open(f"https://open.spotify.com/search/{urllib.parse.quote(q)}")
                time.sleep(1.0)
            except Exception:
                pass
        # Press Enter on first result when possible
        try:
            import actions
            actions.press_keys("enter")
            time.sleep(0.4)
        except Exception:
            pass
    try:
        import actions
        return as_result(actions.media("play"), method="spotify")
    except Exception as exc:
        return fail(f"Spotify play failed: {exc}")


def pause() -> ToolResult:
    try:
        import actions
        return as_result(actions.media("pause"), method="spotify")
    except Exception as exc:
        return fail(str(exc))


def next_track() -> ToolResult:
    try:
        import actions
        return as_result(actions.media("next"), method="spotify")
    except Exception as exc:
        return fail(str(exc))


def previous() -> ToolResult:
    try:
        import actions
        return as_result(actions.media("previous"), method="spotify")
    except Exception as exc:
        return fail(str(exc))


def search(query: str) -> ToolResult:
    q = (query or "").strip()
    if not q:
        return fail("Need a Spotify search query.")
    open()
    time.sleep(0.5)
    uri = "spotify:search:" + urllib.parse.quote(q)
    try:
        import os
        os.startfile(uri)
        return ok(f"Searching Spotify for {q}.", method="spotify")
    except Exception as exc:
        return fail(str(exc))


open_tool = handler(lambda a: open())
play_tool = handler(lambda a: play(str(arg(a, "query", "q", "track", "song", default=""))))
pause_tool = handler(lambda a: pause())
next_tool = handler(lambda a: next_track())
previous_tool = handler(lambda a: previous())
search_tool = handler(lambda a: search(str(arg(a, "query", "q"))))
