"""Browser skill workflows (controlled Playwright Chrome)."""

from __future__ import annotations

from neuron.skills._util import arg, as_result, handler
from neuron.windows.result import ToolResult, fail


def open_tab(url: str = "about:blank") -> ToolResult:
    """Open / navigate the controlled browser to a URL (new session tab)."""
    u = (url or "").strip() or "about:blank"
    try:
        from neuron.tools import browser_tools
        return as_result(browser_tools.browser_open({"url": u}), method="browser")
    except Exception:
        pass
    try:
        import browser
        if browser.supported():
            if u.startswith("http") or u == "about:blank":
                return as_result(browser.open_site(u if u != "about:blank" else "https://www.google.com"), method="browser")
            import brain
            return as_result(brain._web_open(u), method="browser")
    except Exception as exc:
        return fail(str(exc))
    return fail("Browser control isn't available.")


def navigate(url: str) -> ToolResult:
    u = (url or "").strip()
    if not u:
        return fail("Need a URL.")
    try:
        from neuron.tools import browser_tools
        return as_result(browser_tools.browser_navigate({"url": u}), method="browser")
    except Exception:
        pass
    try:
        import browser
        if browser.supported():
            return as_result(browser.open_site(u if u.startswith("http") else f"https://{u}"), method="browser")
    except Exception as exc:
        return fail(str(exc))
    return fail("Browser control isn't available.")


def search(query: str, site: str = "") -> ToolResult:
    q = (query or "").strip()
    if not q:
        return fail("Need a search query.")
    site = (site or "").strip()
    try:
        from neuron.tools import browser_tools
        args = {"query": q}
        if site:
            args["site"] = site
        return as_result(browser_tools.browser_search(args), method="browser")
    except Exception:
        pass
    try:
        import brain
        if site:
            return as_result(brain._web_search(site, q), method="browser")
        return as_result(brain._web_search("google", q), method="browser")
    except Exception as exc:
        return fail(str(exc))


def close_tab() -> ToolResult:
    try:
        from neuron.tools import browser_tools
        return as_result(browser_tools.browser_close_tab({}), method="browser")
    except Exception as exc:
        return fail(str(exc))


def switch_tab(index: int = 0) -> ToolResult:
    try:
        from neuron.tools import browser_tools
        return as_result(browser_tools.browser_switch_tab({"index": int(index)}), method="browser")
    except Exception as exc:
        return fail(str(exc))


def get_tabs() -> ToolResult:
    try:
        from neuron.tools import browser_tools
        return as_result(browser_tools.browser_get_tabs({}), method="browser")
    except Exception as exc:
        return fail(str(exc))


open_tab_tool = handler(lambda a: open_tab(str(arg(a, "url", "site", "path", default="about:blank"))))
navigate_tool = handler(lambda a: navigate(str(arg(a, "url", "site"))))
search_tool = handler(lambda a: search(str(arg(a, "query", "q")), str(arg(a, "site", default=""))))
close_tab_tool = handler(lambda a: close_tab())
switch_tab_tool = handler(lambda a: switch_tab(int(arg(a, "index", "n", default=0) or 0)))
get_tabs_tool = handler(lambda a: get_tabs())
