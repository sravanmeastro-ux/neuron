"""Utterance normalization — wraps nlu.py; adds casual variants without slang spam."""

from __future__ import annotations

import re
import time

from neuron.v4.context.types import ParsedUtterance

# Extra casual → canonical (deterministic, no LLM)
_CASUAL: list[tuple[str, str]] = [
    (r"^(?:bring|pull)\s+(?:up\s+)?(.+)$", r"open \1"),
    (r"^i\s+need\s+(.+)$", r"open \1"),
    (r"^fire\s+up\s+(.+)$", r"open \1"),
    (r"^launch\s+up\s+(.+)$", r"open \1"),
    (r"^go\s+(?:to|into)\s+(.+)$", r"go to \1"),
    (r"^make\s+(?:it\s+)?fullscreen$", "make it fullscreen"),
    (r"^put\s+(?:it\s+)?(?:in\s+)?fullscreen$", "make it fullscreen"),
]

_NEGATION = re.compile(
    r"\b(?:don'?t|do\s+not|never|stop)\s+(?:open|click|close|launch|start|play|type)\b|"
    r"\bnot\s+(?:chrome|edge|spotify|youtube|blender)\b|"
    r"\banything\s+except\b|"
    r"^don'?t\b",
    re.I,
)

_CORRECTION_SPLIT = re.compile(
    r"\s*(?:[-—–]\s*)?(?:\bno[,.]?\s+|actually\s+|nope[,.]?\s+|wait[,.]?\s+)"
    r"(?:no[,.]?\s+|actually\s+)?",
    re.I,
)

_SELF_CORRECT = re.compile(
    r"^(.+?)(?:\s*[-—–,]\s*|\s+)(?:no[,.]?|actually|wait[,.]?)\s+(.+)$",
    re.I,
)

_LEADING_ACTUALLY = re.compile(r"^actually[,.]?\s+", re.I)

_COMPOUND = re.compile(r"\s+(?:and|,)\s+(?=(?:open|search|play|go\s+to|move|put|make|find)\b)", re.I)


def normalize_utterance(raw: str) -> ParsedUtterance:
    t0 = time.perf_counter()
    import nlu

    info = nlu.understand(raw or "")
    cleaned = info.get("cleaned") or ""
    canonical = info.get("canonical") or cleaned
    variants = list(info.get("variants") or [])

    # Casual variants on top of nlu polish
    for pat, repl in _CASUAL:
        nxt = re.sub(pat, repl, canonical, flags=re.I).strip()
        if nxt and nxt != canonical:
            canonical = nlu.polish(nxt)
            break

    negation = bool(_NEGATION.search(canonical) or _NEGATION.search(raw or ""))
    neg_target = ""
    if negation:
        m = re.search(
            r"(?:don'?t|do\s+not|never)\s+(?:open|click|close|launch|start|play)?\s*(.+)$",
            canonical,
            re.I,
        )
        if m:
            neg_target = m.group(1).strip()

    abandoned = ""
    final = ""
    work = canonical
    leading_actually = bool(_LEADING_ACTUALLY.match(work))
    if leading_actually:
        work = _LEADING_ACTUALLY.sub("", work).strip()
        work = nlu.polish(work) or work
        final = work
        abandoned = "(prior)"
    m = _SELF_CORRECT.match(canonical if not leading_actually else canonical)
    if m and not leading_actually:
        left, right = m.group(1).strip(), m.group(2).strip()
        # "open Spotify no open Chrome" / "search Blender actually Unreal"
        abandoned = left
        final = right
        # If right lacks verb, inherit from left
        if not re.match(
            r"^(?:open|close|search|play|move|put|go|make|click|type|focus)\b",
            final,
            re.I,
        ):
            verb_m = re.match(
                r"^((?:open|close|search|play|move|put|go\s+to|make|click|type|focus)\b)\s+",
                left,
                re.I,
            )
            if verb_m:
                final = f"{verb_m.group(1)} {final}".strip()
        work = nlu.polish(final) or final

    compound: list[str] = []
    if re.search(r"\band\b|,", work, re.I) and not abandoned:
        parts = _COMPOUND.split(work)
        if len(parts) >= 2:
            compound = [nlu.polish(p.strip()) or p.strip() for p in parts if p.strip()]

    pu = ParsedUtterance(
        raw=raw or "",
        cleaned=cleaned,
        canonical=work,
        variants=variants,
        fillers_stripped=cleaned != (raw or "").lower().strip(),
        negation=negation and not final,  # correction overrides pure negation block
        negation_target=neg_target,
        correction_abandoned=abandoned,
        correction_final=final,
        compound_parts=compound,
        latency_ms=(time.perf_counter() - t0) * 1000,
    )
    return pu


__all__ = ["normalize_utterance"]
