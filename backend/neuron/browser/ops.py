"""Playwright worker-thread operations for Phase 4 (generic DOM browser)."""

from __future__ import annotations

import time
from typing import Any

from neuron.browser.dom import COLLECT_ELEMENTS_JS, EXTRACT_TEXT_JS, elements_from_payload, rank_elements


def _page(w):
    import browser as br
    return br._active_page(w)


def _dismiss(page):
    import browser as br
    br._dismiss_noise(page)


def _resolve_url(site_or_url: str) -> str:
    raw = (site_or_url or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    try:
        import actions
        return actions._resolve_site_url(raw)
    except Exception:
        if "." in raw and " " not in raw:
            return "https://" + raw
        return "https://www.google.com/search?q=" + raw.replace(" ", "+")


def op_navigate(w, url: str) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    target = _resolve_url(url)
    if not target:
        raise RuntimeError("Need a URL or site name.")
    page.goto(target, wait_until="domcontentloaded", timeout=45000)
    time.sleep(0.5)
    _dismiss(page)
    return {"url": page.url, "title": page.title() or "", "ok": True}


def op_open(w, site: str) -> dict[str, Any]:
    return op_navigate(w, site)


def op_get_elements(w, limit: int = 80) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    _dismiss(page)
    data = page.evaluate(COLLECT_ELEMENTS_JS) or {}
    els = (data.get("elements") or [])[: int(limit)]
    data["elements"] = els
    # Prefer accessibility snapshot names when available
    try:
        snap = page.accessibility.snapshot()
        data["a11y_name"] = (snap or {}).get("name") if isinstance(snap, dict) else None
    except Exception:
        data["a11y_name"] = None
    return data


def op_get_page(w) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    data = page.evaluate(EXTRACT_TEXT_JS) or {}
    data["url"] = data.get("url") or page.url
    data["title"] = data.get("title") or page.title() or ""
    return data


def op_find_element(w, query: str, role: str = "", prefer: str = "", top: int = 8) -> dict[str, Any]:
    data = op_get_elements(w, limit=120)
    els = elements_from_payload(data)
    ranked = rank_elements(els, query, role=role or None, prefer=prefer or None, limit=top)
    return {
        "url": data.get("url"),
        "title": data.get("title"),
        "query": query,
        "candidates": [e.to_dict() for e in ranked],
        "best": ranked[0].to_dict() if ranked else None,
    }


def _click_candidate(page, el: dict) -> str:
    name = (el.get("name") or el.get("text") or el.get("aria_label") or "").strip()
    role = (el.get("role") or "").strip()
    selector = (el.get("selector") or "").strip()
    href = (el.get("href") or "").strip()

    # 1) role + name
    if name and role in ("button", "link", "tab", "menuitem", "searchbox", "textbox"):
        try:
            page.get_by_role(role, name=name).first.click(timeout=5000)
            return "role"
        except Exception:
            pass
    if name:
        try:
            page.get_by_role("button", name=name).first.click(timeout=4000)
            return "button"
        except Exception:
            pass
        try:
            page.get_by_role("link", name=name).first.click(timeout=4000)
            return "link"
        except Exception:
            pass
        try:
            page.get_by_text(name, exact=False).first.click(timeout=4000)
            return "text"
        except Exception:
            pass
    if selector:
        try:
            page.locator(selector).first.click(timeout=5000)
            return "selector"
        except Exception:
            pass
    if href:
        try:
            page.locator(f'a[href="{href}"]').first.click(timeout=4000)
            return "href"
        except Exception:
            try:
                page.locator(f'a[href*="{href.split("?")[0][-60:]}"]').first.click(timeout=4000)
                return "href-partial"
            except Exception:
                pass
    # 2) coordinate within page (still DOM-derived, not OS vision)
    x, y = int(el.get("x") or 0), int(el.get("y") or 0)
    if x and y:
        page.mouse.click(x, y)
        return "bbox"
    raise RuntimeError(f"Couldn't click element '{name or selector or href}'")


def op_click(w, query: str = "", index: int | None = None, role: str = "", prefer: str = "click") -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    _dismiss(page)
    before = page.url
    el = None
    if index is not None:
        data = op_get_elements(w, limit=120)
        els = data.get("elements") or []
        for e in els:
            if int(e.get("index") or -1) == int(index):
                el = e
                break
        if el is None and 0 <= int(index) < len(els):
            el = els[int(index)]
    else:
        found = op_find_element(w, query, role=role, prefer=prefer or "click", top=8)
        el = found.get("best")
        if not el:
            raise RuntimeError(f"No element matching '{query}'")
    how = _click_candidate(page, el)
    time.sleep(0.6)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    return {
        "ok": True,
        "how": how,
        "element": el,
        "before_url": before,
        "url": page.url,
        "title": page.title() or "",
    }


def op_type(w, text: str, query: str = "", submit: bool = False, clear: bool = True) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    _dismiss(page)
    target = None
    if query:
        found = op_find_element(w, query, prefer="type", top=5)
        target = found.get("best")
    if not target:
        found = op_find_element(w, "search", prefer="search", top=5)
        target = found.get("best")
    if not target:
        # focused element fallback
        page.keyboard.type(text, delay=20)
        if submit:
            page.keyboard.press("Enter")
        return {"ok": True, "how": "keyboard", "text": text, "url": page.url}

    # Focus via role/selector then fill
    name = (target.get("name") or target.get("placeholder") or "").strip()
    selector = (target.get("selector") or "").strip()
    filled = False
    if name:
        for role in ("searchbox", "textbox", "combobox"):
            try:
                loc = page.get_by_role(role, name=name).first
                if clear:
                    loc.fill(text, timeout=5000)
                else:
                    loc.click(timeout=3000)
                    page.keyboard.type(text, delay=15)
                filled = True
                break
            except Exception:
                continue
    if not filled and selector:
        try:
            loc = page.locator(selector).first
            if clear:
                loc.fill(text, timeout=5000)
            else:
                loc.click()
                page.keyboard.type(text, delay=15)
            filled = True
        except Exception:
            pass
    if not filled:
        try:
            page.locator("input[type='search'], input[name='q'], input[name='search_query']").first.fill(text, timeout=4000)
            filled = True
        except Exception:
            page.keyboard.type(text, delay=15)
    if submit:
        page.keyboard.press("Enter")
        time.sleep(0.8)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
    return {
        "ok": True,
        "how": "dom-fill" if filled else "keyboard",
        "element": target,
        "text": text,
        "submitted": bool(submit),
        "url": page.url,
        "title": page.title() or "",
    }


def op_search(w, site: str, query: str) -> dict[str, Any]:
    """Generic site search: navigate if needed → find search box → type → submit → list results."""
    page = _page(w)
    page.bring_to_front()
    site = (site or "google").strip() or "google"
    query = (query or "").strip()
    if not query:
        raise RuntimeError("Need a search query.")

    # Navigate to site home / search landing
    want = _resolve_url(site)
    cur = (page.url or "").lower()
    domain = want.split("//", 1)[-1].split("/", 1)[0].lower().replace("www.", "")
    if domain and domain not in cur.replace("www.", ""):
        page.goto(want, wait_until="domcontentloaded", timeout=45000)
        time.sleep(0.6)
    _dismiss(page)

    # Prefer known search URL templates when available (still generic)
    try:
        import actions
        key = site.lower().strip()
        tmpl = (getattr(actions, "SITE_SEARCH", {}) or {}).get(key)
        if tmpl:
            url = tmpl.format(q=__import__("urllib.parse").parse.quote(query))
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(0.7)
            _dismiss(page)
            results = _result_links(page)
            return {
                "ok": True,
                "method": "search-url",
                "site": site,
                "query": query,
                "url": page.url,
                "title": page.title() or "",
                "results": results,
            }
    except Exception:
        pass

    typed = op_type(w, query, query="search", submit=True, clear=True)
    time.sleep(0.5)
    results = _result_links(page)
    return {
        "ok": True,
        "method": "dom-search",
        "site": site,
        "query": query,
        "url": page.url,
        "title": page.title() or "",
        "typed": typed,
        "results": results,
    }


def _result_links(page, limit: int = 12) -> list[dict]:
    data = page.evaluate(COLLECT_ELEMENTS_JS) or {}
    els = elements_from_payload(data)
    ranked = rank_elements(els, "", prefer="result", limit=40)
    # If empty query ranking is weak, take anchors with http hrefs
    out = []
    seen = set()
    for e in ranked + els:
        href = (e.href or "").strip()
        title = (e.label or e.text or "").strip()
        if not href.startswith("http"):
            continue
        # skip pure navigational chrome
        low = (title + " " + href).lower()
        if any(x in low for x in ("sign in", "login", "privacy", "terms", "javascript:")):
            continue
        key = href.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title[:140], "url": href[:400], "score": e.score, "index": e.index})
        if len(out) >= limit:
            break
    return out


