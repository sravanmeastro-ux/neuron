"""V4.3 SemanticElementResolver — NL reference → UIElementState from DesktopWorldModel.

Does not rescan the desktop. Does not click. Does not replace V3 ReferenceResolver.
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.v4.resolve.parse import parse_reference
from neuron.v4.resolve.roles import (
    name_tokens_suggest_role,
    normalize_role,
    roles_compatible,
)
from neuron.v4.resolve.types import (
    ConfidenceBand,
    ElementCandidate,
    ElementReference,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
    ResolvedElement,
    RevalidateStatus,
    band_for,
)
from neuron.v4.world.model import DesktopWorldModel, get_world_model
from neuron.v4.world.models import DesktopState, UIElementState

# Score thresholds (documented in V4_3 doc)
HIGH = 0.75
MEDIUM = 0.45
AMBIGUITY_DELTA = 0.06


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _center(el: UIElementState) -> tuple[float, float] | None:
    b = el.bounds or {}
    if "center_x" in b and "center_y" in b:
        try:
            return float(b["center_x"]), float(b["center_y"])
        except (TypeError, ValueError):
            return None
    try:
        if b.get("left") is not None and b.get("width") is not None:
            return float(b["left"]) + float(b["width"]) / 2, float(b.get("top") or 0) + float(
                b.get("height") or 0
            ) / 2
    except (TypeError, ValueError):
        return None
    return None


def _sort_reading_order(elements: list[UIElementState]) -> list[UIElementState]:
    """Top-to-bottom, then left-to-right (spatial). Prefer attributes.path order if present."""

    def key(e: UIElementState):
        path = str((e.attributes or {}).get("path") or "")
        c = _center(e)
        if c:
            return (0, c[1] // 12, c[0] // 12, path, e.name or "")
        return (1, 0, 0, path, e.name or "")

    return sorted(elements, key=key)


class SemanticElementResolver:
    """Authoritative V4 semantic element resolution API."""

    def __init__(self, *, stale_after_s: float = 30.0):
        self.stale_after_s = float(stale_after_s)
        self._last: ResolutionResult | None = None

    @property
    def last(self) -> ResolutionResult | None:
        return self._last

    def resolve(
        self,
        reference: str | ElementReference,
        world: DesktopWorldModel | DesktopState | None = None,
        context: ResolutionContext | None = None,
        *,
        allow_stale: bool = False,
    ) -> ResolutionResult:
        t0 = time.perf_counter()
        ref = reference if isinstance(reference, ElementReference) else parse_reference(reference)
        ctx = context or ResolutionContext()
        state, wm = self._world_state(world)

        # Stale world?
        ts = state.timestamp or ctx.world_timestamp or 0.0
        max_age = ctx.max_world_age_s or self.stale_after_s
        if (
            not allow_stale
            and ts
            and (time.time() - float(ts)) > float(max_age)
            and not state.visible_elements
        ):
            result = ResolutionResult(
                status=ResolutionStatus.STALE_WORLD,
                reference=ref,
                evidence="world_stale_or_empty",
                needs_reobserve=True,
                clarification_prompt="I need a fresh look at the screen.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._last = result
            return result

        elements = list(state.visible_elements or [])
        if not elements:
            # Insufficient perception structure
            status = (
                ResolutionStatus.STALE_WORLD
                if not state.windows and not state.foreground_window
                else ResolutionStatus.INSUFFICIENT_CONTEXT
            )
            result = ResolutionResult(
                status=status,
                reference=ref,
                evidence="no_visible_elements",
                needs_reobserve=True,
                clarification_prompt="I don't see interactive elements yet.",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._last = result
            return result

        # Fill context defaults from world
        if not ctx.active_application and state.foreground_application:
            ctx.active_application = state.foreground_application.name
        if not ctx.active_window and state.foreground_window:
            ctx.active_window = state.foreground_window.title
        if ctx.active_monitor is None:
            ctx.active_monitor = state.active_monitor_id
        if not ctx.browser_url and state.browser:
            ctx.browser_url = state.browser.url or ""
            ctx.browser_page_type = state.browser.page_type or ""

        # Deixis path
        if ref.deixis and not ref.name_hint and not ref.role_hint and ref.ordinal is None:
            result = self._resolve_deixis(ref, elements, ctx, t0)
            self._remember(result, wm)
            return result

        # Candidate generation + filters
        pool = self._filter_context(elements, ref, ctx)
        if ref.role_hint:
            role_pool = [
                e
                for e in pool
                if roles_compatible(ref.role_hint, e.role)
                or roles_compatible(ref.role_hint, str((e.attributes or {}).get("control_type") or ""))
            ]
            # Prefer name-aligned for search / chrome buttons
            if role_pool:
                pool = role_pool
            elif ref.role_hint in ("video", "browser_result"):
                # No video-like candidates
                result = ResolutionResult(
                    status=ResolutionStatus.INSUFFICIENT_CONTEXT,
                    reference=ref,
                    evidence="no_video_candidates",
                    needs_reobserve=True,
                    clarification_prompt="I don't see video results on this page yet.",
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._last = result
                return result

        if ref.color:
            colored = [
                e
                for e in pool
                if ref.color in _norm(e.name)
                or ref.color in _norm(str((e.attributes or {}).get("color") or ""))
            ]
            if colored:
                pool = colored

        if ref.monitor_id is not None:
            mon_pool = [e for e in pool if e.monitor_id == ref.monitor_id]
            if mon_pool:
                pool = mon_pool

        # Relational: resolve anchor first among all elements
        relation_dist: dict[str, float] = {}
        if ref.relation and ref.relation_anchor:
            pool, relation_dist = self._apply_relation(pool, elements, ref)

        # Score
        scored = self._score_candidates(pool, ref, ctx, relation_dist=relation_dist)
        if not scored:
            result = ResolutionResult(
                status=ResolutionStatus.NOT_FOUND,
                reference=ref,
                evidence="no_candidates_after_filter",
                clarification_prompt=self._clarify_missing(ref, elements),
                latency_ms=(time.perf_counter() - t0) * 1000,
                candidates=[],
            )
            self._last = result
            return result

        # Ordinal AFTER semantic filtering
        if ref.ordinal is not None:
            ordered = _sort_reading_order([c.element for c in scored])
            # Keep score map
            score_map = {c.element.id: c for c in scored}
            ordered_cands = [score_map[e.id] for e in ordered if e.id in score_map]
            # If name/role scored, prefer ordered among those with score >= MEDIUM*0.5
            viable = [c for c in ordered_cands if c.score >= 0.2] or ordered_cands
            pick = self._pick_ordinal(viable, ref.ordinal)
            if pick is None:
                result = ResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    reference=ref,
                    candidates=viable[:8],
                    confidence=0.35,
                    confidence_band=ConfidenceBand.LOW,
                    evidence="ordinal_out_of_range",
                    clarification_prompt=self._clarify_ambiguous(ref, viable),
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._last = result
                return result
            # Boost ordinal certainty
            pick.score = min(1.0, max(pick.score, 0.85))
            pick.reasons.append(f"ordinal:{ref.ordinal_word or ref.ordinal}")
            scored = [pick] + [c for c in scored if c.element.id != pick.element.id]

        # Spatial AFTER semantic filtering
        if ref.position:
            scored = self._apply_spatial(scored, ref.position)

        scored.sort(key=lambda c: -c.score)
        top = scored[0]
        # Ambiguity — but relational closest-unique wins
        if len(scored) > 1 and abs(scored[0].score - scored[1].score) < AMBIGUITY_DELTA:
            unique_nearest = False
            if ref.relation and relation_dist:
                d0 = relation_dist.get(scored[0].element.id)
                d1 = relation_dist.get(scored[1].element.id)
                if d0 is not None and (d1 is None or d0 + 12 < d1):
                    unique_nearest = True
                    scored[0].reasons.append("relation_nearest")
                    scored[0].score = min(1.0, scored[0].score + 0.12)
            if not unique_nearest and (
                _norm(scored[0].element.name) == _norm(scored[1].element.name)
                or (scored[0].score >= MEDIUM and scored[1].score >= MEDIUM)
            ):
                result = ResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    reference=ref,
                    candidates=scored[:8],
                    confidence=min(scored[0].score, 0.5),
                    confidence_band=ConfidenceBand.LOW,
                    evidence="ambiguous_top_candidates",
                    clarification_prompt=self._clarify_ambiguous(ref, scored),
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
                self._last = result
                return result
            top = scored[0]

        conf = float(top.score)
        band = band_for(conf)
        if band is ConfidenceBand.LOW:
            result = ResolutionResult(
                status=ResolutionStatus.NOT_FOUND
                if conf < 0.25
                else ResolutionStatus.AMBIGUOUS,
                reference=ref,
                candidates=scored[:8],
                confidence=conf,
                confidence_band=band,
                evidence="low_confidence",
                clarification_prompt=self._clarify_ambiguous(ref, scored),
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._last = result
            return result

        resolved = ResolvedElement.from_ui(
            top.element,
            confidence=conf,
            raw_role=top.raw_role,
            normalized_role=top.normalized_role,
        )
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            reference=ref,
            resolved=resolved,
            candidates=scored[:8],
            confidence=conf,
            confidence_band=band,
            evidence=";".join(top.reasons) or "scored_match",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        self._remember(result, wm)
        self._last = result
        return result

    def revalidate(
        self,
        element_id: str,
        world: DesktopWorldModel | DesktopState | None = None,
        *,
        prior: ResolvedElement | None = None,
    ) -> RevalidateStatus:
        state, _ = self._world_state(world)
        if not element_id:
            return RevalidateStatus.UNCERTAIN
        hit = next((e for e in state.visible_elements if e.id == element_id), None)
        if hit is None:
            # Try semantic fingerprint match if prior known
            if prior and prior.name:
                soft = [
                    e
                    for e in state.visible_elements
                    if _norm(e.name) == _norm(prior.name)
                    and normalize_role(e.role) == normalize_role(prior.role)
                ]
                if soft:
                    return RevalidateStatus.CHANGED
            return RevalidateStatus.MISSING
        if prior and prior.bounds and hit.bounds:
            if prior.bounds != hit.bounds:
                # same id, moved
                return RevalidateStatus.MOVED
            if _norm(prior.name) != _norm(hit.name) or normalize_role(prior.role) != normalize_role(
                hit.role
            ):
                return RevalidateStatus.CHANGED
        return RevalidateStatus.STILL_VALID

    # ------------------------------------------------------------------ internals

    def _world_state(
        self, world: DesktopWorldModel | DesktopState | None
    ) -> tuple[DesktopState, DesktopWorldModel | None]:
        if isinstance(world, DesktopState):
            return world, None
        if isinstance(world, DesktopWorldModel):
            return world.current, world
        wm = get_world_model()
        return wm.current, wm

    def _filter_context(
        self,
        elements: list[UIElementState],
        ref: ElementReference,
        ctx: ResolutionContext,
    ) -> list[UIElementState]:
        pool = list(elements)
        app = (ref.application or ctx.active_application or "").lower()
        if app:
            app_pool = [
                e
                for e in pool
                if app in (e.application or "").lower() or app in (e.window or "").lower()
            ]
            if app_pool:
                pool = app_pool
        return pool

    def _score_candidates(
        self,
        pool: list[UIElementState],
        ref: ElementReference,
        ctx: ResolutionContext,
        *,
        relation_dist: dict[str, float] | None = None,
    ) -> list[ElementCandidate]:
        out: list[ElementCandidate] = []
        name_q = _norm(ref.name_hint)
        relation_dist = relation_dist or {}
        for e in pool:
            raw_role = str((e.attributes or {}).get("control_type") or e.role or "")
            norm_role = normalize_role(e.role or raw_role)
            score = 0.15 * float(e.confidence or 0.5)
            reasons: list[str] = []

            if ref.role_hint:
                if roles_compatible(ref.role_hint, e.role) or roles_compatible(
                    ref.role_hint, raw_role
                ):
                    score += 0.25
                    reasons.append(f"role:{ref.role_hint}")
                else:
                    continue  # hard filter already done, but skip mismatches
                bonus = name_tokens_suggest_role(e.name, ref.role_hint)
                score += bonus
                if bonus > 0:
                    reasons.append("role_name_align")
                if bonus < 0:
                    reasons.append("role_name_penalty")
                    if score < 0.2:
                        continue
                # Prefer dedicated Search field over omnibox "Address and search bar"
                if ref.role_hint == "search_box":
                    nlow = _norm(e.name)
                    aid = _norm(str((e.attributes or {}).get("automation_id") or ""))
                    if nlow == "search" or aid == "search":
                        score += 0.2
                        reasons.append("exact_search_field")
                    if "address" in nlow or "omnibox" in nlow or aid == "address":
                        score -= 0.18
                        reasons.append("omnibox_penalty")

            if name_q:
                ns = _text_score(name_q, e.name, e.text, str((e.attributes or {}).get("automation_id") or ""))
                if ns <= 0 and ref.role_hint:
                    # role-only ok
                    pass
                elif ns <= 0:
                    continue
                else:
                    score += 0.45 * ns
                    reasons.append(f"text:{ns:.2f}")
                    # Prefer exact / near-exact over long supersets for consequential words
                    if _norm(e.name) == name_q:
                        score += 0.2
                        reasons.append("exact_name")
                    elif name_q in _norm(e.name) and len(_norm(e.name)) > len(name_q) + 12:
                        score -= 0.15
                        reasons.append("long_superset_penalty")

            if ctx.active_application and ctx.active_application.lower() in (
                e.application or ""
            ).lower():
                score += 0.05
                reasons.append("app_ctx")
            if ctx.active_window and _norm(ctx.active_window)[:20] in _norm(e.window):
                score += 0.05
                reasons.append("window_ctx")
            if e.id and e.id == ctx.last_element_id:
                score += 0.1
                reasons.append("last_element")
            if e.id and e.id in (ctx.last_result_ids or []):
                score += 0.08
                reasons.append("last_result_set")

            if e.source == "uia":
                score += 0.03
            elif e.source == "ocr":
                score -= 0.05

            if e.id in relation_dist:
                dist = relation_dist[e.id]
                # Closer to anchor → stronger (cap boost)
                prox = max(0.0, 1.0 - (dist / 280.0))
                score += 0.25 * prox
                reasons.append(f"relation_dist:{dist:.0f}")

            score = max(0.0, min(1.0, score))
            if score >= 0.15 or (ref.role_hint and not name_q):
                if ref.role_hint and not name_q and "role:" in ";".join(reasons):
                    score = max(score, 0.55)
                out.append(
                    ElementCandidate(
                        element=e,
                        score=score,
                        reasons=reasons,
                        raw_role=raw_role,
                        normalized_role=norm_role,
                    )
                )
        return out

    def _apply_relation(
        self,
        pool: list[UIElementState],
        all_elements: list[UIElementState],
        ref: ElementReference,
    ) -> tuple[list[UIElementState], dict[str, float]]:
        anchor_q = _norm(ref.relation_anchor)
        anchors = [
            e
            for e in all_elements
            if anchor_q and (anchor_q in _norm(e.name) or _norm(e.name) == anchor_q)
        ]
        if not anchors:
            return pool, {}
        anchor = anchors[0]
        ac = _center(anchor)
        if not ac:
            return pool, {}
        ax, ay = ac
        scored: list[tuple[float, UIElementState]] = []
        for e in pool:
            if e.id == anchor.id:
                continue
            c = _center(e)
            if not c:
                continue
            ex, ey = c
            dx, dy = ex - ax, ey - ay
            dist = (dx * dx + dy * dy) ** 0.5
            ok = False
            if ref.relation == "above" and dy < -8:
                ok = True
            elif ref.relation == "below" and dy > 8:
                ok = True
            elif ref.relation == "left_of" and dx < -8:
                ok = True
            elif ref.relation == "right_of" and dx > 8:
                ok = True
            elif ref.relation in ("next_to", "near") and dist < 280:
                ok = True
            if ok:
                scored.append((dist, e))
        scored.sort(key=lambda x: x[0])
        if not scored:
            return pool, {}
        dist_map = {e.id: d for d, e in scored}
        return [e for _, e in scored], dist_map

    def _apply_spatial(
        self, scored: list[ElementCandidate], position: str
    ) -> list[ElementCandidate]:
        if not scored:
            return scored
        with_c = [(c, _center(c.element)) for c in scored]
        with_c = [(c, cen) for c, cen in with_c if cen]
        if not with_c:
            return scored
        xs = [cen[0] for _, cen in with_c]
        ys = [cen[1] for _, cen in with_c]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        mid_x = (min_x + max_x) / 2
        mid_y = (min_y + max_y) / 2

        def ok(cen: tuple[float, float]) -> bool:
            x, y = cen
            if position == "left":
                return x <= mid_x
            if position == "right":
                return x >= mid_x
            if position == "top":
                return y <= mid_y
            if position == "bottom":
                return y >= mid_y
            if position == "center":
                return abs(x - mid_x) <= (max_x - min_x) * 0.35 and abs(y - mid_y) <= (
                    max_y - min_y
                ) * 0.35
            if position == "top_left":
                return x <= mid_x and y <= mid_y
            if position == "top_right":
                return x >= mid_x and y <= mid_y
            if position == "bottom_left":
                return x <= mid_x and y >= mid_y
            if position == "bottom_right":
                return x >= mid_x and y >= mid_y
            return True

        filtered = []
        for c, cen in with_c:
            if ok(cen):
                c.reasons.append(f"spatial:{position}")
                c.score = min(1.0, c.score + 0.08)
                filtered.append(c)
        if not filtered:
            return scored
        # For leftmost/rightmost style — pick extreme
        if position == "left":
            filtered.sort(key=lambda c: _center(c.element)[0])
            filtered[0].score = min(1.0, filtered[0].score + 0.12)
        elif position == "right":
            filtered.sort(key=lambda c: -_center(c.element)[0])
            filtered[0].score = min(1.0, filtered[0].score + 0.12)
        elif position == "top":
            filtered.sort(key=lambda c: _center(c.element)[1])
            filtered[0].score = min(1.0, filtered[0].score + 0.12)
        elif position == "bottom":
            filtered.sort(key=lambda c: -_center(c.element)[1])
            filtered[0].score = min(1.0, filtered[0].score + 0.12)
        return filtered

    def _pick_ordinal(
        self, cands: list[ElementCandidate], ordinal: int
    ) -> ElementCandidate | None:
        if not cands:
            return None
        if ordinal == -1:
            return cands[-1]
        idx = int(ordinal) - 1
        if idx < 0 or idx >= len(cands):
            return None
        return cands[idx]

    def _resolve_deixis(
        self,
        ref: ElementReference,
        elements: list[UIElementState],
        ctx: ResolutionContext,
        t0: float,
    ) -> ResolutionResult:
        # Priority: last resolved → last result set → focused → ambiguous
        candidates: list[ElementCandidate] = []
        if ctx.last_element_id:
            el = next((e for e in elements if e.id == ctx.last_element_id), None)
            if el:
                candidates.append(
                    ElementCandidate(
                        element=el,
                        score=0.88,
                        reasons=["deixis:last_element"],
                        raw_role=el.role,
                        normalized_role=normalize_role(el.role),
                    )
                )
        if not candidates and ctx.last_result_ids:
            for eid in ctx.last_result_ids[:3]:
                el = next((e for e in elements if e.id == eid), None)
                if el:
                    candidates.append(
                        ElementCandidate(
                            element=el,
                            score=0.7,
                            reasons=["deixis:last_result_set"],
                            raw_role=el.role,
                            normalized_role=normalize_role(el.role),
                        )
                    )
        if not candidates and ctx.focused_element_id:
            el = next((e for e in elements if e.id == ctx.focused_element_id), None)
            if el:
                candidates.append(
                    ElementCandidate(
                        element=el,
                        score=0.8,
                        reasons=["deixis:focused"],
                        raw_role=el.role,
                        normalized_role=normalize_role(el.role),
                    )
                )
        if not candidates:
            # buttons only if exactly one interactive?
            buttons = [e for e in elements if normalize_role(e.role) == "button"]
            if len(buttons) == 1:
                el = buttons[0]
                candidates.append(
                    ElementCandidate(
                        element=el,
                        score=0.6,
                        reasons=["deixis:sole_button"],
                        raw_role=el.role,
                        normalized_role="button",
                    )
                )
            else:
                return ResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS
                    if len(buttons) > 1
                    else ResolutionStatus.INSUFFICIENT_CONTEXT,
                    reference=ref,
                    candidates=[
                        ElementCandidate(
                            element=e,
                            score=0.4,
                            reasons=["deixis:ambiguous"],
                            normalized_role=normalize_role(e.role),
                            raw_role=e.role,
                        )
                        for e in buttons[:6]
                    ],
                    confidence=0.3,
                    confidence_band=ConfidenceBand.LOW,
                    evidence="deixis_ambiguous",
                    clarification_prompt="Which one do you mean?",
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )

        top = max(candidates, key=lambda c: c.score)
        if top.score < MEDIUM:
            return ResolutionResult(
                status=ResolutionStatus.AMBIGUOUS,
                reference=ref,
                candidates=candidates,
                confidence=top.score,
                confidence_band=band_for(top.score),
                evidence="deixis_low_confidence",
                clarification_prompt="Which one do you mean?",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        resolved = ResolvedElement.from_ui(
            top.element,
            confidence=top.score,
            raw_role=top.raw_role,
            normalized_role=top.normalized_role,
        )
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            reference=ref,
            resolved=resolved,
            candidates=candidates,
            confidence=top.score,
            confidence_band=band_for(top.score),
            evidence=";".join(top.reasons),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    def _remember(self, result: ResolutionResult, wm: DesktopWorldModel | None) -> None:
        self._last = result
        if not result.ok or not result.resolved or wm is None:
            return
        # Stash on world raw for later deixis (non-secret metadata only)
        try:
            wm.current.raw["last_resolved_element_id"] = result.resolved.element_id
            wm.current.raw["last_resolved_role"] = result.resolved.role
            wm.current.raw["last_resolved_name"] = (result.resolved.name or "")[:80]
        except Exception:
            pass

    def _clarify_ambiguous(self, ref: ElementReference, scored: list[ElementCandidate]) -> str:
        labels = []
        for c in scored[:5]:
            n = (c.element.name or c.normalized_role or "?").strip()
            if n:
                labels.append(n[:40])
        if labels:
            return "Which one? " + "; ".join(labels)
        return f"Which {ref.role_hint or 'element'} did you mean?"

    def _clarify_missing(self, ref: ElementReference, elements: list[UIElementState]) -> str:
        labels = [e.name for e in elements if e.name][:6]
        if labels:
            return "I couldn't find that. Visible: " + "; ".join(labels)
        return "I couldn't find that element."


def _text_score(query: str, name: str, text: str, automation_id: str) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    n = _norm(name)
    t = _norm(text)
    a = _norm(automation_id)
    if not n and not t and not a:
        return 0.0
    if q == n or q == t:
        return 1.0
    if q == a or q in a:
        return 0.85
    if n.startswith(q) or t.startswith(q):
        return 0.9
    if q in n or q in t:
        # penalize long containers
        host = n if q in n else t
        ratio = len(q) / max(1, len(host))
        return 0.55 + 0.35 * ratio
    qtoks = [w for w in q.split() if len(w) > 1]
    if not qtoks:
        return 0.0
    host = f"{n} {t} {a}"
    hits = sum(1 for w in qtoks if w in host)
    return 0.5 * (hits / len(qtoks)) if hits else 0.0


def context_from_engine(engine: Any = None, world: DesktopWorldModel | None = None) -> ResolutionContext:
    """Build ResolutionContext from ContextEngine + DesktopWorldModel."""
    ctx = ResolutionContext()
    wm = world or get_world_model()
    st = wm.current
    ctx.world_timestamp = st.timestamp
    if st.foreground_application:
        ctx.active_application = st.foreground_application.name
    if st.foreground_window:
        ctx.active_window = st.foreground_window.title
    ctx.active_monitor = st.active_monitor_id
    if st.browser:
        ctx.browser_url = st.browser.url or ""
        ctx.browser_page_type = st.browser.page_type or ""
    ctx.last_element_id = str((st.raw or {}).get("last_resolved_element_id") or "")
    ctx.last_element_name = str((st.raw or {}).get("last_resolved_name") or "")
    ctx.last_element_role = str((st.raw or {}).get("last_resolved_role") or "")
    try:
        from neuron.v3.context_engine import get_engine
        eng = engine or get_engine()
        if eng is not None:
            ctx.task = str(getattr(eng.world, "current_goal", "") or "")
            ctx.last_action = str(getattr(eng.world, "last_action", "") or "")
    except Exception:
        pass
    return ctx


_RESOLVER: SemanticElementResolver | None = None


def get_semantic_resolver() -> SemanticElementResolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = SemanticElementResolver()
    return _RESOLVER


def reset_semantic_resolver() -> SemanticElementResolver:
    global _RESOLVER
    _RESOLVER = SemanticElementResolver()
    return _RESOLVER


def resolve(
    reference: str,
    world: DesktopWorldModel | DesktopState | None = None,
    context: ResolutionContext | None = None,
    **kwargs: Any,
) -> ResolutionResult:
    """Module-level convenience → SemanticElementResolver.resolve."""
    return get_semantic_resolver().resolve(reference, world=world, context=context, **kwargs)
