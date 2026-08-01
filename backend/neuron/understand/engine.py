"""Intent Understanding Engine — semantic rewrite → FastIntentRouter.

Pipeline (local, no LLM, no heavy model):
  Speech text
  → nlu clean
  → synonym / paraphrase
  → deixis + chain context
  → entity extraction
  → embedding intent classification
  → confidence band (high / medium / low)
  → rewritten canonical command

FastIntentRouter remains the primary executor.
AgentLoop is fallback for low confidence / clarify / complex.
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.understand.embeddings import cosine, embed_from_cache
from neuron.understand.entities import extract_entities
from neuron.understand import context_mem
from neuron.understand.synonyms import apply_paraphrase, canonicalize_app
from neuron.understand.types import SemanticUnderstanding

# Intent prototypes for embedding classification (canonical phrases)
_INTENT_PROTOTYPES: dict[str, list[str]] = {
    "OPEN_APPLICATION": [
        "open chrome", "launch blender", "start notepad", "run steam",
        "open the browser", "bring up discord", "open vscode",
    ],
    "CLOSE_APPLICATION": [
        "close chrome", "quit notepad", "exit blender", "close that",
    ],
    "FOCUS_APPLICATION": [
        "focus chrome", "switch to notepad", "bring blender to front",
    ],
    "OPEN_WEBSITE": [
        "open youtube", "go to youtube", "take me to youtube", "open google",
    ],
    "YOUTUBE_SEARCH": [
        "search youtube for blender tutorials",
        "youtube search unreal engine",
        "find blender tutorials on youtube",
    ],
    "WEB_SEARCH": [
        "search the web for news", "google for python tips",
    ],
    "SEARCH": [
        "search for blender tutorials", "find unreal engine",
    ],
    "VOLUME": [
        "volume up", "volume down", "mute", "unmute", "louder", "quieter",
    ],
    "WINDOW": [
        "maximize", "minimize", "make it bigger", "show desktop",
    ],
    "MOVE_MONITOR": [
        "move chrome to monitor 2", "put notepad on monitor one",
    ],
    "MEDIA": [
        "play", "pause", "next track", "previous song",
    ],
    "CLIPBOARD": [
        "copy", "paste", "undo", "redo",
    ],
    "SYSTEM": [
        "lock the pc", "screenshot",
    ],
    "PLAY_RESULT": [
        "play the first video", "play second one",
    ],
    "COMPLEX": [
        "summarize this document", "write an email", "explain this code",
        "research this topic", "analyze this image",
    ],
}

_PROTOTYPE_VECS: dict[str, Any] | None = None


def _prototype_vecs() -> dict[str, Any]:
    global _PROTOTYPE_VECS
    if _PROTOTYPE_VECS is None:
        import numpy as np
        out = {}
        for intent, phrases in _INTENT_PROTOTYPES.items():
            mats = [embed_from_cache(p) for p in phrases]
            out[intent] = np.mean(np.stack(mats, axis=0), axis=0)
            n = float(np.linalg.norm(out[intent]))
            if n > 1e-8:
                out[intent] = out[intent] / n
        _PROTOTYPE_VECS = out
    return _PROTOTYPE_VECS


def _band(conf: float) -> str:
    if conf >= 0.82:
        return "high"
    if conf >= 0.55:
        return "medium"
    return "low"


def _score_intents(text: str) -> dict[str, float]:
    vec = embed_from_cache(text)
    scores = {k: cosine(vec, v) for k, v in _prototype_vecs().items()}
    return scores


def _compose_command(
    text: str,
    intent_id: str,
    entities: list,
) -> str:
    """Build a FastIntentRouter-friendly canonical string."""
    app = next((e.value for e in entities if e.kind == "application"), "")
    site = next((e.value for e in entities if e.kind == "website"), "")
    query = next((e.value for e in entities if e.kind == "query"), "")
    monitor = next((e.value for e in entities if e.kind == "monitor"), "")
    ordinal = next((e.value for e in entities if e.kind == "ordinal"), "")

    if intent_id == "YOUTUBE_SEARCH" and query:
        return f"search youtube for {query}"
    if intent_id == "WEB_SEARCH" and query:
        return f"search the web for {query}"
    if intent_id == "SEARCH" and query:
        if site == "youtube":
            return f"search youtube for {query}"
        return f"search for {query}"
    if intent_id == "OPEN_WEBSITE" and site:
        return f"open {site}"
    if intent_id == "OPEN_APPLICATION" and app:
        return f"open {canonicalize_app(app)}"
    if intent_id == "CLOSE_APPLICATION" and app:
        return f"close {canonicalize_app(app)}"
    if intent_id == "FOCUS_APPLICATION" and app:
        return f"focus {canonicalize_app(app)}"
    if intent_id == "MOVE_MONITOR" and app and monitor:
        return f"move {canonicalize_app(app)} to monitor {monitor}"
    if intent_id == "PLAY_RESULT" and ordinal:
        word = {"1st": "first", "2nd": "second", "3rd": "third"}.get(ordinal, ordinal)
        return f"play the {word} video"
    if intent_id == "VOLUME":
        low = text.lower()
        if "mute" in low or "silence" in low:
            return "unmute" if "unmute" in low else "mute"
        if "down" in low or "quiet" in low:
            return "volume down"
        return "volume up"
    # Default: keep paraphrased text
    return text


def understand(raw: str, *, refresh_desktop: bool = True) -> SemanticUnderstanding:
    t0 = time.perf_counter()
    import nlu

    info = nlu.understand(raw or "")
    cleaned = info.get("canonical") or info.get("cleaned") or (raw or "").strip()
    context_used: list[str] = []

    # 1) Synonym / paraphrase
    paraphrased, hint, rule_conf = apply_paraphrase(cleaned)
    work = paraphrased or cleaned

    # 2) Desktop memory + deixis + chains
    mem = context_mem.refresh_desktop_snapshot() if refresh_desktop else context_mem.get_memory()
    work, used = context_mem.resolve_deixis(work, mem)
    context_used.extend(used)
    work, used2 = context_mem.chain_rewrite(work, mem)
    context_used.extend(used2)

    # Re-paraphrase after deixis (open it → open chrome)
    work2, hint2, rule_conf2 = apply_paraphrase(work)
    if rule_conf2 >= rule_conf:
        work, hint, rule_conf = work2, hint2 or hint, max(rule_conf, rule_conf2)

    # 3) Entities
    entities = extract_entities(work)

    # 4) Embedding classification
    scores = _score_intents(work)
    # Prefer rule hint when strong
    best_embed = max(scores.items(), key=lambda kv: kv[1]) if scores else ("UNKNOWN", 0.0)
    intent_id = hint if hint != "UNKNOWN" else best_embed[0]
    embed_conf = float(best_embed[1])

    # Boost SEARCH → YOUTUBE_SEARCH when site entity present
    if intent_id in ("SEARCH", "WEB_SEARCH") and any(
        e.kind == "website" and e.value == "youtube" for e in entities
    ):
        intent_id = "YOUTUBE_SEARCH"

    if any(e.kind == "monitor" for e in entities) and any(
        e.kind == "application" for e in entities
    ):
        if re.search(r"\b(?:move|put|send)\b", work, re.I):
            intent_id = "MOVE_MONITOR"

    # Exact known desktop commands — high confidence regardless of embed
    _KNOWN_EXACT = {
        "volume up": ("VOLUME", 0.97),
        "volume down": ("VOLUME", 0.97),
        "mute": ("VOLUME", 0.97),
        "unmute": ("VOLUME", 0.97),
        "copy": ("CLIPBOARD", 0.97),
        "paste": ("CLIPBOARD", 0.97),
        "undo": ("CLIPBOARD", 0.97),
        "redo": ("CLIPBOARD", 0.97),
    }
    exact = _KNOWN_EXACT.get(work.lower().strip())
    if exact:
        intent_id, conf = exact[0], exact[1]
    else:
        conf = max(rule_conf, embed_conf)
        if hint != "UNKNOWN":
            conf = max(conf, 0.5 * rule_conf + 0.5 * max(embed_conf, 0.4))
            conf = max(conf, rule_conf)
        if context_used:
            conf = min(1.0, conf + 0.05)

    # Complex language → low band force AgentLoop
    if intent_id == "COMPLEX" or (scores.get("COMPLEX", 0) > 0.72 and hint == "UNKNOWN"):
        intent_id = "COMPLEX"
        conf = min(conf, 0.45)

    rewritten = _compose_command(work, intent_id, entities)
    # Final nlu polish
    rewritten = nlu.polish(rewritten) or rewritten

    band = _band(conf)
    clarify = None
    if band == "medium" and intent_id in (
        "OPEN_APPLICATION", "FOCUS_APPLICATION", "CLOSE_APPLICATION"
    ):
        apps = [e.value for e in entities if e.kind == "application"]
        if not apps:
            clarify = "Which app did you mean?"
            band = "medium"

    # High band requires a concrete rewritten command
    if band == "high" and (not rewritten or rewritten == cleaned and hint == "UNKNOWN" and embed_conf < 0.82):
        if embed_conf < 0.82 and rule_conf < 0.82:
            band = "medium" if conf >= 0.55 else "low"

    result = SemanticUnderstanding(
        raw=raw or "",
        cleaned=cleaned,
        rewritten=rewritten,
        intent_id=intent_id,
        intent_label=intent_id.replace("_", " ").title(),
        confidence=float(conf),
        band=band,
        entities=entities,
        context_used=context_used,
        clarify_prompt=clarify,
        embedding_scores={k: round(v, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:6]},
        latency_ms=(time.perf_counter() - t0) * 1000.0,
    )
    return result


def understand_for_router(raw: str) -> tuple[str, SemanticUnderstanding]:
    """
    Returns text to feed FastIntentRouter + understanding record.

    high → rewritten command
    medium + clarify → original (caller may ask)
    low / COMPLEX → original (AgentLoop)
    """
    u = understand(raw)
    if u.band == "high" and u.rewritten:
        return u.rewritten, u
    if u.band == "medium" and u.rewritten and not u.clarify_prompt:
        # Medium without clarify still try rewritten (FastRouter + fallback)
        return u.rewritten, u
    return (u.cleaned or raw or ""), u