def op_scroll(w, direction: str = "down", amount: int = 900) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    direction = (direction or "down").lower()
    delta = abs(int(amount))
    if direction == "up":
        page.mouse.wheel(0, -delta)
    elif direction == "left":
        page.mouse.wheel(-delta, 0)
    elif direction == "right":
        page.mouse.wheel(delta, 0)
    else:
        page.mouse.wheel(0, delta)
    time.sleep(0.25)
    return {"ok": True, "direction": direction, "url": page.url}


def op_back(w) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    page.go_back(wait_until="domcontentloaded", timeout=15000)
    time.sleep(0.3)
    return {"ok": True, "url": page.url, "title": page.title() or ""}


def op_forward(w) -> dict[str, Any]:
    page = _page(w)
    page.bring_to_front()
    page.go_forward(wait_until="domcontentloaded", timeout=15000)
    time.sleep(0.3)
    return {"ok": True, "url": page.url, "title": page.title() or ""}


def op_get_tabs(w) -> dict[str, Any]:
    page = _page(w)
    tabs = []
    active_url = page.url
    for i, p in enumerate(w._ctx.pages):
        try:
            tabs.append({
                "index": i,
                "url": p.url,
                "title": (p.title() or "")[:120],
                "active": p.url == active_url and p is page,
            })
        except Exception:
            tabs.append({"index": i, "url": "", "title": "(unavailable)", "active": False})
    # Mark last active page
    try:
        for t in tabs:
            if w._page and t["index"] < len(w._ctx.pages) and w._ctx.pages[t["index"]] is w._page:
                t["active"] = True
    except Exception:
        pass
    return {"tabs": tabs, "count": len(tabs)}


