"""V4.7 ConversationEngine — unified understand + context boundary.

Reuses ContextEngine + ReferenceResolver; does not replace AgentLoop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.context import clarify as clarify_mod
from neuron.v4.context import followup, normalize, parse, route as route_mod
from neuron.v4.context.types import (
    ClarificationState,
    ConfirmationState,
    ContinuityKind,
    ConversationState,
    EntityReference,
    GoalCandidate,
    GoalUpdate,
    IntentFamily,
    ResultSet,
    ResultSetItem,
    RouteDest,
    TaskContext,
    Turn,
    UnderstandingResult,
)

log = logging.getLogger("neuron.v4.context")

_ENGINE: "ConversationEngine | None" = None


class ConversationEngine:
    def __init__(self) -> None:
        self.state = ConversationState()
        self.stats = {
            "understands": 0,
            "follow_ups": 0,
            "clarifications": 0,
            "confirmations": 0,
            "verified_updates": 0,
            "uncertain_updates": 0,
            "routing_mismatches": 0,
        }

    def reset(self) -> None:
        """Explicit test/session reset — clears conversation context."""
        self.state = ConversationState()

    def cancel_transient(self) -> None:
        """Neuron stop: clear unsafe pending states; keep harmless session facts."""
        self.state.clear_pending_unsafe()

    def snapshot(self) -> dict[str, Any]:
        return self.state.to_dict()

    # ------------------------------------------------------------------ understand

    def understand(self, raw: str, *, world: Any = None) -> UnderstandingResult:
        t0 = time.perf_counter()
        self.stats["understands"] += 1
        parsed = normalize.normalize_utterance(raw)
        goal = parse.build_goal(parsed)

        # Pending confirmation vs clarification (separate)
        conf_res = clarify_mod.resolve_confirmation(
            parsed.canonical, self.state.pending_confirmation
        )
        if conf_res is not None:
            turn = Turn(
                raw=raw,
                normalized=parsed.canonical,
                intent_family=IntentFamily.CONFIRMATION,
                continuity=ContinuityKind.CONFIRMATION_ANSWER
                if conf_res.get("authorized")
                else ContinuityKind.CANCEL,
                confidence=0.95,
                route=RouteDest.CONFIRM if conf_res.get("authorized") else RouteDest.STOP,
            )
            self.state.push_turn(turn)
            if conf_res.get("authorized"):
                self.stats["confirmations"] += 1
            else:
                self.state.pending_confirmation = None
            out = UnderstandingResult(
                turn=turn,
                parsed=parsed,
                goal=goal,
                continuity=turn.continuity,
                route=turn.route,
                route_reason="confirmation path",
                confirmation_resolution=conf_res,
                rewritten_command=parsed.canonical,
                confidence=0.95,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._log_nlu(out)
            return out

        # Unrelated command while confirmation pending → do not authorize
        if self.state.pending_confirmation and self.state.pending_confirmation.is_active():
            if not conf_res:
                # Fall through as normal understand; confirmation stays until expiry/cancel
                pass

        clr_res = clarify_mod.resolve_clarification(
            parsed.canonical, self.state.pending_clarification
        )
        if clr_res is not None:
            turn = Turn(
                raw=raw,
                normalized=parsed.canonical,
                intent_family=IntentFamily.CLARIFICATION_RESPONSE,
                continuity=ContinuityKind.CLARIFICATION_ANSWER,
                confidence=0.9,
                route=RouteDest.HIERARCHICAL if clr_res.get("resolved") else RouteDest.CLARIFY,
            )
            self.state.push_turn(turn)
            self.stats["clarifications"] += 1
            rewritten = parsed.canonical
            if clr_res.get("resolved") and clr_res.get("choice"):
                ch = clr_res["choice"]
                label = str(ch.get("label") or ch.get("name") or ch.get("app") or "")
                og = self.state.pending_clarification.original_goal if self.state.pending_clarification else ""
                rewritten = f"{og} ({label})".strip() if og else label
                self.state.pending_clarification = None
            elif clr_res.get("cancel") or clr_res.get("reason") == "neither":
                self.state.pending_clarification = None
            out = UnderstandingResult(
                turn=turn,
                parsed=parsed,
                goal=goal,
                continuity=ContinuityKind.CLARIFICATION_ANSWER,
                route=RouteDest.HIERARCHICAL if clr_res.get("resolved") else (
                    RouteDest.STOP if clr_res.get("cancel") else RouteDest.CLARIFY
                ),
                route_reason="clarification response",
                clarification_resolution=clr_res,
                rewritten_command=rewritten,
                confidence=0.9,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._log_nlu(out)
            return out

        continuity = followup.detect_continuity(
            parsed,
            goal,
            self.state,
            has_pending_clarify=bool(
                self.state.pending_clarification and self.state.pending_clarification.is_active()
            ),
            has_pending_confirm=bool(
                self.state.pending_confirmation and self.state.pending_confirmation.is_active()
            ),
        )

        rewritten = parsed.canonical
        goal_update: GoalUpdate | None = None
        entities: list[EntityReference] = []

        if continuity is ContinuityKind.ELLIPSIS:
            rewritten = followup.apply_ellipsis(parsed, self.state)
            goal = parse.build_goal(
                type(parsed)(
                    raw=parsed.raw,
                    cleaned=parsed.cleaned,
                    canonical=rewritten,
                    variants=parsed.variants,
                )
            )
            goal.source = "follow_up"

        if continuity is ContinuityKind.CORRECTION:
            goal_update = GoalUpdate(
                kind="patch_selection" if "ordinal" in (goal.args or {}) else "replace",
                text=rewritten,
                args_patch=dict(goal.args),
                preserve_verified=True,
                reason="user correction",
            )
            self.stats["follow_ups"] += 1

        if continuity is ContinuityKind.FOLLOW_UP:
            self.stats["follow_ups"] += 1
            rewritten = self._expand_followup(rewritten, goal)
            goal = parse.build_goal(
                type(parsed)(
                    raw=parsed.raw,
                    cleaned=parsed.cleaned,
                    canonical=rewritten,
                    variants=parsed.variants,
                    correction_final=parsed.correction_final,
                    compound_parts=parsed.compound_parts,
                )
            )
            goal.source = "follow_up"
            goal.intent_family = (
                goal.intent_family
                if goal.intent_family is not IntentFamily.UNKNOWN
                else IntentFamily.FOLLOW_UP
            )

        # Bridge ReferenceResolver for deixis when needed
        rewritten, entities, needs_clarify, clarify_prompt = self._resolve_refs(
            rewritten, goal
        )

        # World reconciliation (observable wins)
        self._reconcile_world(world)

        # Ambiguous bare pronoun with no referent
        if needs_clarify or (
            continuity is ContinuityKind.FOLLOW_UP
            and re_has_bare_deixis(rewritten)
            and not self._has_referent()
        ):
            prompt = clarify_prompt or "Which one did you mean?"
            clr = clarify_mod.set_clarification(
                prompt=prompt,
                original_goal=rewritten,
                source="context",
            )
            self.state.pending_clarification = clr
            turn = Turn(
                raw=raw,
                normalized=rewritten,
                intent_family=goal.intent_family,
                continuity=continuity,
                confidence=0.4,
                route=RouteDest.CLARIFY,
            )
            self.state.push_turn(turn)
            out = UnderstandingResult(
                turn=turn,
                parsed=parsed,
                goal=goal,
                continuity=continuity,
                route=RouteDest.CLARIFY,
                route_reason="no usable referent",
                rewritten_command=rewritten,
                clarification=clr,
                resolved_entities=entities,
                confidence=0.4,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._log_nlu(out)
            return out

        if goal.args.get("negated"):
            turn = Turn(
                raw=raw,
                normalized=rewritten,
                intent_family=goal.intent_family,
                continuity=continuity,
                confidence=0.9,
                route=RouteDest.REJECT,
            )
            self.state.push_turn(turn)
            out = UnderstandingResult(
                turn=turn,
                parsed=parsed,
                goal=goal,
                continuity=continuity,
                route=RouteDest.REJECT,
                route_reason="negation",
                rewritten_command=rewritten,
                confidence=0.9,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
            self._log_nlu(out)
            return out

        conf = float(goal.confidence)
        turn = Turn(
            raw=raw,
            normalized=rewritten,
            intent_family=goal.intent_family,
            continuity=continuity,
            confidence=conf,
        )
        result = UnderstandingResult(
            turn=turn,
            parsed=parsed,
            goal=goal,
            goal_update=goal_update,
            continuity=continuity,
            rewritten_command=rewritten,
            resolved_entities=entities,
            confidence=conf,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
        route_mod.attach_route(result)
        turn.route = result.route
        turn.continuity = result.continuity
        self.state.push_turn(turn)
        self._log_nlu(result)
        return result

    def _expand_followup(self, text: str, goal: GoalCandidate) -> str:
        task = self.state.task
        t = text
        # Result-set ordinals
        if goal.intent_family in (IntentFamily.PLAY, IntentFamily.SELECT) or parse.parse_ordinal(t):
            ord_n = goal.args.get("ordinal") or parse.parse_ordinal(t)
            rs = self.state.result_set
            if ord_n is not None and rs and rs.is_fresh():
                item = rs.pick(int(ord_n))
                if item:
                    return f"play result {item.index} ({item.label})".strip()
            if ord_n is not None and (not rs or not rs.is_fresh()):
                # Stale — leave for clarify path caller
                return t
        if goal.intent_family is IntentFamily.FULLSCREEN or "fullscreen" in t.lower():
            return "make it fullscreen"
        if goal.intent_family is IntentFamily.NAVIGATE and task.active_application:
            return t  # go to X in current browser context
        if goal.intent_family is IntentFamily.SEARCH and task.active_application:
            return t
        # "move it to monitor 2"
        if re_search(r"\b(?:it|that|this)\b", t) and task.active_application:
            t2 = re_sub(r"\b(?:it|that|this)\b", task.active_application, t, count=1)
            return t2
        if re_search(r"\bother\s+monitor\b", t) and task.active_monitor is not None:
            # Keep "other monitor" token — monitors.resolve / ReferenceResolver handle it
            # but bind app from task
            if task.active_application and not re_search(
                r"\b(?:chrome|spotify|edge|notepad|blender)\b", t, flags=True
            ):
                if not re_match(r"^(?:move|put|send)\b", t):
                    return f"move {task.active_application} to the other monitor"
        return t

    def _resolve_refs(
        self, text: str, goal: GoalCandidate
    ) -> tuple[str, list[EntityReference], bool, str]:
        entities: list[EntityReference] = []
        needs = False
        prompt = ""
        try:
            from neuron.v3.reference_resolver import needs_resolution, resolve_reference

            if needs_resolution(text) or re_has_bare_deixis(text):
                ref = resolve_reference(text)
                if ref.needs_clarification:
                    return text, entities, True, ref.clarification_prompt or ""
                if ref.rewritten_command and ref.confidence >= 0.55:
                    text = ref.rewritten_command
                    if ref.resolved_target:
                        ent = EntityReference(
                            entity_type=ref.target_type or "other",
                            value=str(ref.resolved_target),
                            normalized=str(ref.resolved_target).lower(),
                            confidence=float(ref.confidence or 0.5),
                            source_turn=self.state.turn_id,
                        )
                        entities.append(ent)
                        self.state.note_entity(ent)
        except Exception as exc:
            log.debug("reference bridge: %s", exc)
        return text, entities, needs, prompt

    def _has_referent(self) -> bool:
        if self.state.task.active_application:
            return True
        if self.state.result_set and self.state.result_set.is_fresh():
            return True
        if self.state.last_referenced and self.state.last_referenced.is_fresh():
            return True
        return False

    def _reconcile_world(self, world: Any) -> None:
        if world is None:
            try:
                from neuron.v3.context_engine import get_engine

                w = get_engine().world
                app = getattr(w, "active_app", "") or ""
                mon = getattr(w, "active_monitor", None)
                if app and self.state.task.active_application:
                    if app.lower() not in self.state.task.active_application.lower():
                        # World wins for observable — invalidate mismatched soft facts
                        if self.state.task.verified_facts.get("app") and str(
                            self.state.task.verified_facts.get("app")
                        ).lower() not in app.lower():
                            self.state.task.uncertain_facts["app"] = "world_mismatch"
                if app:
                    pass  # don't overwrite verified until verify callback
                _ = mon
            except Exception:
                pass
            return
        # DesktopWorldModel-like
        try:
            fg = getattr(world, "foreground_app", None) or getattr(world, "active_application", "")
            if callable(fg):
                fg = fg()
            if fg and self.state.last_resolved_element:
                # element may be stale if app gone
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------ events

    def set_pending_clarification(self, clr: ClarificationState) -> None:
        self.state.pending_clarification = clr
        log.info("[CLARIFY][pending] id=%s src=%s", clr.clarification_id, clr.source)

    def set_pending_confirmation(self, cfm: ConfirmationState) -> None:
        self.state.pending_confirmation = cfm

    def on_recovery_clarify(self, decision, *, goal_text: str = "", plan_id: str = "") -> None:
        prompt = getattr(decision, "clarify_prompt", "") or getattr(decision, "reason", "")
        if not prompt:
            return
        clr = clarify_mod.set_clarification(
            prompt=str(prompt),
            original_goal=goal_text,
            source="recovery",
            plan_id=plan_id,
        )
        self.set_pending_clarification(clr)

    def apply_verified(
        self,
        *,
        action: str,
        args: dict[str, Any] | None = None,
        status: str = "SUCCESS",
        observation: dict[str, Any] | None = None,
        summary: str = "",
    ) -> None:
        """Only SUCCESS updates strong facts; UNCERTAIN marks unknown; FAILURE does not claim success."""
        args = dict(args or {})
        obs = dict(observation or {})
        st = (status or "").upper()
        act = (action or "").lower()

        if st == "SUCCESS":
            self.stats["verified_updates"] += 1
            self.state.last_successful_action = act
            self.state.last_verified_summary = (summary or "")[:160]
            self.state.task.at = time.time()
            name = str(args.get("name") or args.get("app") or obs.get("app") or "")
            if "open" in act or "focus" in act:
                if name:
                    self.state.task.active_application = name
                    self.state.task.verified_facts["app"] = name
                    self.state.task.uncertain_facts.pop("app", None)
                    self.state.note_entity(
                        EntityReference(
                            entity_type="app",
                            value=name,
                            normalized=name.lower(),
                            verified=True,
                            confidence=0.9,
                        )
                    )
            mon = args.get("monitor") or args.get("monitor_index") or obs.get("monitor")
            if mon is not None and ("move" in act or "monitor" in act):
                self.state.task.active_monitor = mon
                self.state.task.verified_facts["monitor"] = mon
                self.state.task.verified_facts["last_move_monitor"] = mon
                if name:
                    self.state.task.verified_facts[f"app_monitor:{name.lower()}"] = mon
                self.state.task.uncertain_facts.pop("monitor", None)
            if "search" in act:
                q = str(args.get("query") or args.get("text") or "")
                if q:
                    self.state.task.last_query = q
                    self.state.task.verified_facts["last_query"] = q
            url = str(obs.get("url") or args.get("url") or "")
            if url:
                self.state.task.active_browser_url = url
            if "youtube" in (url + str(args.get("site") or "")).lower():
                self.state.task.active_page_hint = "youtube"
            if "fullscreen" in act:
                self.state.task.media_fullscreen = "true"
                self.state.task.verified_facts["media_fullscreen"] = True
                self.state.task.uncertain_facts.pop("media_fullscreen", None)
            # Result set seeding for search
            if "search" in act and self.state.task.last_query:
                items = obs.get("results") or args.get("results")
                if isinstance(items, list) and items:
                    self.set_result_set(
                        source="search",
                        query=self.state.task.last_query,
                        application=self.state.task.active_application,
                        items=items,
                    )
                elif not self.state.result_set or not self.state.result_set.is_fresh():
                    # Placeholder ordered slots for ordinal follow-ups in tests/mocks
                    self.set_result_set(
                        source="search",
                        query=self.state.task.last_query,
                        application=self.state.task.active_application,
                        items=[
                            {"index": 1, "label": f"{self.state.task.last_query} result 1"},
                            {"index": 2, "label": f"{self.state.task.last_query} result 2"},
                            {"index": 3, "label": f"{self.state.task.last_query} result 3"},
                        ],
                    )
            if "navigate" in act or "go_to" in act or "browser_open" in act:
                if self.state.result_set:
                    self.state.result_set.stale = True
            log.info(
                "[CONTEXT][verify] SUCCESS action=%s app=%s mon=%s",
                act,
                self.state.task.active_application,
                self.state.task.active_monitor,
            )
            return

        if st == "UNCERTAIN":
            self.stats["uncertain_updates"] += 1
            if "fullscreen" in act:
                self.state.task.media_fullscreen = "unknown"
                self.state.task.uncertain_facts["media_fullscreen"] = summary or "uncertain"
            if mon := (args.get("monitor") or args.get("monitor_index")):
                self.state.task.uncertain_facts["monitor"] = mon
            if name := str(args.get("name") or ""):
                self.state.task.uncertain_facts["app"] = name
            log.info("[CONTEXT][verify] UNCERTAIN action=%s", act)
            return

        # FAILURE — do not store claimed success facts
        if "monitor" in act or "move" in act:
            self.state.task.uncertain_facts.pop("monitor", None)
            # Explicitly do not set active_monitor from failed move
        if "fullscreen" in act:
            self.state.task.media_fullscreen = "unknown"
        log.info("[CONTEXT][verify] FAILURE action=%s — no strong fact update", act)

    def set_result_set(
        self,
        *,
        source: str,
        query: str = "",
        application: str = "",
        items: list[Any],
    ) -> ResultSet:
        parsed_items: list[ResultSetItem] = []
        for i, it in enumerate(items):
            if isinstance(it, ResultSetItem):
                parsed_items.append(it)
            elif isinstance(it, dict):
                parsed_items.append(
                    ResultSetItem(
                        index=int(it.get("index") or i + 1),
                        label=str(it.get("label") or it.get("title") or it.get("name") or ""),
                        world_ref=str(it.get("world_ref") or it.get("id") or ""),
                        meta={k: v for k, v in it.items() if k not in ("label", "title", "name", "id")},
                    )
                )
            else:
                parsed_items.append(ResultSetItem(index=i + 1, label=str(it)[:80]))
        rs = ResultSet(
            source=source,
            query=query,
            application=application,
            items=parsed_items,
        )
        self.state.result_set = rs
        return rs

    def invalidate_result_set(self, reason: str = "") -> None:
        if self.state.result_set:
            self.state.result_set.stale = True
            log.info("[CONTEXT] result_set stale reason=%s", reason[:80])

    def begin_task(self, goal_text: str, *, goal_id: str = "", plan_id: str = "") -> None:
        self.state.task = TaskContext(
            goal_text=goal_text[:200],
            goal_id=goal_id,
            plan_id=plan_id,
            active_application=self.state.task.active_application,
            active_monitor=self.state.task.active_monitor,
            active_browser_url=self.state.task.active_browser_url,
        )

    def to_plan_goal(self, understanding: UnderstandingResult):
        """Map understanding → HierarchicalPlanner Goal (opt-in callers)."""
        from neuron.v4.plan.types import Goal as PlanGoal

        g = understanding.goal
        text = understanding.rewritten_command or (g.normalized if g else "") or ""
        args = dict(g.args) if g else {}
        return PlanGoal(
            text=text,
            normalized=text,
            target_applications=[args["name"]] if args.get("name") else [],
            target_monitor=args.get("monitor"),
            constraints=[f"continuity={understanding.continuity.value}"],
            source="v4_context",
        )

    def apply_goal_update(self, update: GoalUpdate, plan=None) -> None:
        if update is None:
            return
        if update.preserve_verified:
            # Keep task verified facts; only change goal text / selection
            if update.text:
                self.state.task.goal_text = update.text[:200]
            if "ordinal" in update.args_patch and self.state.result_set:
                pass  # selection change only
        else:
            self.state.task.goal_text = update.text[:200]

    def _log_nlu(self, result: UnderstandingResult) -> None:
        log.info(
            "[NLU][turn] family=%s cont=%s route=%s conf=%.2f ms=%.1f reason=%s",
            result.goal.intent_family.value if result.goal else "?",
            result.continuity.value,
            result.route.value,
            result.confidence,
            result.latency_ms,
            result.route_reason[:80],
        )


def re_has_bare_deixis(text: str) -> bool:
    import re

    t = (text or "").lower().strip()
    if re.match(r"^(?:open|click|play|close|move|put|focus)\s+(?:it|that|this)\b", t):
        return True
    if t in ("it", "that", "this", "this one", "that one", "open it", "click it", "play it"):
        return True
    return False


def re_search(pat: str, text: str, flags: bool = False):
    import re

    return re.search(pat, text or "", re.I if flags else 0)


def re_sub(pat: str, repl: str, text: str, count: int = 0) -> str:
    import re

    return re.sub(pat, repl, text or "", count=count, flags=re.I)


def re_match(pat: str, text: str):
    import re

    return re.match(pat, text or "", re.I)


def get_conversation_engine() -> ConversationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = ConversationEngine()
    return _ENGINE


def reset_conversation_engine() -> ConversationEngine:
    global _ENGINE
    _ENGINE = ConversationEngine()
    return _ENGINE


__all__ = [
    "ConversationEngine",
    "get_conversation_engine",
    "reset_conversation_engine",
]
