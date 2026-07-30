"""Phase 4 browser agent — public tools returning ToolResult."""

from __future__ import annotations

from typing import Any

from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[browser-agent] {msg}", flush=True)


def _submit(op, *args, timeout: int = 90):
    import browser as br
    if not br.supported():
        raise RuntimeError("Playwright browser control isn't available.")
    return br._get().submit(op, *args, timeout=timeout)


def browser_open(args: dict | None = None) -> ToolResult:
    args = args or {}
    site = (args.get("site") or args.get("url") or args.get("name") or "").strip()
    if not site:
        return fail("Need a site or URL.")
    try:
        from neuron.browser import ops
        data = _submit(ops.op_open, site)
        return ok(
            f"Opened {data.get('title') or site}.",
            state=data,
            method="playwright",
        )
    except Exception as exc:
        # Fall back to existing brain/_web_open path
        try:
            import brain
            msg = brain._web_open(site, args.get("browser", "") or "")
            return ok(str(msg), state={"site": site, "fallback": "brain._web_open"}, method="playwright-legacy")
        except Exception as exc2:
            return fail(f"browser_open failed: {exc2 or exc}")


def browser_navigate(args: dict | None = None) -> ToolResult:
    args = args or {}
    url = (args.get("url") or args.get("site") or args.get("to") or "").strip()
    if not url:
        return fail("Need a URL.")
    try:
        from neuron.browser import ops
        data = _submit(ops.op_navigate, url)
        return ok(f"Navigated to {data.get('url')}.", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_search(args: dict | None = None) -> ToolResult:
    args = args or {}
    site = (args.get("site") or "google").strip() or "google"
    query = (args.get("query") or args.get("q") or args.get("text") or "").strip()
    if not query:
        return fail("Need a search query.")
    try:
        from neuron.browser import ops
        data = _submit(ops.op_search, site, query, timeout=100)
        results = data.get("results") or []
        preview = "; ".join(
            (r.get("title") or r.get("url") or "")[:50] for r in results[:4]
        )
        msg = f"Searched {site} for '{query}'."
        if preview:
            msg += f" Top: {preview}"
        return ok(msg, state=data, method=data.get("method") or "playwright")
    except Exception as exc:
        # Legacy site search fallback
        try:
            import brain
            msg = brain._web_search(site, query, args.get("browser", "") or "")
            return ok(str(msg), state={"site": site, "query": query, "fallback": True}, method="legacy-search")
        except Exception as exc2:
            return fail(str(exc2 or exc))


def browser_get_page(args: dict | None = None) -> ToolResult:
    try:
        from neuron.browser import ops
        data = _submit(ops.op_get_page)
        title = data.get("title") or ""
        url = data.get("url") or ""
        text = (data.get("text") or "")[:500]
        links = data.get("links") or []
        msg = f"Page: {title} | {url}"
        if text:
            msg += f" | {text[:180]}…"
        return ok(
            msg,
            state={
                "title": title,
                "url": url,
                "text": (data.get("text") or "")[:6000],
                "links": links,
                "sources": [L.get("url") for L in links if L.get("url")],
            },
            method="playwright-dom",
        )
    except Exception as exc:
        return fail(str(exc))


def browser_get_elements(args: dict | None = None) -> ToolResult:
    args = args or {}
    try:
        from neuron.browser import ops
        data = _submit(ops.op_get_elements, int(args.get("limit") or 80))
        els = data.get("elements") or []
        labels = [e.get("name") or e.get("text") or e.get("tag") for e in els[:15]]
        msg = f"{len(els)} elements on {data.get('title') or data.get('url')}: " + ", ".join(
            str(x)[:40] for x in labels if x
        )
        return ok(msg, state=data, method="playwright-dom")
    except Exception as exc:
        return fail(str(exc))


def browser_find_element(args: dict | None = None) -> ToolResult:
    args = args or {}
    query = (args.get("name") or args.get("query") or args.get("text") or "").strip()
    if not query:
        return fail("Need an element query.")
    try:
        from neuron.browser import ops
        data = _submit(
            ops.op_find_element,
            query,
            args.get("role") or args.get("control_type") or "",
            args.get("prefer") or "click",
            int(args.get("top") or 8),
        )
        best = data.get("best")
        if not best:
            return fail(f"Not found: {query}", state=data, method="playwright-dom")
        msg = (
            f"Found '{best.get('name') or best.get('text')}' "
            f"({best.get('role') or best.get('tag')}) score={best.get('score', 0):.0f}"
        )
        return ok(msg, state=data, method="playwright-dom")
    except Exception as exc:
        return fail(str(exc))


def browser_click(args: dict | None = None) -> ToolResult:
    args = args or {}
    query = (args.get("name") or args.get("text") or args.get("query") or "").strip()
    index = args.get("index")
    if index is not None and index != "":
        try:
            index = int(index)
        except Exception:
            index = None
    else:
        index = None
    if not query and index is None:
        return fail("Need element name or index.")
    try:
        from neuron.browser import ops
        data = _submit(
            ops.op_click,
            query,
            index,
            args.get("role") or "",
            args.get("prefer") or "click",
        )
        el = data.get("element") or {}
        label = el.get("name") or el.get("text") or query or f"#{index}"
        verified = bool(data.get("url"))
        return ok(
            f"Clicked '{label}'.",
            state={**data, "verified": verified},
            method=f"playwright:{data.get('how')}",
        )
    except Exception as exc:
        # Soft fallback to legacy click_text
        if query:
            try:
                import browser as br
                msg = br.click_text(query)
                return ok(str(msg), state={"fallback": "click_text"}, method="playwright-legacy")
            except Exception:
                pass
        return fail(str(exc))


def browser_type(args: dict | None = None) -> ToolResult:
    args = args or {}
    text = args.get("text") or args.get("value") or ""
    if not text:
        return fail("Need text to type.")
    try:
        from neuron.browser import ops
        data = _submit(
            ops.op_type,
            str(text),
            args.get("into") or args.get("name") or args.get("query") or "",
            bool(args.get("submit") or args.get("enter")),
            bool(args.get("clear", True)),
        )
        return ok(
            f"Typed into page{' and submitted' if data.get('submitted') else ''}.",
            state=data,
            method=f"playwright:{data.get('how')}",
        )
    except Exception as exc:
        return fail(str(exc))


def browser_scroll(args: dict | None = None) -> ToolResult:
    args = args or {}
    try:
        from neuron.browser import ops
        data = _submit(
            ops.op_scroll,
            args.get("direction") or "down",
            int(args.get("amount") or 900),
        )
        return ok(f"Scrolled {data.get('direction')}.", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_back(args: dict | None = None) -> ToolResult:
    try:
        from neuron.browser import ops
        data = _submit(ops.op_back)
        return ok(f"Back to {data.get('url')}.", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_forward(args: dict | None = None) -> ToolResult:
    try:
        from neuron.browser import ops
        data = _submit(ops.op_forward)
        return ok(f"Forward to {data.get('url')}.", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_get_tabs(args: dict | None = None) -> ToolResult:
    try:
        from neuron.browser import ops
        data = _submit(ops.op_get_tabs)
        tabs = data.get("tabs") or []
        bits = [f"#{t['index']} {(t.get('title') or t.get('url') or '')[:40]}" for t in tabs]
        return ok("Tabs: " + ("; ".join(bits) if bits else "none"), state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_switch_tab(args: dict | None = None) -> ToolResult:
    args = args or {}
    try:
        from neuron.browser import ops
        data = _submit(ops.op_switch_tab, int(args.get("index") or 0))
        return ok(f"Switched to tab {data.get('index')}: {data.get('title')}", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_close_tab(args: dict | None = None) -> ToolResult:
    args = args or {}
    idx = args.get("index")
    try:
        from neuron.browser import ops
        if idx is None or idx == "":
            data = _submit(ops.op_close_tab, None)
        else:
            data = _submit(ops.op_close_tab, int(idx))
        return ok(f"Closed tab. {data.get('remaining')} remaining.", state=data, method="playwright")
    except Exception as exc:
        return fail(str(exc))


def browser_research(args: dict | None = None) -> ToolResult:
    """Search (Playwright) → open useful results → extract text → summarize with Ollama.

    Sources kept in state['sources']. No paid search APIs.
    """
    args = args or {}
    query = (args.get("query") or args.get("q") or "").strip()
    site = (args.get("site") or "google").strip() or "google"
    if not query:
        return fail("Need a research query.")
    max_pages = int(args.get("max_pages") or 2)

    search = browser_search({"site": site, "query": query})
    if not search.success:
        # HTTP scrape fallback (still free)
        try:
            from neuron.tools import web_tools
            msg = web_tools.web_search_summarize({"query": query})
            return ok(str(msg), state={"fallback": "http-scrape", "query": query}, method="http+ollama")
        except Exception as exc:
            return fail(search.error or str(exc))

    results = (search.state or {}).get("results") or []
    sources: list[str] = []
    evidence: list[str] = []
    for r in results[:5]:
        if r.get("url"):
            sources.append(r["url"])
        evidence.append(f"- {r.get('title')}: {r.get('url')}")

    # Open top useful pages (skip pure search chrome)
    opened = []
    for r in results[:max_pages]:
        url = r.get("url") or ""
        if not url.startswith("http"):
            continue
        if any(x in url for x in ("google.com/search", "accounts.google", "youtube.com/results")):
            # For YT results page, extract from current page instead of opening
            continue
        nav = browser_navigate({"url": url})
        if not nav.success:
            continue
        page = browser_get_page({})
        if page.success:
            opened.append({
                "url": (page.state or {}).get("url"),
                "title": (page.state or {}).get("title"),
                "text": ((page.state or {}).get("text") or "")[:2500],
            })
            if (page.state or {}).get("url"):
                sources.append(page.state["url"])

    blob = "Search hits:\n" + "\n".join(evidence[:8])
    for p in opened:
        blob += f"\n\nPage: {p.get('title')} ({p.get('url')})\n{(p.get('text') or '')[:1800]}"
    blob = blob[:7000]

    summary = ""
    try:
        import brain_llm
        if brain_llm.is_enabled():
            import json
            import re
            raw = brain_llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            'Summarize findings for the user. JSON only: '
                            '{"say":"<clear summary under 120 words>","steps":[]}. '
                            "Mention key facts; do not invent."
                        ),
                    },
                    {"role": "user", "content": f"Query: {query}\nEvidence:\n{blob}"},
                ],
                timeout=45,
            )
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{.*\}", raw or "", re.S)
                data = json.loads(m.group(0)) if m else {"say": raw}
            summary = (data.get("say") or raw or "").strip()
    except Exception as exc:
        _log(f"summarize failed: {exc}")

    if not summary:
        summary = f"Findings for '{query}':\n" + "\n".join(evidence[:5])

    # Dedupe sources
    uniq = []
    seen = set()
    for s in sources:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)

    return ok(
        summary[:900],
        state={
            "query": query,
            "site": site,
            "search": search.state,
            "opened": opened,
            "sources": uniq,
            "evidence": evidence,
        },
        method="playwright+ollama",
    )
