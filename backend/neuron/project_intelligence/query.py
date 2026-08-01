"""Natural-language queries over the project index."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from neuron.developer.index import resolve_root
from neuron.project_intelligence.indexer import deep_index
from neuron.project_intelligence.memory import get_or_build_memory

_AUTH_HINTS = re.compile(
    r"\b(auth|authenticat|authorization|login|logout|signin|sign-in|oauth|jwt|"
    r"passport|session|credential|password|bearer|api[_-]?key|firebase.?auth|"
    r"supabase.?auth|next-?auth|clerk)\b",
    re.I,
)

_LEAK_PATTERNS = [
    (re.compile(r"\bsetInterval\s*\(", re.I), "setInterval without clearInterval nearby"),
    (re.compile(r"\baddEventListener\s*\(", re.I), "addEventListener — check removeEventListener"),
    (re.compile(r"\bwhile\s*\(\s*True\s*\)", re.I), "infinite while True loop"),
    (re.compile(r"\bopen\s*\([^)]+\)(?![\s\S]{0,200}\.close\()", re.I), "open() — verify close/context manager"),
    (re.compile(r"\bglobal\s+_CACHE\b|\b_CACHE\s*[:=]", re.I), "module-level cache — ensure eviction"),
    (re.compile(r"\bnew\s+\w+\s*[\[(]", re.I), "manual new — verify dispose/delete"),
    (re.compile(r"\bmalloc\s*\(", re.I), "malloc — verify free"),
    (re.compile(r"\bsubprocess\.Popen\b", re.I), "Popen — verify process wait/terminate"),
    (re.compile(r"\.subscribe\s*\(", re.I), "subscribe — verify unsubscribe"),
]


def project_overview(root: str | Path | None = None) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    mem = get_or_build_memory(root_p)
    idx = deep_index(root_p)
    arch = mem.get("architecture") or {}
    langs = ", ".join(f"{k}({v})" for k, v in list((arch.get("languages") or idx.get("languages") or {}).items())[:6])
    modules = ", ".join(arch.get("entry_areas") or [])[:220]
    title = arch.get("title") or idx.get("name")
    summary = arch.get("summary") or "No README summary found."
    say = (
        f"{title}: {summary} "
        f"Languages: {langs or 'n/a'}. "
        f"Top modules: {modules or 'n/a'}. "
        f"Indexed {idx.get('source_count', 0)} sources, "
        f"{idx.get('doc_count', 0)} docs, {idx.get('asset_count', 0)} assets, "
        f"{idx.get('build_dir_count', 0)} build dirs."
    )
    return {"ok": True, "say": say.strip(), "architecture": arch, "index": {
        "sources": idx.get("source_count"),
        "docs": idx.get("doc_count"),
        "assets": idx.get("asset_count"),
        "modules": idx.get("modules"),
    }, "memory_path": mem.get("memory_path")}


def locate_feature(root: str | Path | None = None, *, topic: str = "authentication") -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    idx = deep_index(root_p)
    topic_l = (topic or "authentication").lower()
    pattern = _AUTH_HINTS if "auth" in topic_l or "login" in topic_l else re.compile(
        re.escape(topic_l.split()[0]) if topic_l else "auth", re.I
    )

    hits: list[dict[str, Any]] = []
    candidates = list(idx.get("sources_sample") or [])
    for s in _extra_sources(root_p, limit=800):
        candidates.append(s)

    seen: set[str] = set()
    for s in candidates:
        rel = s.get("path") if isinstance(s, dict) else str(s)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        path_score = 2 if pattern.search(rel.replace("\\", "/")) else 0
        content_hits = 0
        snippet = ""
        path = root_p / rel
        if path.is_file() and path.stat().st_size < 400_000:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for i, line in enumerate(text.splitlines()[:400], 1):
                if pattern.search(line):
                    content_hits += 1
                    if not snippet:
                        snippet = f"L{i}: {line.strip()[:160]}"
        score = path_score + min(content_hits, 5)
        if score:
            hits.append({"path": rel, "score": score, "matches": content_hits, "snippet": snippet})

    hits.sort(key=lambda h: (-h["score"], h["path"]))
    top = hits[:15]
    if not top:
        say = f"No strong matches for '{topic}' in indexed sources."
    else:
        paths = ", ".join(h["path"] for h in top[:5])
        say = f"Likely '{topic}' locations: {paths}."
    return {"ok": True, "say": say, "topic": topic, "hits": top}


def find_memory_leaks(root: str | Path | None = None) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    findings: list[dict[str, Any]] = []
    for s in _extra_sources(root_p, limit=600):
        rel = s["path"]
        path = root_p / rel
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 250_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for rx, reason in _LEAK_PATTERNS:
            m = rx.search(text)
            if not m:
                continue
            # soften open() false positives if 'with open' present heavily
            if "open()" in reason and "with open" in text:
                continue
            line_no = text[: m.start()].count("\n") + 1
            findings.append({
                "path": rel,
                "line": line_no,
                "reason": reason,
                "excerpt": text.splitlines()[line_no - 1].strip()[:140] if line_no <= len(text.splitlines()) else "",
            })
            if len(findings) >= 40:
                break
        if len(findings) >= 40:
            break

    if not findings:
        say = "No obvious memory-leak heuristics matched (static scan)."
    else:
        sample = "; ".join(f"{f['path']}:{f['line']} ({f['reason']})" for f in findings[:5])
        say = f"Found {len(findings)} potential leak/resource risks. Top: {sample}."
    return {"ok": True, "say": say, "findings": findings}


def search_project(root: str | Path | None = None, *, query: str) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    q = (query or "").strip()
    if not q:
        return {"ok": False, "say": "Need a search query.", "hits": []}
    rx = re.compile(re.escape(q), re.I)
    hits: list[dict[str, Any]] = []
    for s in _extra_sources(root_p, limit=900):
        rel = s["path"]
        path = root_p / rel
        if rx.search(rel):
            hits.append({"path": rel, "line": 0, "snippet": "(path match)"})
        if not path.is_file() or path.stat().st_size > 200_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines()[:500], 1):
            if rx.search(line):
                hits.append({"path": rel, "line": i, "snippet": line.strip()[:160]})
                break
        if len(hits) >= 25:
            break
    say = f"{len(hits)} hit(s) for {q!r}." if hits else f"No hits for {q!r}."
    return {"ok": True, "say": say, "query": q, "hits": hits}


def _extra_sources(root: Path, *, limit: int = 800) -> list[dict[str, Any]]:
    from neuron.project_intelligence.indexer import _SOURCE_EXT, _SKIP_DEEP, _BUILD_DIR_NAMES
    out: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DEEP and d not in _BUILD_DIR_NAMES and not d.endswith(".egg-info")]
        for name in filenames:
            suf = Path(name).suffix.lower()
            if suf not in _SOURCE_EXT:
                continue
            p = Path(dirpath) / name
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            out.append({"path": rel, "ext": suf})
            if len(out) >= limit:
                return out
    return out
