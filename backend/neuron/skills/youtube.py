"""YouTube skill workflows."""

from __future__ import annotations

from neuron.skills._util import arg, as_result, handler
from neuron.windows.result import ToolResult, fail, ok


def search(query: str) -> ToolResult:
    """Search YouTube in the controlled browser."""
    q = (query or "").strip()
    if not q:
        return fail("Need a YouTube search query.")
    try:
        import browser
        if browser.supported():
            return as_result(browser.youtube_search(q), method="youtube")
    except Exception as exc:
        return fail(f"YouTube search failed: {exc}")
    try:
        import brain
        return as_result(brain._web_search("youtube", q), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def play_result(index: int = 1) -> ToolResult:
    """Play the Nth visible YouTube video on screen."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return fail("play_result needs an integer index (1-based).")
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.play_result(idx), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def home() -> ToolResult:
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.youtube_home(), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def play_by_title(title: str) -> ToolResult:
    t = (title or "").strip()
    if not t:
        return fail("Need a video title.")
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.play_by_title(t), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def list_videos() -> ToolResult:
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.list_visible_videos(), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def skip_ad() -> ToolResult:
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.skip_ad(), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def fullscreen(exit_fs: bool = False) -> ToolResult:
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.fullscreen(bool(exit_fs)), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def ensure_playback(want: str = "play") -> ToolResult:
    try:
        import browser
        if not browser.supported():
            return fail("Browser control isn't available.")
        return as_result(browser.ensure_playback(want or "play"), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def open_channel_videos(channel: str = "MrBeast") -> ToolResult:
    """Open an official channel Videos tab (@handle/videos)."""
    handle = (channel or "").strip().lstrip("@")
    if not handle:
        return fail("Need a channel name.")
    url = f"https://www.youtube.com/@{handle}/videos"
    try:
        import browser
        if browser.supported():
            return as_result(browser.open_site(url), method="youtube")
    except Exception as exc:
        return fail(str(exc))
    try:
        import brain
        return as_result(brain._web_open(url), method="youtube")
    except Exception as exc:
        return fail(str(exc))


def play_search(query: str, index: int = 1) -> ToolResult:
    """Workflow: search → play Nth result."""
    r = search(query)
    if not r.success:
        return r
    return play_result(index)


# --- Tool-registry handlers (dict args) ---

search_tool = handler(lambda a: search(str(arg(a, "query", "q", "search"))))
play_result_tool = handler(lambda a: play_result(int(arg(a, "index", "n", default=1) or 1)))
home_tool = handler(lambda a: home())
play_by_title_tool = handler(lambda a: play_by_title(str(arg(a, "title", "name", "query"))))
list_videos_tool = handler(lambda a: list_videos())
skip_ad_tool = handler(lambda a: skip_ad())
fullscreen_tool = handler(lambda a: fullscreen(bool(arg(a, "exit", "exit_fs", default=False))))
ensure_playback_tool = handler(lambda a: ensure_playback(str(arg(a, "want", default="play") or "play")))
open_channel_videos_tool = handler(lambda a: open_channel_videos(str(arg(a, "channel", "name", "handle", default="MrBeast"))))
play_search_tool = handler(
    lambda a: play_search(str(arg(a, "query", "q")), int(arg(a, "index", default=1) or 1))
)
