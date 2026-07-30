"""DOM / accessibility element model for Phase 4 browser control."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class DomElement:
    index: int = 0
    tag: str = ""
    role: str = ""
    name: str = ""
    text: str = ""
    placeholder: str = ""
    aria_label: str = ""
    href: str = ""
    input_type: str = ""
    selector: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def label(self) -> str:
        return (self.name or self.aria_label or self.placeholder or self.text or "").strip()


# JS collected in-page — interactive + labeled nodes
COLLECT_ELEMENTS_JS = """
() => {
  const out = [];
  const seen = new Set();
  const push = (el, roleHint) => {
    try {
      const r = el.getBoundingClientRect();
      if (r.width < 2 && r.height < 2) return;
      const style = window.getComputedStyle(el);
      if (style && (style.visibility === 'hidden' || style.display === 'none')) return;
      const tag = (el.tagName || '').toLowerCase();
      const role = (el.getAttribute('role') || roleHint || '').toLowerCase();
      const aria = (el.getAttribute('aria-label') || '').trim();
      const placeholder = (el.getAttribute('placeholder') || '').trim();
      const title = (el.getAttribute('title') || '').trim();
      const nameAttr = (el.getAttribute('name') || '').trim();
      const id = (el.id || '').trim();
      let text = '';
      try { text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(); } catch(e) {}
      text = text.slice(0, 120);
      const href = (el.href || el.getAttribute('href') || '').toString().slice(0, 300);
      const inputType = (el.getAttribute('type') || '').toLowerCase();
      const name = (aria || title || placeholder || nameAttr || text || id || '').slice(0, 120);
      const key = [tag, role, name.slice(0,40), Math.round(r.x/8), Math.round(r.y/8)].join('|');
      if (seen.has(key)) return;
      seen.add(key);

      let selector = '';
      try {
        if (id && /^[A-Za-z][\\w\\-:.]*$/.test(id)) {
          const esc = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/[^a-zA-Z0-9_\\-:]/g, '\\\\$&');
          selector = '#' + esc;
        } else if (aria) selector = `[aria-label="${aria.replace(/"/g, '\\\\"').slice(0,80)}"]`;
        else if (placeholder) selector = `${tag}[placeholder="${placeholder.replace(/"/g, '\\\\"').slice(0,60)}"]`;
        else if (href && href.startsWith('http')) {
          const short = href.split('?')[0].slice(-80);
          selector = `a[href*="${short.replace(/"/g, '')}"]`;
        }
      } catch (e) { selector = ''; }

      out.push({
        index: out.length,
        tag, role, name, text, placeholder,
        aria_label: aria,
        href, input_type: inputType, selector,
        x: Math.round(r.x + r.width/2),
        y: Math.round(r.y + r.height/2),
        w: Math.round(r.width),
        h: Math.round(r.height),
      });
    } catch (e) {}
  };

  const nodes = document.querySelectorAll(
    'a, button, input, textarea, select, [role="button"], [role="link"], [role="tab"],' +
    '[role="menuitem"], [role="searchbox"], [role="textbox"], [role="combobox"],' +
    '[role="option"], [role="checkbox"], [contenteditable="true"], [aria-label]'
  );
  for (const el of nodes) {
    const tag = (el.tagName || '').toLowerCase();
    let hint = '';
    if (tag === 'a') hint = 'link';
    else if (tag === 'button') hint = 'button';
    else if (tag === 'input' || tag === 'textarea') hint = 'textbox';
    push(el, hint);
    if (out.length >= 120) break;
  }
  return {
    url: location.href,
    title: document.title || '',
    elements: out,
  };
}
"""


EXTRACT_TEXT_JS = """
() => {
  const clone = document.body ? document.body.cloneNode(true) : null;
  if (!clone) return { title: document.title || '', url: location.href, text: '' };
  for (const sel of ['script','style','noscript','svg','iframe']) {
    clone.querySelectorAll(sel).forEach(n => n.remove());
  }
  const text = (clone.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim().slice(0, 8000);
  const links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    const t = (a.innerText || a.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
    if (!href || !t || t.length < 3) continue;
    if (href.startsWith('javascript:')) continue;
    links.push({ title: t.slice(0, 120), url: href.slice(0, 400) });
    if (links.length >= 25) break;
  }
  return { title: document.title || '', url: location.href, text, links };
}
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def rank_elements(
    elements: list[DomElement] | list[dict],
    query: str,
    *,
    role: str | None = None,
    prefer: str | None = None,  # search | click | type | link | result
    limit: int = 10,
) -> list[DomElement]:
    q = _norm(query)
    prefer = (prefer or "").lower()
    role_f = _norm(role) if role else ""

    scored: list[DomElement] = []
    for raw in elements:
        el = raw if isinstance(raw, DomElement) else DomElement(**{
            k: raw.get(k, getattr(DomElement(), k, None))
            for k in DomElement.__dataclass_fields__
            if k in raw or k == "index"
        })
        if isinstance(raw, dict):
            el = DomElement(
                index=int(raw.get("index") or 0),
                tag=str(raw.get("tag") or ""),
                role=str(raw.get("role") or ""),
                name=str(raw.get("name") or ""),
                text=str(raw.get("text") or ""),
                placeholder=str(raw.get("placeholder") or ""),
                aria_label=str(raw.get("aria_label") or ""),
                href=str(raw.get("href") or ""),
                input_type=str(raw.get("input_type") or ""),
                selector=str(raw.get("selector") or ""),
                x=int(raw.get("x") or 0),
                y=int(raw.get("y") or 0),
                w=int(raw.get("w") or 0),
                h=int(raw.get("h") or 0),
            )

        hay = _norm(" ".join([el.name, el.aria_label, el.placeholder, el.text, el.role, el.tag, el.href]))
        score = 0.0

        if role_f:
            if role_f not in (el.role, el.tag, el.input_type) and role_f not in hay:
                # soft filter — don't hard exclude if name matches strongly
                if q and q not in hay:
                    continue
                score -= 20.0

        if q:
            if hay == q or _norm(el.name) == q:
                score += 100.0
            elif q in hay:
                score += 55.0
            else:
                tokens = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 3]
                hits = sum(1 for t in tokens if t in hay)
                if not hits:
                    if prefer not in ("search", "result") or not _looks_searchish(el):
                        continue
                    score += 5.0
                else:
                    score += 12.0 * hits

        # Preference boosts
        if prefer in ("search", "type"):
            if el.role in ("searchbox", "textbox", "combobox") or el.tag in ("input", "textarea"):
                score += 40.0
            if "search" in hay:
                score += 25.0
            if el.input_type in ("search", "text", ""):
                score += 8.0
        elif prefer in ("click", "button"):
            if el.role in ("button", "link", "menuitem", "tab") or el.tag in ("button", "a"):
                score += 25.0
        elif prefer in ("link", "result"):
            if el.tag == "a" or el.role == "link":
                score += 30.0
            if el.href and ("watch" in el.href or "http" in el.href):
                score += 10.0
            # Google result-ish
            if "/url?" in el.href or "http" in el.href:
                score += 5.0

        if el.w >= 8 and el.h >= 8:
            score += 3.0

        el.score = score
        if score > 0 or (prefer in ("search",) and _looks_searchish(el)):
            if prefer in ("search",) and _looks_searchish(el) and score < 15:
                el.score = 15.0
            scored.append(el)

    scored.sort(key=lambda e: (-e.score, e.index))
    return scored[:limit]


def _looks_searchish(el: DomElement) -> bool:
    hay = _norm(" ".join([el.role, el.tag, el.name, el.placeholder, el.aria_label, el.input_type]))
    if el.tag in ("input", "textarea") or el.role in ("searchbox", "textbox", "combobox"):
        if any(x in hay for x in ("search", "query", "find", "google", "youtube")):
            return True
        if el.input_type in ("search", "text", ""):
            return True
    return False


def elements_from_payload(data: dict) -> list[DomElement]:
    out = []
    for raw in data.get("elements") or []:
        out.append(
            DomElement(
                index=int(raw.get("index") or 0),
                tag=str(raw.get("tag") or ""),
                role=str(raw.get("role") or ""),
                name=str(raw.get("name") or ""),
                text=str(raw.get("text") or ""),
                placeholder=str(raw.get("placeholder") or ""),
                aria_label=str(raw.get("aria_label") or ""),
                href=str(raw.get("href") or ""),
                input_type=str(raw.get("input_type") or ""),
                selector=str(raw.get("selector") or ""),
                x=int(raw.get("x") or 0),
                y=int(raw.get("y") or 0),
                w=int(raw.get("w") or 0),
                h=int(raw.get("h") or 0),
            )
        )
    return out
