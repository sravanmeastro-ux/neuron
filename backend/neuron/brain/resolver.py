"""Phase 8 — resolve ambiguous deixis using ContextSnapshot + confidence."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from neuron.brain.snapshot import ContextSnapshot

# Confidence bands (overridable via config agent.context_*)
HIGH = 0.75
MEDIUM = 0.45

_ORDINALS = {
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "sixth": 5,
    "last": -1,
}

_DEIXIS = re.compile(
    r"\b("
    r"it|that|this|them|those|these|there|"
    r"the\s+(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+(?:one|result|video|file|item|track|song|link|tab|window)|"
    r"(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+(?:one|result|video|file|item|track|song|link)|"
    r"the\s+(?:video|file|folder|song|track|page|window|tab|result|one)|"
    r"that\s+(?:video|file|folder|song|track|page|window|tab|result|one)|"
    r"this\s+(?:video|file|folder|song|track|page|window|tab|result|one)|"
    r"the\s+[\w.+-]{2,40}\s+one"
    r")\b",
    re.I,
)

_DESTRUCTIVE = re.compile(
    r"\b("
    r"delete|remove|erase|uninstall|format|wipe|destroy|"
    r"shut\s*down|shutdown|power\s*off|kill\s+all|close\s+all|"
    r"empty\s+recycle|rm\s+-rf|drop\s+table"
    r")\b",
    re.I,
)

_PLAY = re.compile(r"\b(play|open|start|click|select|launch)\b", re.I)
_PAUSE = re.compile(r"\b(pause|stop|halt)\b", re.I)
_RESUME = re.compile(r"\b(resume|unpause|continue)\b", re.I)
_CLOSE = re.compile(r"\b(close|dismiss|exit|quit)\b", re.I)


@dataclass
class ResolvedReference:
    phrase: str
    entity_type: str  # video | file | playback | window | page | element | app | unknown
    label: str = ""
    index: int | None = None
    action_hint: str = ""  # play | open | pause | resume | click | focus | close
    tool_hint: str = ""
    args_hint: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    candidates: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolveResult:
    ambiguous: bool = False
    references: list[ResolvedReference] = field(default_factory=list)
    rewritten_request: str = ""
    confidence: float = 1.0
    band: str = "high"  # high | medium | low
    needs_inspect: bool = False
    ask_user: str | None = None
    destructive_blocked: bool = False
    resolved_blob: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguous": self.ambiguous,
            "references": [r.to_dict() for r in self.references],
            "rewritten_request": self.rewritten_request,
            "confidence": self.confidence,
            "band": self.band,
            "needs_inspect": self.needs_inspect,
            "ask_user": self.ask_user,
            "destructive_blocked": self.destructive_blocked,
            "resolved_blob": self.resolved_blob,
        }


def _cfg_thresholds() -> tuple[float, float]:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(
                encoding="utf-8"
            )
        ).get("agent") or {}
        high = float(cfg.get("context_high_confidence", HIGH) or HIGH)
        med = float(cfg.get("context_medium_confidence", MEDIUM) or MEDIUM)
        return high, med
    except Exception:
        return HIGH, MEDIUM


def is_ambiguous(text: str) -> bool:
    return bool(_DEIXIS.search(text or ""))


def is_destructive(text: str) -> bool:
    return bool(_DESTRUCTIVE.search(text or ""))


def _band(score: float) -> str:
    high, med = _cfg_thresholds()
    if score >= high:
        return "high"
    if score >= med:
        return "medium"
    return "low"


def _ordinal(text: str) -> int | None:
    low = (text or "").lower()
    for word, idx in _ORDINALS.items():
        if re.search(rf"\b{word}\b", low):
            return idx
    m = re.search(r"\b(?:number|#)?\s*(\d{1,2})(?:st|nd|rd|th)?\b", low)
    if m:
        n = int(m.group(1))
        if n >= 1:
            return n - 1
    return None


def _qualifier_one(text: str) -> str | None:
    """Match 'the Blender one' / 'the downloads one'."""
    m = re.search(r"\bthe\s+([a-z0-9][\w.+-]{1,40})\s+one\b", (text or "").lower())
    if not m:
        return None
    word = m.group(1)
    if word in _ORDINALS or word in (
        "first", "second", "third", "video", "file", "song", "track", "page", "window", "tab", "result",
    ):
        return None
    return word


def _action_hint(text: str) -> str:
    if _PAUSE.search(text) and not _PLAY.search(text):
        return "pause"
    if _RESUME.search(text):
        return "resume"
    if _CLOSE.search(text):
        return "close"
    if _PLAY.search(text):
        return "play"
    if re.search(r"\b(open|show)\b", text, re.I):
        return "open"
    return "click"


def _candidate_labels(snap: ContextSnapshot) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = (s or "").strip()
        if not t or len(t) < 2:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        labels.append(t)

    for e in snap.ui_elements:
        add(e.get("name") or "")
        add(e.get("value") or "")
    for t in snap.visible_text:
        add(t)
    if snap.browser_dom_summary:
        for part in re.split(r"\s*\|\s*", snap.browser_dom_summary):
            part = re.sub(r"^\[\d+\]\s*", "", part).strip()
            add(part)
    return labels


def _match_qualifier(qual: str, labels: list[str]) -> tuple[str | None, list[str], float]:
    q = (qual or "").lower()
    hits = [L for L in labels if q in L.lower()]
    if not hits:
        # fuzzy token
        hits = [L for L in labels if any(tok.startswith(q[:4]) for tok in re.split(r"\W+", L.lower()) if tok)]
    if not hits:
        return None, [], 0.2
    # Prefer shorter / startswith
    hits.sort(key=lambda L: (0 if L.lower().startswith(q) else 1, len(L)))
    best = hits[0]
    conf = 0.92 if best.lower().startswith(q) or q in best.lower().split() else 0.78
    if len(hits) > 1 and hits[0].lower() != hits[1].lower():
        # Close competitors → lower
        if hits[1].lower().startswith(q) or q in hits[1].lower():
            conf = min(conf, 0.58)
    return best, hits[:5], conf


def _pick_ordinal(labels: list[str], index: int, *, prefer_video: bool = False) -> tuple[str | None, float]:
    if not labels:
        return None, 0.25
    filtered = labels
    if prefer_video:
        vidish = [
            L
            for L in labels
            if not re.match(r"^(home|shorts|subscriptions|library|search|filter|sign in)$", L, re.I)
            and len(L) > 8
        ]
        if vidish:
            filtered = vidish
    if index == -1:
        index = len(filtered) - 1
    if index < 0 or index >= len(filtered):
        return None, 0.3
    return filtered[index], 0.86 if prefer_video or len(filtered) >= index + 1 else 0.7


def resolve(request: str, snapshot: ContextSnapshot | None = None) -> ResolveResult:
    """Convert ambiguous references into concrete entities with confidence."""
    text = (request or "").strip()
    snap = snapshot or ContextSnapshot()
    result = ResolveResult(rewritten_request=text)

    if not text:
        return result

    ambiguous = is_ambiguous(text)
    result.ambiguous = ambiguous
    if not ambiguous:
        result.confidence = 1.0
        result.band = "high"
        return result

    destructive = is_destructive(text)
    result.destructive_blocked = destructive
    action = _action_hint(text)
    labels = _candidate_labels(snap)
    scene = snap.scene or "unknown"
    refs: list[ResolvedReference] = []

    # --- "the Blender one" ---
    qual = _qualifier_one(text)
    if qual:
        best, hits, conf = _match_qualifier(qual, labels)
        ref = ResolvedReference(
            phrase=f"the {qual} one",
            entity_type="file" if scene == "explorer" else "element",
            label=best or "",
            action_hint=action if action != "click" else ("open" if scene == "explorer" else "click"),
            confidence=conf if best else 0.25,
            candidates=hits,
            reason=f"Matched qualifier '{qual}' against visible items" if best else f"No visible item matched '{qual}'",
        )
        if best and scene == "explorer":
            ref.tool_hint = "click_ui_element"
            ref.args_hint = {"name": best}
        elif best and scene in ("youtube", "browser"):
            ref.tool_hint = "browser_click"
            ref.args_hint = {"name": best}
            ref.entity_type = "video" if scene == "youtube" else "element"
        elif best:
            ref.tool_hint = "click_ui_element"
            ref.args_hint = {"name": best}
        refs.append(ref)

    # --- ordinal: first one / second video ---
    ord_idx = _ordinal(text)
    if ord_idx is not None and not qual:
        prefer_video = scene == "youtube" or bool(re.search(r"\bvideo\b", text, re.I))
        label, conf = _pick_ordinal(labels, ord_idx, prefer_video=prefer_video)
        # YouTube / browser: index-based click is strong even without label
        if scene in ("youtube", "browser") and (label or True):
            conf = max(conf, 0.82 if labels else 0.55)
            ref = ResolvedReference(
                phrase=re.search(
                    r"(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+\w+",
                    text,
                    re.I,
                ).group(0)
                if re.search(
                    r"(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+\w+",
                    text,
                    re.I,
                )
                else f"index {ord_idx}",
                entity_type="video" if scene == "youtube" else "element",
                label=label or f"result #{ord_idx + 1}",
                index=ord_idx,
                action_hint="play" if action in ("play", "click") else action,
                tool_hint="browser_click",
                args_hint={"index": ord_idx} if not label else {"name": label, "index": ord_idx},
                confidence=conf,
                candidates=labels[:5],
                reason=f"Ordinal {ord_idx} on {scene} with {len(labels)} visible candidates",
            )
            refs.append(ref)
        elif scene == "explorer":
            ref = ResolvedReference(
                phrase="ordinal item",
                entity_type="file",
                label=label or "",
                index=ord_idx,
                action_hint="open",
                tool_hint="click_ui_element",
                args_hint={"name": label} if label else {},
                confidence=conf if label else 0.35,
                candidates=labels[:5],
                reason="Ordinal file/list item in Explorer",
            )
            refs.append(ref)
        else:
            ref = ResolvedReference(
                phrase="ordinal item",
                entity_type="element",
                label=label or "",
                index=ord_idx,
                action_hint=action,
                tool_hint="click_ui_element",
                args_hint={"name": label} if label else {},
                confidence=conf if label else 0.35,
                candidates=labels[:5],
                reason=f"Ordinal on scene={scene}",
            )
            refs.append(ref)

    # --- it / that / this (playback, page, window) ---
    if re.search(r"\b(it|that|this)\b", text, re.I) and not refs:
        if scene == "spotify" or "spotify" in (snap.active_window or "").lower():
            if action in ("pause", "resume", "play"):
                refs.append(
                    ResolvedReference(
                        phrase="it",
                        entity_type="playback",
                        label="current Spotify playback",
                        action_hint=action if action != "play" else "resume",
                        tool_hint="hotkey",
                        args_hint={"keys": "space"},
                        confidence=0.9,
                        reason="Spotify focused → 'it' = current playback",
                    )
                )
            else:
                refs.append(
                    ResolvedReference(
                        phrase="it",
                        entity_type="playback",
                        label="current Spotify playback",
                        action_hint=action,
                        confidence=0.7,
                        reason="Spotify focused; ambiguous action on playback",
                    )
                )
        elif re.search(r"\b(page|tab)\b", text, re.I) or (
            action in ("close",) and scene in ("browser", "youtube")
        ):
            refs.append(
                ResolvedReference(
                    phrase="this page" if "page" in text.lower() else "it",
                    entity_type="page",
                    label=snap.browser_title or snap.active_window or "current page",
                    action_hint=action,
                    tool_hint="browser_close_tab" if action == "close" else "",
                    confidence=0.8 if snap.browser_url or snap.browser_title else 0.55,
                    reason="Deixis to current browser page/tab",
                )
            )
        elif re.search(r"\bwindow\b", text, re.I):
            refs.append(
                ResolvedReference(
                    phrase="that window",
                    entity_type="window",
                    label=snap.active_window or snap.active_application or "",
                    action_hint=action,
                    tool_hint="focus_app" if action == "click" else ("close_app" if action == "close" else "focus_app"),
                    args_hint={"name": snap.active_application or snap.active_window},
                    confidence=0.85 if snap.active_window else 0.4,
                    reason="Deixis to active window",
                )
            )
        elif scene == "youtube" and action in ("play", "pause", "click"):
            # "pause it" on YouTube → media key / space
            refs.append(
                ResolvedReference(
                    phrase="it",
                    entity_type="playback",
                    label=snap.browser_title or "current YouTube video",
                    action_hint=action,
                    tool_hint="hotkey",
                    args_hint={"keys": "k" if action == "pause" else "space"},
                    confidence=0.78,
                    reason="YouTube → 'it' = current video playback",
                )
            )
        else:
            # Generic "it" — try last tool target or active app
            label = snap.active_application or snap.active_window or ""
            conf = 0.5 if label else 0.3
            if snap.recent_actions:
                conf = max(conf, 0.55)
            refs.append(
                ResolvedReference(
                    phrase="it",
                    entity_type="app" if label else "unknown",
                    label=label or "current focus",
                    action_hint=action,
                    confidence=conf,
                    reason="Generic deixis; using active application/window",
                    candidates=labels[:5],
                )
            )

    # --- there ---
    if re.search(r"\bthere\b", text, re.I) and not refs:
        refs.append(
            ResolvedReference(
                phrase="there",
                entity_type="element",
                label=labels[0] if labels else (snap.active_window or ""),
                action_hint=action,
                confidence=0.4 if labels else 0.25,
                candidates=labels[:5],
                reason="'there' needs visible target; weak without gesture",
            )
        )

    result.references = refs
    if not refs:
        result.confidence = 0.3
        result.band = "low"
        result.ask_user = _ask_prompt(text, snap, labels)
        result.needs_inspect = bool(labels) is False
        return result

    result.confidence = min(r.confidence for r in refs)
    # Boost slightly when scene is clear
    if scene in ("youtube", "spotify", "explorer") and result.confidence >= 0.5:
        result.confidence = min(1.0, result.confidence + 0.05)
    result.band = _band(result.confidence)

    # Destructive + any ambiguity → never auto-execute
    if destructive:
        result.band = "low"
        result.confidence = min(result.confidence, 0.4)
        result.destructive_blocked = True
        result.ask_user = (
            "That could be destructive. "
            + _ask_prompt(text, snap, labels, refs=refs)
        )
        result.rewritten_request = text
        result.resolved_blob = _blob(refs, snap)
        return result

    high, med = _cfg_thresholds()
    if result.confidence < med:
        result.ask_user = _ask_prompt(text, snap, labels, refs=refs)
        result.needs_inspect = len(labels) < 3
    elif result.confidence < high:
        result.needs_inspect = True
        result.ask_user = None
    else:
        result.needs_inspect = False
        result.ask_user = None

    result.rewritten_request = _rewrite(text, refs, snap)
    result.resolved_blob = _blob(refs, snap)
    return result


def _rewrite(text: str, refs: list[ResolvedReference], snap: ContextSnapshot) -> str:
    if not refs:
        return text
    r = refs[0]
    if r.entity_type == "playback" and r.action_hint == "pause":
        return f"Pause current playback in {snap.active_application or 'Spotify'}"
    if r.entity_type == "playback" and r.action_hint in ("resume", "play"):
        return f"Resume current playback in {snap.active_application or 'Spotify'}"
    if r.index is not None and r.entity_type == "video":
        label = r.label or f"result #{r.index + 1}"
        return f"Play the YouTube result '{label}' (index {r.index})"
    if r.label and r.entity_type == "file":
        return f"Open the file '{r.label}' in the current Explorer window"
    if r.label and r.entity_type in ("element", "video"):
        verb = "Play" if r.action_hint == "play" else "Click"
        return f"{verb} '{r.label}'"
    if r.entity_type == "window" and r.label:
        return f"{r.action_hint.capitalize()} the window '{r.label}'"
    if r.entity_type == "page" and r.label:
        return f"{r.action_hint.capitalize()} the page '{r.label}'"
    return text


def _blob(refs: list[ResolvedReference], snap: ContextSnapshot) -> str:
    lines = [f"scene={snap.scene}", f"window={snap.active_window or '?'}"]
    for r in refs:
        lines.append(
            f"- '{r.phrase}' → {r.entity_type}:{r.label or '?'} "
            f"conf={r.confidence:.2f} hint={r.tool_hint or '-'} {r.args_hint or {}} "
            f"({r.reason})"
        )
    return "\n".join(lines)


def _ask_prompt(
    text: str,
    snap: ContextSnapshot,
    labels: list[str],
    refs: list[ResolvedReference] | None = None,
) -> str:
    opts = labels[:4]
    if refs:
        for r in refs:
            opts = (r.candidates or opts)[:4]
    if opts:
        listed = "; ".join(f"'{o[:50]}'" for o in opts)
        return f"Which one did you mean — {listed}?"
    where = snap.active_window or snap.active_application or "the screen"
    return f"I'm not sure what you mean by that on {where}. Can you be more specific?"
