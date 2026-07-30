"""Phase 4 browser agent tests — DOM ranking, registry, mocked ops."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_rank_searchbox():
    from neuron.browser.dom import DomElement, rank_elements

    els = [
        DomElement(index=0, tag="a", role="link", name="Home", href="https://x/"),
        DomElement(index=1, tag="input", role="searchbox", name="Search", placeholder="Search", input_type="search"),
        DomElement(index=2, tag="button", role="button", name="Menu"),
    ]
    ranked = rank_elements(els, "search", prefer="search", limit=3)
    assert ranked
    assert ranked[0].tag == "input"
    print("OK rank searchbox", ranked[0].name, ranked[0].score)


def test_rank_result_links():
    from neuron.browser.dom import DomElement, rank_elements

    els = [
        DomElement(index=0, tag="a", role="link", name="Sign in", href="https://accounts.google.com/"),
        DomElement(index=1, tag="a", role="link", name="RTX 5090 review", href="https://example.com/rtx"),
        DomElement(index=2, tag="button", role="button", name="Tools"),
    ]
    ranked = rank_elements(els, "RTX 5090", prefer="result", limit=5)
    assert ranked
    assert "rtx" in (ranked[0].href + ranked[0].name).lower()
    print("OK rank results", ranked[0].name)


def test_registry_phase4_tools():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    needed = [
        "browser_open", "browser_navigate", "browser_search",
        "browser_get_page", "browser_get_elements", "browser_find_element",
        "browser_click", "browser_type", "browser_scroll",
        "browser_back", "browser_forward",
        "browser_get_tabs", "browser_switch_tab", "browser_close_tab",
        "browser_research",
    ]
    names = set(tool_registry.names())
    missing = [n for n in needed if n not in names]
    assert not missing, missing
    print("OK registry phase4", len(needed))


def test_browser_search_mocked():
    from neuron.browser import agent
    from neuron.browser import ops

    fake = {
        "ok": True,
        "method": "search-url",
        "site": "youtube",
        "query": "Unreal Engine tutorials",
        "url": "https://www.youtube.com/results?search_query=Unreal",
        "title": "Unreal - YouTube",
        "results": [
            {"title": "UE5 Beginner", "url": "https://www.youtube.com/watch?v=aaa", "index": 0},
            {"title": "UE5 Materials", "url": "https://www.youtube.com/watch?v=bbb", "index": 1},
        ],
    }
    with mock.patch.object(agent, "_submit", return_value=fake):
        r = agent.browser_search({"site": "youtube", "query": "Unreal Engine tutorials"})
    assert r.success
    assert r.state["results"]
    assert "youtube" in r.message.lower() or "Searched" in r.message
    print("OK browser_search mock", r.message[:80])


def test_browser_click_then_verify_state():
    from neuron.browser import agent

    fake = {
        "ok": True,
        "how": "role",
        "element": {"name": "UE5 Beginner", "href": "https://www.youtube.com/watch?v=aaa"},
        "before_url": "https://www.youtube.com/results",
        "url": "https://www.youtube.com/watch?v=aaa",
        "title": "UE5 Beginner - YouTube",
    }
    with mock.patch.object(agent, "_submit", return_value=fake):
        r = agent.browser_click({"name": "UE5 Beginner"})
    assert r.success
    assert "watch" in (r.state.get("url") or "")
    print("OK browser_click mock", r.method)


def test_browser_research_sources():
    from neuron.browser import agent
    from neuron.windows.result import ok

    search_state = {
        "results": [
            {"title": "Bench A", "url": "https://example.com/a"},
            {"title": "Bench B", "url": "https://example.com/b"},
        ],
        "query": "RTX 5090 benchmarks",
        "site": "google",
    }
    with mock.patch.object(
        agent, "browser_search", return_value=ok("searched", state=search_state, method="mock")
    ), mock.patch.object(
        agent, "browser_navigate", return_value=ok("nav", state={"url": "https://example.com/a"})
    ), mock.patch.object(
        agent,
        "browser_get_page",
        return_value=ok(
            "page",
            state={"url": "https://example.com/a", "title": "Bench A", "text": "The RTX 5090 scores high.", "links": []},
        ),
    ), mock.patch("brain_llm.is_enabled", return_value=False):
        r = agent.browser_research({"query": "RTX 5090 benchmarks", "site": "google", "max_pages": 1})
    assert r.success
    assert r.state.get("sources")
    print("OK browser_research sources", r.state["sources"][:2])


if __name__ == "__main__":
    test_rank_searchbox()
    test_rank_result_links()
    test_registry_phase4_tools()
    test_browser_search_mocked()
    test_browser_click_then_verify_state()
    test_browser_research_sources()
    print("\n=== Phase 4 browser tests passed ===")
