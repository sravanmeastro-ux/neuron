"""V3.3 ReferenceResolver — contextual deixis using ContextEngine / WorldState.

Priority (where appropriate):
  1. explicit current command information
  2. current task
  3. active application / window (verified WorldState)
  4. recent semantic entities
  5. recent verified actions
  6. conversation / recent commands
  7. visible UI candidates (V3.4 PerceptionEngine via agent when context is thin)

Does NOT silently guess ambiguous consequential targets (close/delete/move).
Composes Phase 8 neuron.brain.resolver when a ContextSnapshot is supplied —
does not replace it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


HIGH = 0.75
MEDIUM = 0.45


@dataclass
class ReferenceResolution:
    """Structured result for one contextual resolve call."""

    resolved_target: str = ""
    target_type: str = ""  # app | window | monitor | video | file | folder | site | action | unknown
    confidence: float = 0.0
    evidence: str = ""
    needs_clarification: bool = False
    clarification_prompt: str = ""
    rewritten_command: str = ""
    tool_hint: str = ""
    args_hint: dict[str, Any] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)
    phrase: str = ""
    source: str = ""  # which priority layer won

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
    "previous": -2,
}

_DEIXIS = re.compile(
    r"\b("
    r"it|that|this|them|those|these|"
    r"the\s+(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous)\s+"
    r"(?:one|result|video|file|item|track|song|link|tab|window)|"
    r"(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous)\s+"
    r"(?:one|result|video|file|item|track|song|link|tab)|"
    r"the\s+(?:other\s+)?(?:monitor|screen)|"
    r"the\s+(?:file|folder|video|window|tab|result|one)|"
    r"that\s+(?:file|folder|video|window|tab|result|one)|"
    r"this\s+(?:file|folder|video|window|tab|result|one)|"
    r"go\s+back|do\s+that\s+again|do\s+it\s+again|repeat\s+that|"
    r"the\s+file\s+i\s+just\s+downloaded|that\s+file\s+i\s+downloaded"
    r")\b",
    re.I,
)

_CONSEQUENTIAL = re.compile(
    r"\b(close|quit|exit|delete|remove|uninstall|kill|move|drag)\b",
    re.I,
)


def needs_resolution(text: str) -> bool:
    return bool(_DEIXIS.search(text or ""))


def resolve_reference(
    raw: str,
    *,
    intent: Any | None = None,
    engine: Any | None = None,
    ui_candidates: list[dict[str, Any]] | None = None,
    snapshot: Any | None = None,
) -> ReferenceResolution:
    """
    Resolve contextual references into a concrete target + optional rewrite.

    ui_candidates: optional list of {label, type, index?} for V3.4 perception.
    snapshot: optional ContextSnapshot — delegates UI ordinals to Phase 8 when useful.
    """
    text = _normalize_text(raw, intent)
    raw_l = (raw or "").strip().lower()
    if not text:
        return ReferenceResolution(confidence=1.0, evidence="empty")

    # Prefer raw for deixis detection (NLU may drop articles)
    if (
        not needs_resolution(text)
        and not needs_resolution(raw_l)
        and not _is_monitor_relative(text)
        and not _is_monitor_relative(raw_l)
    ):
        return ReferenceResolution(
            confidence=1.0,
            evidence="no_deixis",
            rewritten_command=text,
        )

    # Use the phrasing that still contains deixis markers
    if needs_resolution(raw_l) and not needs_resolution(text):
        text = raw_l

    try:
        from neuron.v3.context_engine import get_engine
        eng = engine or get_engine()
    except Exception:
        eng = engine

    # 1) Explicit command info (ordinals / monitors named in the utterance)
    hit = _resolve_explicit(text, eng, ui_candidates)
    if hit:
        return hit

    # 7 / Phase-8 UI snapshot ordinals when available (before weak guesses)
    if snapshot is not None and _has_ordinal(text):
        hit = _resolve_via_phase8(raw, text, snapshot)
        if hit and (hit.confidence >= MEDIUM or hit.needs_clarification):
            return hit

    # 7) Optional UI candidates from future perception
    if ui_candidates and _has_ordinal(text):
        hit = _resolve_ui_candidates(text, ui_candidates)
        if hit:
            return hit

    # Repeat / go back (action references) — before pronouns
    hit = _resolve_repeat_or_back(text, eng)
    if hit:
        return hit

    # Monitor-relative ("the other monitor") with optional "it"
    hit = _resolve_monitor_relative(text, eng)
    if hit:
        return hit

    # Recent file download phrase
    hit = _resolve_recent_download(text, eng)
    if hit:
        return hit

    # Pronouns: it / that / this → app/window/site/file from context
    hit = _resolve_pronoun(text, eng)
    if hit:
        return hit

    # Ordinals without UI snapshot — use recent entities / search context
    if _has_ordinal(text):
        hit = _resolve_ordinal_from_context(text, eng, ui_candidates)
        if hit:
            return hit

    # Ambiguous consequential → clarify
    if _CONSEQUENTIAL.search(text) and needs_resolution(text):
        cands = _plausible_targets(eng)
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt=_clarify_prompt(text, cands),
            candidates=cands,
            confidence=0.25,
            evidence="ambiguous_consequential",
            phrase=_deixis_phrase(text),
            target_type="unknown",
        )

    # Fall through: try Phase 8 if snapshot given
    if snapshot is not None:
        hit = _resolve_via_phase8(raw, text, snapshot)
        if hit:
            return hit

    cands = _plausible_targets(eng)
    if len(cands) > 1 and needs_resolution(text):
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt=_clarify_prompt(text, cands),
            candidates=cands,
            confidence=0.3,
            evidence="multiple_candidates",
            phrase=_deixis_phrase(text),
        )

    return ReferenceResolution(
        needs_clarification=bool(needs_resolution(text)),
        clarification_prompt=(
            _clarify_prompt(text, cands) if needs_resolution(text) else ""
        ),
        candidates=cands,
        confidence=0.2 if needs_resolution(text) else 1.0,
        evidence="unresolved" if needs_resolution(text) else "no_deixis",
        rewritten_command=text if not needs_resolution(text) else "",
    )


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------

def _resolve_explicit(
    text: str,
    eng: Any,
    ui_candidates: list[dict] | None,
) -> ReferenceResolution | None:
    """Command already names the object clearly — little to resolve."""
    # "play the first video" with explicit video word + ordinal handled later
    m = re.search(r"\bmonitor\s+(\d+)\b|\bscreen\s+(\d+)\b", text)
    if m and not re.search(r"\b(it|that|this)\b", text):
        # explicit monitor without pronoun — not deixis for target object
        return None
    return None


def _resolve_repeat_or_back(text: str, eng: Any) -> ReferenceResolution | None:
    if re.search(r"\b(do\s+that\s+again|do\s+it\s+again|repeat\s+that)\b", text):
        act = _last_verified_action(eng)
        if not act:
            return ReferenceResolution(
                needs_clarification=True,
                clarification_prompt="What should I do again?",
                confidence=0.2,
                evidence="no_recent_action",
                target_type="action",
                phrase="do that again",
            )
        rewrite = _action_to_command(act)
        return ReferenceResolution(
            resolved_target=act.get("action") or "",
            target_type="action",
            confidence=0.88,
            evidence="recent_verified_action",
            source="recent_actions",
            rewritten_command=rewrite,
            tool_hint=act.get("action") or "",
            args_hint=dict(act.get("args") or {}),
            phrase="do that again",
        )

    if re.search(r"\bgo\s+back\b", text):
        # Prefer browser back when browser/youtube scene; else previous app entity
        scene = ""
        app = ""
        if eng is not None:
            scene = (eng.world.scene or "").lower()
            app = (eng.world.active_app or "").lower()
            url = (eng.world.browser_url or "").lower()
        if "youtube" in scene or "browser" in scene or "http" in url or "chrome" in app:
            return ReferenceResolution(
                resolved_target="browser_back",
                target_type="action",
                confidence=0.82,
                evidence="browser_context_go_back",
                source="active_app",
                rewritten_command="go back",
                tool_hint="browser_back",
                args_hint={},
                phrase="go back",
            )
        prev = _previous_app_entity(eng)
        if prev:
            return ReferenceResolution(
                resolved_target=prev,
                target_type="app",
                confidence=0.7,
                evidence="previous_app_entity",
                source="recent_entities",
                rewritten_command=f"focus {prev}",
                tool_hint="focus_app",
                args_hint={"name": prev},
                phrase="go back",
            )
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt="Go back where — previous page or previous app?",
            confidence=0.3,
            evidence="go_back_ambiguous",
            phrase="go back",
        )
    return None


def _resolve_monitor_relative(text: str, eng: Any) -> ReferenceResolution | None:
    other = bool(re.search(r"\b(?:the\s+)?other\s+(?:monitor|screen)\b", text))
    fg = bool(re.search(r"\b(?:the\s+)?(?:foreground|current|this)\s+(?:monitor|screen)\b", text))
    m = re.search(
        r"\b(?:monitor|screen)\s+"
        r"(\d+|two|2nd|second|left|right|main|other|foreground|current)\b",
        text,
    )
    mon: int | str | None = None
    if other:
        mon = "other"
    elif fg:
        mon = "foreground"
    elif m:
        tok = m.group(1)
        if tok in ("two", "2nd", "second"):
            mon = 2
        elif tok in ("left", "right", "main", "other", "foreground", "current"):
            mon = tok
        else:
            mon = int(tok)

    if mon is None:
        return None

    # Need a window/app target for move
    if not re.search(r"\b(move|put|send|drag)\b", text) and not re.search(
        r"\b(it|that|this)\b", text
    ):
        # "look at the other monitor" style — leave for other systems
        if re.search(r"\b(look|focus|switch)\b", text):
            return ReferenceResolution(
                resolved_target=str(mon),
                target_type="monitor",
                confidence=0.85,
                evidence="monitor_relative",
                source="explicit",
                rewritten_command=f"look at monitor {mon}",
                phrase=_deixis_phrase(text) or "other monitor",
            )
        return None

    target, conf, evidence, source = _resolve_it_target(eng, prefer=("app", "window"))
    if not target:
        cands = _plausible_targets(eng)
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt=(
                f"Which window should I move to monitor {mon}? "
                + ("Options: " + ", ".join(cands) if cands else "")
            ).strip(),
            candidates=cands,
            confidence=0.3,
            evidence="move_missing_target",
            phrase="it",
            target_type="window",
        )

    # Consequential move with multiple equal candidates → clarify
    cands = _plausible_targets(eng)
    if _CONSEQUENTIAL.search(text) and len(cands) > 1 and conf < HIGH:
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt=(
                f"Move which window to monitor {mon}: " + ", ".join(cands) + "?"
            ),
            candidates=cands,
            confidence=conf,
            evidence="move_ambiguous",
            phrase="it",
        )

    return ReferenceResolution(
        resolved_target=target,
        target_type="app",
        confidence=max(conf, 0.8),
        evidence=evidence + f";monitor={mon}",
        source=source,
        rewritten_command=f"move {target} to monitor {mon}",
        tool_hint="move_window_to_monitor",
        args_hint={"title": target, "monitor": mon},
        phrase=_deixis_phrase(text) or "it",
    )


def _resolve_recent_download(text: str, eng: Any) -> ReferenceResolution | None:
    if not re.search(
        r"\b(file\s+i\s+just\s+downloaded|that\s+file\s+i\s+downloaded|"
        r"the\s+download(?:ed)?\s+file|open\s+(?:the\s+)?(?:last\s+)?download)\b",
        text,
    ):
        return None
    path = None
    if eng is not None:
        files = list(eng.recent_files)
        # Prefer downloads paths
        for f in reversed(files):
            if "download" in f.lower() or f.lower().endswith(
                (".pdf", ".zip", ".png", ".jpg", ".exe", ".msi", ".blend")
            ):
                path = f
                break
        if not path and files:
            path = files[-1]
        for e in reversed(list(eng.recent_entities)):
            if e.kind in ("file", "folder") and (
                "download" in e.name.lower() or path is None
            ):
                path = path or e.name
                break
    if not path:
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt="Which downloaded file? I don't have a recent download recorded.",
            confidence=0.25,
            evidence="no_recent_download",
            target_type="file",
            phrase="file I just downloaded",
        )
    return ReferenceResolution(
        resolved_target=path,
        target_type="file",
        confidence=0.8,
        evidence="recent_files",
        source="recent_files",
        rewritten_command=f"open file {path}",
        tool_hint="open_file",
        args_hint={"path": path},
        phrase="file I just downloaded",
    )


def _resolve_pronoun(text: str, eng: Any) -> ReferenceResolution | None:
    if not re.search(r"\b(it|that|this)\b", text):
        return None

    # Action verbs
    if re.search(r"\b(close|quit|exit)\b", text):
        target, conf, evidence, source = _resolve_it_target(
            eng, prefer=("window", "app")
        )
        cands = _plausible_targets(eng)
        if not target or (len(cands) > 1 and conf < HIGH):
            return ReferenceResolution(
                needs_clarification=True,
                clarification_prompt=(
                    "Close which window? "
                    + (", ".join(cands) if cands else "I need a clearer target.")
                ),
                candidates=cands,
                confidence=min(conf, 0.4) if target else 0.25,
                evidence="close_ambiguous" if cands else "close_missing",
                phrase="it",
                target_type="window",
            )
        return ReferenceResolution(
            resolved_target=target,
            target_type="app",
            confidence=conf,
            evidence=evidence,
            source=source,
            rewritten_command=f"close {target}",
            tool_hint="close_app",
            args_hint={"name": target},
            phrase="it",
        )

    if re.search(r"\b(open|focus|switch\s+to)\b", text):
        target, conf, evidence, source = _resolve_it_target(
            eng, prefer=("app", "site", "file", "folder")
        )
        if not target:
            cands = _plausible_targets(eng)
            if len(cands) > 1:
                return ReferenceResolution(
                    needs_clarification=True,
                    clarification_prompt="Open which one: " + ", ".join(cands) + "?",
                    candidates=cands,
                    confidence=0.35,
                    evidence="open_ambiguous",
                    phrase="it",
                )
            # No context — defer to Phase 8 snapshot / LLM (do not steal ask_user)
            return ReferenceResolution(
                confidence=0.2,
                evidence="open_missing_defer",
                phrase="it",
                rewritten_command="",
            )
        if source == "recent_entities" and any(
            e.kind == "site" and e.name.lower() == target.lower()
            for e in (eng.recent_entities if eng else [])
        ):
            return ReferenceResolution(
                resolved_target=target,
                target_type="site",
                confidence=conf,
                evidence=evidence,
                source=source,
                rewritten_command=f"open {target}",
                tool_hint="open_website",
                args_hint={"site": target},
                phrase="it",
            )
        return ReferenceResolution(
            resolved_target=target,
            target_type="app",
            confidence=conf,
            evidence=evidence,
            source=source,
            rewritten_command=f"open {target}",
            tool_hint="open_app",
            args_hint={"name": target},
            phrase="it",
        )

    if re.search(r"\b(search|find)\b", text):
        # "search that" → use recent query / entity as search term
        q = _recent_search_query(eng)
        if not q:
            ent = _latest_entity(eng, kinds=("other", "app", "site"))
            q = ent
        if not q:
            return ReferenceResolution(
                needs_clarification=True,
                clarification_prompt="Search for what?",
                confidence=0.25,
                evidence="search_missing_query",
                phrase="that",
            )
        site = "youtube" if _youtube_context(eng) else "google"
        return ReferenceResolution(
            resolved_target=q,
            target_type="other",
            confidence=0.78,
            evidence="recent_query_or_entity",
            source="recent_entities",
            rewritten_command=f"search {site} for {q}",
            tool_hint="search_site",
            args_hint={"site": site, "query": q},
            phrase="that",
        )

    if re.search(r"\b(play|watch)\b", text) and not _has_ordinal(text):
        # play it → recent video entity or first result context
        label = _latest_entity(eng, kinds=("other", "ui"))
        if _youtube_context(eng):
            return ReferenceResolution(
                resolved_target=label or "first",
                target_type="video",
                confidence=0.7 if label else 0.55,
                evidence="youtube_play_it",
                source="active_app",
                rewritten_command=(
                    f"play video {label}" if label else "play the first video"
                ),
                tool_hint="play_result",
                args_hint={"index": 1},
                phrase="it",
            )

    # Generic "it" with move already handled
    if re.search(r"\b(move|put|send)\b", text):
        return None  # monitor handler

    # Bare focus "it"
    target, conf, evidence, source = _resolve_it_target(eng, prefer=("app", "window"))
    if target and conf >= MEDIUM:
        return ReferenceResolution(
            resolved_target=target,
            target_type="app",
            confidence=conf,
            evidence=evidence,
            source=source,
            rewritten_command=text,  # leave verb as-is if unclear
            phrase="it",
        )
    return None


def _resolve_ordinal_from_context(
    text: str,
    eng: Any,
    ui_candidates: list[dict] | None,
) -> ReferenceResolution | None:
    ord_word, index = _parse_ordinal(text)
    if ord_word is None:
        return None

    if ui_candidates:
        hit = _resolve_ui_candidates(text, ui_candidates)
        if hit:
            return hit

    # YouTube / search results context
    if _youtube_context(eng) or re.search(r"\b(video|result|one)\b", text):
        idx = index if index and index > 0 else 1
        if index == -1:
            idx = 1  # unknown last without UI
        yt = _youtube_context(eng)
        if not yt and not ui_candidates:
            # Let Phase 8 snapshot resolve labeled results ("Lofi Radio")
            return ReferenceResolution(
                confidence=0.4,
                evidence="ordinal_defer_to_snapshot",
                phrase=f"{ord_word} one",
                rewritten_command="",
            )
        return ReferenceResolution(
            resolved_target=f"result:{idx}",
            target_type="video",
            confidence=0.8 if yt else 0.7,
            evidence="ordinal_youtube_or_results",
            source="current_task" if yt else "explicit",
            rewritten_command=f"play the {ord_word} video".replace("1st", "first"),
            tool_hint="play_result",
            args_hint={"index": idx},
            phrase=f"{ord_word} one",
        )

    # File ordinal from recent files (newest first)
    if eng is not None and eng.recent_files:
        files = list(reversed(list(eng.recent_files)))
        path = None
        if index == -1:
            path = files[0] if files else None
        elif index == -2 and len(files) >= 2:
            path = files[1]
        elif index and 1 <= index <= len(files):
            path = files[index - 1]
        if path:
            return ReferenceResolution(
                resolved_target=path,
                target_type="file",
                confidence=0.7,
                evidence="ordinal_recent_files",
                source="recent_files",
                rewritten_command=f"open file {path}",
                tool_hint="open_file",
                args_hint={"path": path},
                phrase=f"{ord_word} one",
            )

    return ReferenceResolution(
        needs_clarification=True,
        clarification_prompt=f"Which is the {ord_word} one? I need more context.",
        confidence=0.3,
        evidence="ordinal_no_context",
        phrase=f"{ord_word} one",
    )


def _resolve_ui_candidates(
    text: str, ui_candidates: list[dict[str, Any]]
) -> ReferenceResolution | None:
    ord_word, index = _parse_ordinal(text)
    if not ui_candidates:
        return None
    labels = [
        str(c.get("label") or c.get("name") or c.get("title") or "").strip()
        for c in ui_candidates
    ]
    labels = [x for x in labels if x]
    if not labels:
        return None
    if index is None:
        return None
    if index == -1:
        chosen = labels[-1]
        idx = len(labels)
    elif index == -2 and len(labels) >= 2:
        chosen = labels[-2]
        idx = len(labels) - 1
    elif 1 <= index <= len(labels):
        chosen = labels[index - 1]
        idx = index
    else:
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt="Which one? " + "; ".join(
                f"{i+1}. {l}" for i, l in enumerate(labels[:6])
            ),
            candidates=labels[:8],
            confidence=0.35,
            evidence="ordinal_out_of_range",
            phrase=ord_word or "one",
        )
    return ReferenceResolution(
        resolved_target=chosen,
        target_type=str(ui_candidates[idx - 1].get("type") or "ui"),
        confidence=0.9,
        evidence="ui_candidates",
        source="ui_candidates",
        rewritten_command=f"play the {ord_word} video" if "video" in text else f"select {chosen}",
        tool_hint="play_result" if re.search(r"\b(play|video|result)\b", text) else "click_element",
        args_hint=(
            {"index": idx}
            if re.search(r"\b(play|video|result)\b", text)
            else {"name": chosen}
        ),
        phrase=f"{ord_word} one",
        candidates=labels[:8],
    )


def _resolve_via_phase8(
    raw: str, text: str, snapshot: Any
) -> ReferenceResolution | None:
    try:
        from neuron.brain import resolver as r8
        result = r8.resolve(raw, snapshot)
    except Exception:
        return None
    if not result.ambiguous and not result.references:
        return None
    if result.ask_user and (
        result.band == "low" or result.destructive_blocked or result.confidence < MEDIUM
    ):
        return ReferenceResolution(
            needs_clarification=True,
            clarification_prompt=result.ask_user,
            confidence=result.confidence,
            evidence="phase8_ask_user",
            source="phase8",
            candidates=[
                x
                for ref in result.references
                for x in (ref.candidates or ([ref.label] if ref.label else []))
            ][:8],
            phrase=_deixis_phrase(text),
        )
    if result.rewritten_request and result.confidence >= MEDIUM:
        ref0 = result.references[0] if result.references else None
        return ReferenceResolution(
            resolved_target=(ref0.label if ref0 else "") or result.rewritten_request,
            target_type=(ref0.entity_type if ref0 else "unknown"),
            confidence=result.confidence,
            evidence="phase8:" + (ref0.reason if ref0 else "rewrite"),
            source="phase8",
            rewritten_command=result.rewritten_request,
            tool_hint=(ref0.tool_hint if ref0 else ""),
            args_hint=dict(ref0.args_hint) if ref0 else {},
            phrase=_deixis_phrase(text),
        )
    return None


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _resolve_it_target(
    eng: Any, prefer: tuple[str, ...] = ("app", "window")
) -> tuple[str, float, str, str]:
    """Return (target, confidence, evidence, source)."""
    if eng is None:
        return "", 0.0, "no_engine", ""

    # 3) verified active app/window
    if "app" in prefer or "window" in prefer:
        app = (eng.world.active_app or "").strip()
        win = (eng.world.active_window or "").strip()
        if app and app.lower() not in ("?", "unknown"):
            return app, 0.9, "verified_active_app", "active_app"
        if win:
            # use first segment as app-ish
            short = win.split(" - ")[-1].strip() or win
            return short[:60], 0.75, "verified_active_window", "active_window"

    # 2) current task mentions an app
    goal = (eng.world.current_goal or "").lower()
    m = re.search(r"\b(?:open|focus|close|move)\s+([a-z0-9 .+-]{2,40})", goal)
    if m:
        return m.group(1).strip(), 0.7, "current_task", "current_task"

    # 4) recent entities
    for kind in prefer:
        for e in reversed(list(eng.recent_entities)):
            if e.kind == kind or (kind == "window" and e.kind == "app"):
                return e.name, 0.72, f"recent_entity:{e.kind}", "recent_entities"
    for e in reversed(list(eng.recent_entities)):
        if e.kind in ("app", "site", "file", "folder"):
            return e.name, 0.65, f"recent_entity:{e.kind}", "recent_entities"

    # 5) recent verified open/focus
    for a in reversed(list(eng.recent_actions)):
        if not a.verified or not a.ok:
            continue
        if a.action in ("open_app", "focus_app", "windows.open_app", "windows.focus_app"):
            name = (a.args or {}).get("name") or ""
            if name:
                return str(name), 0.8, "recent_verified_open_focus", "recent_actions"
        if a.action in ("open_website", "browser.open"):
            site = (a.args or {}).get("site") or (a.args or {}).get("url") or ""
            if site:
                return str(site), 0.78, "recent_verified_site", "recent_actions"

    # 6) conversation — last user "open X"
    for c in reversed(list(eng.recent_commands)):
        m = re.search(r"\b(?:open|focus|switch\s+to)\s+([a-z0-9 .+-]{2,40})", c.text.lower())
        if m:
            return m.group(1).strip(), 0.6, "recent_command", "conversation"

    return "", 0.0, "unresolved", ""


def _plausible_targets(eng: Any) -> list[str]:
    out: list[str] = []
    if eng is None:
        return out
    if eng.world.active_app:
        out.append(eng.world.active_app)
    for e in reversed(list(eng.recent_entities)):
        if e.kind in ("app", "site", "window") and e.name not in out:
            out.append(e.name)
        if len(out) >= 5:
            break
    for a in reversed(list(eng.recent_actions)):
        if a.verified and a.ok:
            n = (a.args or {}).get("name") or (a.args or {}).get("site")
            if n and str(n) not in out:
                out.append(str(n))
        if len(out) >= 5:
            break
    return out[:5]


def _last_verified_action(eng: Any) -> dict[str, Any] | None:
    if eng is None:
        return None
    for a in reversed(list(eng.recent_actions)):
        if a.verified and a.ok:
            return {"action": a.action, "args": dict(a.args or {}), "detail": a.detail}
    return None


def _action_to_command(act: dict[str, Any]) -> str:
    action = (act.get("action") or "").replace("windows.", "").replace("youtube.", "")
    args = act.get("args") or {}
    if action in ("open_app", "open"):
        return f"open {args.get('name') or 'it'}"
    if action in ("focus_app", "focus"):
        return f"focus {args.get('name') or 'it'}"
    if action in ("close_app", "close"):
        return f"close {args.get('name') or 'it'}"
    if action in ("search_site", "search"):
        return f"search {args.get('site') or 'youtube'} for {args.get('query') or ''}".strip()
    if action == "play_result":
        return f"play the {args.get('index') or 1} video"
    if action in ("skip_ad",):
        return "skip the ad"
    return action.replace("_", " ")


def _previous_app_entity(eng: Any) -> str:
    if eng is None:
        return ""
    apps = [e.name for e in eng.recent_entities if e.kind == "app"]
    if len(apps) >= 2:
        return apps[-2]
    if eng.world.active_app and apps:
        for a in reversed(apps):
            if a.lower() != eng.world.active_app.lower():
                return a
    return ""


def _recent_search_query(eng: Any) -> str:
    if eng is None:
        return ""
    for a in reversed(list(eng.recent_actions)):
        if a.verified and a.action in ("search_site", "youtube.search", "browser.search"):
            q = (a.args or {}).get("query") or ""
            if q:
                return str(q)
    for c in reversed(list(eng.recent_commands)):
        m = re.search(r"\bsearch(?:\s+\w+)?\s+for\s+(.+)$", c.text.lower())
        if m:
            return m.group(1).strip()
    return ""


def _latest_entity(eng: Any, kinds: tuple[str, ...] = ()) -> str:
    if eng is None:
        return ""
    for e in reversed(list(eng.recent_entities)):
        if not kinds or e.kind in kinds:
            return e.name
    return ""


def _youtube_context(eng: Any) -> bool:
    if eng is None:
        return False
    if "youtube" in (eng.world.scene or "").lower():
        return True
    if "youtube" in (eng.world.browser_url or "").lower():
        return True
    if "youtube" in (eng.world.active_window or "").lower():
        return True
    goal = (eng.world.current_goal or "").lower()
    if "youtube" in goal or "yt" in goal:
        return True
    for e in eng.recent_entities:
        if e.kind == "site" and "youtube" in e.name.lower():
            return True
    for c in eng.recent_commands:
        if "youtube" in c.text.lower() or "yt" in c.text.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _normalize_text(raw: str, intent: Any | None) -> str:
    if intent is not None:
        t = (getattr(intent, "normalized", None) or "").strip()
        if t:
            return t.lower()
    try:
        import nlu
        u = nlu.understand(raw or "")
        return (u.get("canonical") or u.get("cleaned") or raw or "").strip().lower()
    except Exception:
        return (raw or "").strip().lower()


def _has_ordinal(text: str) -> bool:
    return bool(
        re.search(
            r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous)\b",
            text or "",
            re.I,
        )
    )


def _parse_ordinal(text: str) -> tuple[str | None, int | None]:
    m = re.search(
        r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous)\b",
        text or "",
        re.I,
    )
    if not m:
        return None, None
    w = m.group(1).lower()
    return w, _ORDINALS.get(w)


def _is_monitor_relative(text: str) -> bool:
    return bool(re.search(r"\bother\s+(?:monitor|screen)\b|\bmonitor\s+\d+\b", text or "", re.I))


def _deixis_phrase(text: str) -> str:
    m = _DEIXIS.search(text or "")
    return m.group(0) if m else ""


def _clarify_prompt(text: str, cands: list[str]) -> str:
    if cands:
        return "Which one did you mean: " + ", ".join(cands) + "?"
    if re.search(r"\bclose\b", text):
        return "Close which window?"
    if re.search(r"\bmove\b", text):
        return "Move which window?"
    return "Which one did you mean?"