def op_switch_tab(w, index: int = 0) -> dict[str, Any]:
    pages = list(w._ctx.pages)
    if not pages:
        raise RuntimeError("No tabs open.")
    i = int(index)
    if i < 0 or i >= len(pages):
        raise RuntimeError(f"Tab index {i} out of range (0-{len(pages)-1}).")
    w._page = pages[i]
    w._page.bring_to_front()
    return {"ok": True, "index": i, "url": w._page.url, "title": w._page.title() or ""}


def op_close_tab(w, index: int | None = None) -> dict[str, Any]:
    pages = list(w._ctx.pages)
    if not pages:
        raise RuntimeError("No tabs open.")
    if index is None:
        page = _page(w)
        page.close()
    else:
        i = int(index)
        if i < 0 or i >= len(pages):
            raise RuntimeError(f"Tab index {i} out of range.")
        pages[i].close()
    time.sleep(0.2)
    pages = list(w._ctx.pages)
    if pages:
        w._page = pages[-1]
        try:
            w._page.bring_to_front()
        except Exception:
            pass
        return {"ok": True, "remaining": len(pages), "url": w._page.url}
    # Recreate a blank tab so context stays usable
    w._page = w._ctx.new_page()
    return {"ok": True, "remaining": 1, "url": w._page.url}
