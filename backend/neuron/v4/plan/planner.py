"""V4.4 HierarchicalPlanner — rolling, grounded, tool-aware planning.

Does NOT execute desktop actions. Produces PlanningDecision / GroundedAction
for AgentLoop + ToolRegistry + safety.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.plan import satisfy, templates, tools as plan_tools
from neuron.v4.plan.types import (
    ActionIntent,
    DecisionKind,
    Goal,
    GroundedAction,
    PlanStatus,
    PlanningDecision,
    StepStatus,
    Subgoal,
    TaskPlan,
)
from neuron.v4.plan.validate import (
    MAX_REVISIONS,
    validate_llm_plan_dict,
    validate_plan,
)

log = logging.getLogger("neuron.v4.plan")

_MIN_RESOLVE_CONFIDENCE = 0.45


class HierarchicalPlanner:
    """Goal → TaskPlan; plan_next(world) → PlanningDecision (rolling)."""

    def __init__(self, *, allow_llm: bool = False, tool_registry=None):
        self.allow_llm = allow_llm
        self._tool_registry = tool_registry
        self.active_plan: TaskPlan | None = None
        self._pending_confirm: GroundedAction | None = None
        self.last_decision: PlanningDecision | None = None
        self.stats: dict[str, float] = {
            "plan_create_ms": 0.0,
            "plan_next_ms": 0.0,
            "ground_ms": 0.0,
            "llm_ms": 0.0,
        }

    # ------------------------------------------------------------------ create

    def create_plan(
        self,
        text: str,
        *,
        normalized: str = "",
        context: Any = None,
        goal: Goal | None = None,
        world=None,
        allow_llm: bool | None = None,
    ) -> TaskPlan:
        t0 = time.perf_counter()
        raw = (normalized or text or "").strip()
        g = goal or Goal(text=text or raw, normalized=raw)
        if not g.text:
            g.text = raw
        if not g.normalized:
            g.normalized = raw

        # ContextEngine follow-ups (best-effort)
        raw = self._apply_context(raw, context)

        # V4.9 — learned COMPOSITE procedure (opt-in registry; never bypasses validate)
        plan = self._try_learned_procedure(raw, g, context=context)
        if plan is None:
            plan = (
                templates.try_youtube_workflow(raw, g)
                or templates.try_multi_open(raw, g)
                or templates.try_multi_app_as_plan(raw, g)
                or templates.try_simple_template(raw, g)
                or templates.try_click_resolve_template(raw, g)
            )

        use_llm = self.allow_llm if allow_llm is None else allow_llm
        if plan is None and use_llm:
            plan = self._llm_decompose(raw, g, world=world, context=context)

        if plan is None:
            # Soft fallback: single observe/clarify subgoal — never invent tools
            plan = TaskPlan(
                goal=g,
                source="fallback",
                status=PlanStatus.BLOCKED,
                subgoals=[
                    Subgoal(
                        description="Need clarification or capability match",
                        intent="clarify",
                        preferred_tools=["clarify"],
                        completion_criteria=["user clarified"],
                        status=StepStatus.BLOCKED,
                        subgoal_id="sg_clarify",
                        target_hints={"prompt": f"I am not sure how to plan: {g.text[:120]}"},
                    )
                ],
            )

        v = validate_plan(plan)
        if not v.ok:
            plan.status = PlanStatus.FAILED
            plan.meta["validation_errors"] = list(v.errors)
        else:
            plan.status = PlanStatus.ACTIVE
            if plan.subgoals:
                plan.current_subgoal_id = plan.subgoals[0].subgoal_id
                plan.subgoals[0].status = StepStatus.READY

        plan.touch()
        self.active_plan = plan
        self._pending_confirm = None
        self.stats["plan_create_ms"] = (time.perf_counter() - t0) * 1000
        self._log_decision(
            PlanningDecision(
                kind=DecisionKind.WAIT,
                plan_id=plan.plan_id,
                goal_id=plan.goal.goal_id,
                reason=f"created plan source={plan.source} subgoals={len(plan.subgoals)}",
                revision=plan.revision,
                latency_ms=self.stats["plan_create_ms"],
            )
        )
        return plan

    def load_plan(self, plan: TaskPlan) -> TaskPlan:
        self.active_plan = plan
        return plan

    def cancel(self, plan: TaskPlan | None = None) -> TaskPlan | None:
        p = plan or self.active_plan
        if p is None:
            return None
        p.status = PlanStatus.CANCELLED
        p.touch()
        for sg in p.subgoals:
            if sg.status in (StepStatus.PENDING, StepStatus.READY, StepStatus.RUNNING, StepStatus.UNCERTAIN):
                sg.status = StepStatus.BLOCKED
        self._pending_confirm = None
        if self.active_plan and self.active_plan.plan_id == p.plan_id:
            self.active_plan = p
        return p

    def _try_learned_procedure(self, raw: str, g: Goal, *, context: Any = None) -> TaskPlan | None:
        """Expand a matched learned procedure into TaskPlan subgoals (AgentLoop path)."""
        try:
            from neuron.v4.learn.execute import (
                match_procedure_for_goal,
                extract_procedure_params,
            )
            proc = match_procedure_for_goal(raw)
            if not proc or not proc.enabled:
                return None
            # Prefer built-in youtube templates for simple search unless alias/confidence strong
            low = (raw or "").lower()
            strong = (
                any(a.lower() in low for a in proc.aliases)
                or "my youtube" in low
                or "workflow" in low
                or "do that again" in low
                or proc.confidence >= 0.7
            )
            if not strong and proc.intent_family.startswith("youtube"):
                return None
            ctx_params = {}
            if isinstance(context, dict):
                ctx_params = dict(context.get("procedure_params") or {})
            params = extract_procedure_params(raw, proc, context_params=ctx_params)
            subgoals: list[Subgoal] = []
            for i, step in enumerate(proc.steps):
                legacy = step.to_legacy_step(params)
                tool = str(legacy.get("action") or "")
                args = dict(legacy.get("args") or {})
                subgoals.append(
                    Subgoal(
                        description=legacy.get("expected_result") or tool,
                        intent=tool.split(".")[0] if "." in tool else tool,
                        preferred_tools=[tool] if tool else [],
                        completion_criteria=[
                            str(legacy.get("expected_result") or f"{tool} verified")
                        ],
                        status=StepStatus.PENDING,
                        subgoal_id=f"sg_proc_{i}",
                        target_hints=args,
                    )
                )
            if len(subgoals) < 2:
                return None
            return TaskPlan(
                goal=g,
                source="learned_procedure",
                status=PlanStatus.ACTIVE,
                subgoals=subgoals,
                meta={
                    "procedure_id": proc.procedure_id,
                    "procedure_version": proc.version,
                    "params": params,
                },
            )
        except Exception:
            return None

    # ------------------------------------------------------------------ rolling

    def plan_next(
        self,
        plan: TaskPlan | None = None,
        *,
        world=None,
        context: Any = None,
        resolution=None,
        confirmed: bool = False,
        last_result: dict[str, Any] | None = None,
    ) -> PlanningDecision:
        t0 = time.perf_counter()
        p = plan or self.active_plan
        if p is None:
            d = PlanningDecision(kind=DecisionKind.FAIL, reason="no active plan")
            self.last_decision = d
            return d

        if p.status == PlanStatus.CANCELLED:
            d = self._dec(p, DecisionKind.CANCELLED, reason="plan cancelled")
            self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
            d.latency_ms = self.stats["plan_next_ms"]
            self._log_decision(d)
            return d

        if p.status == PlanStatus.COMPLETED:
            d = self._dec(p, DecisionKind.COMPLETE, reason="plan already completed")
            self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
            d.latency_ms = self.stats["plan_next_ms"]
            self._log_decision(d)
            return d

        if p.status == PlanStatus.FAILED:
            d = self._dec(p, DecisionKind.FAIL, reason=str(p.meta.get("validation_errors") or "plan failed"))
            self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
            d.latency_ms = self.stats["plan_next_ms"]
            self._log_decision(d)
            return d

        # Confirmation gate
        if p.status == PlanStatus.WAITING_FOR_CONFIRMATION:
            if not confirmed:
                d = self._dec(
                    p,
                    DecisionKind.CONFIRM,
                    reason="waiting for user confirmation",
                    needs_confirmation=True,
                    grounded=self._pending_confirm,
                )
                self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
                d.latency_ms = self.stats["plan_next_ms"]
                self._log_decision(d)
                return d
            # Confirmed — release pending action
            if self._pending_confirm:
                ga = self._pending_confirm
                self._pending_confirm = None
                p.status = PlanStatus.ACTIVE
                p.touch()
                d = self._dec(
                    p,
                    DecisionKind.ACT,
                    reason="confirmation granted",
                    grounded=ga,
                    subgoal_id=ga.subgoal_id,
                )
                self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
                d.latency_ms = self.stats["plan_next_ms"]
                self._log_decision(d)
                return d

        if p.status == PlanStatus.WAITING_FOR_OBSERVATION:
            p.status = PlanStatus.ACTIVE
            p.touch()

        # Apply last_result bookkeeping
        if last_result:
            self._note_result(p, last_result)

        # Skip / advance satisfied subgoals
        while True:
            sg = self._select_subgoal(p)
            if sg is None:
                p.status = PlanStatus.COMPLETED
                p.current_subgoal_id = ""
                p.touch()
                d = self._dec(p, DecisionKind.COMPLETE, reason="all subgoals done")
                break

            p.current_subgoal_id = sg.subgoal_id
            if not satisfy.dependencies_met(sg, p.subgoals):
                sg.status = StepStatus.BLOCKED
                d = self._dec(
                    p,
                    DecisionKind.WAIT,
                    reason="dependency unmet",
                    subgoal=sg,
                )
                break

            sat = satisfy.subgoal_satisfied(sg, world)
            if sat is True:
                sg.status = StepStatus.SKIPPED
                p.touch()
                continue  # rolling — pick next
            if sat is None and sg.intent in ("open_app", "focus_app", "move_monitor", "ensure_youtube"):
                # Need observation before claiming skip or act
                p.status = PlanStatus.WAITING_FOR_OBSERVATION
                d = self._dec(
                    p,
                    DecisionKind.OBSERVE,
                    reason="world knowledge UNKNOWN for precondition",
                    subgoal=sg,
                    needs_observation=True,
                )
                break

            # Clarify intent
            if sg.intent == "clarify" or "clarify" in sg.preferred_tools:
                p.status = PlanStatus.BLOCKED
                prompt = str((sg.target_hints or {}).get("prompt") or sg.description)
                d = self._dec(
                    p,
                    DecisionKind.CLARIFY,
                    reason="clarification required",
                    subgoal=sg,
                    clarify_prompt=prompt,
                )
                break

            # Observe-only subgoal
            if sg.intent == "observe" or sg.preferred_tools == ["observe"]:
                d = self._dec(
                    p,
                    DecisionKind.OBSERVE,
                    reason="completion observe",
                    subgoal=sg,
                    needs_observation=True,
                )
                # Mark succeed after observe request — caller should call mark after observe
                break

            # Semantic resolve for click/reference
            ref = str((sg.target_hints or {}).get("reference") or "")
            if ref and (
                sg.intent == "click"
                or "resolve" in sg.preferred_tools
                or resolution is not None
            ):
                d = self._ground_via_resolve(p, sg, world, context, resolution, ref)
                break

            # Normal tool grounding
            d = self._ground_tool_action(p, sg)
            break

        self.stats["plan_next_ms"] = (time.perf_counter() - t0) * 1000
        d.latency_ms = self.stats["plan_next_ms"]
        self.last_decision = d
        self._log_decision(d)
        return d

    def mark_subgoal(
        self,
        plan: TaskPlan,
        subgoal_id: str,
        status: StepStatus,
        *,
        error: str = "",
    ) -> None:
        for sg in plan.subgoals:
            if sg.subgoal_id == subgoal_id:
                sg.status = status
                if error:
                    sg.last_error = error
                if status == StepStatus.FAILED:
                    sg.attempt_count += 1
                plan.touch()
                return

    def apply_action_outcome(
        self,
        plan: TaskPlan,
        decision: PlanningDecision,
        *,
        ok: bool | None = None,
        detail: str = "",
        world=None,
        verification=None,
    ) -> None:
        """
        Record outcome. Prefer VerificationReport/VerificationOutcome when provided.

        ActionResult ok alone must not mark SUCCESS — pass verification=.
        ok=True without verification → treated as UNCERTAIN (V4.5).
        ok=None → UNCERTAIN.
        ok=False → FAILURE path.
        """
        from neuron.v4.types import VerificationOutcome
        from neuron.v4.verify.types import VerificationReport

        sg = None
        if decision.subgoal_id:
            for s in plan.subgoals:
                if s.subgoal_id == decision.subgoal_id:
                    sg = s
                    break
        if sg is None:
            return

        status = None
        if verification is not None:
            if isinstance(verification, VerificationReport):
                status = verification.status
                detail = detail or verification.reason
                plan.meta["last_verification"] = verification.to_dict()
            elif isinstance(verification, VerificationOutcome):
                status = verification
            elif hasattr(verification, "outcome"):
                status = verification.outcome
                detail = detail or getattr(verification, "detail", "") or ""

        if status is VerificationOutcome.SUCCESS:
            sg.status = StepStatus.SUCCEEDED
        elif status is VerificationOutcome.FAILURE or ok is False:
            sg.attempt_count += 1
            sg.last_error = detail or "verification failed"
            if sg.attempt_count >= sg.max_attempts:
                sg.status = StepStatus.FAILED
                plan.status = PlanStatus.FAILED
                plan.meta["fail_reason"] = f"max attempts on {sg.subgoal_id}"
            else:
                sg.status = StepStatus.READY
                if plan.revision < MAX_REVISIONS:
                    plan.revision += 1
                    plan.meta["last_replan"] = detail or "retry"
        else:
            # UNCERTAIN or ok=True without verification — never SUCCEEDED
            sg.status = StepStatus.UNCERTAIN
            sg.last_error = detail or "uncertain verification"
            if ok is True and verification is None:
                plan.meta["caller_ok_without_verify"] = True
        plan.touch()

        if (status is VerificationOutcome.FAILURE or ok is False) and world is not None:
            if "disappear" in (detail or "").lower():
                self._replan_ensure_app(plan, world)

    def apply_verification(
        self,
        plan: TaskPlan,
        decision: PlanningDecision,
        verification,
        *,
        world=None,
    ) -> None:
        """Authoritative path: apply VerificationReport / VerificationOutcome."""
        self.apply_action_outcome(
            plan, decision, verification=verification, world=world
        )

    def apply_recovery(self, plan: TaskPlan, decision, *, world=None) -> None:
        """V4.6: apply RecoveryDecision to TaskPlan (no direct execution)."""
        try:
            from neuron.v4.recover import get_recovery_engine
            get_recovery_engine().apply_to_plan(plan, decision, planner=self)
        except Exception:
            pass

    def plan_is_complete(self, plan: TaskPlan) -> bool:
        """TaskPlan completes only when remaining subgoals are SUCCEEDED or SKIPPED."""
        if plan.status == PlanStatus.CANCELLED:
            return False
        for sg in plan.subgoals:
            if sg.status in (
                StepStatus.PENDING,
                StepStatus.READY,
                StepStatus.RUNNING,
                StepStatus.UNCERTAIN,
                StepStatus.BLOCKED,
            ):
                return False
            if sg.status is StepStatus.FAILED:
                return False
        return all(
            sg.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for sg in plan.subgoals
        )

    def replan_bounded(self, plan: TaskPlan, *, reason: str = "") -> TaskPlan:
        if plan.revision >= MAX_REVISIONS:
            plan.status = PlanStatus.FAILED
            plan.meta["fail_reason"] = "max revisions"
            return plan
        plan.revision += 1
        plan.meta["replan_reason"] = reason
        plan.status = PlanStatus.ACTIVE
        # Reset BLOCKED/FAILED ready-to-retry open_app style subgoals
        for sg in plan.subgoals:
            if sg.status == StepStatus.FAILED and sg.attempt_count < sg.max_attempts:
                sg.status = StepStatus.READY
        plan.touch()
        return plan

    # ------------------------------------------------------------------ internals

    def _apply_context(self, text: str, context: Any) -> str:
        if context is None:
            return text
        # string context
        if isinstance(context, str) and context.strip():
            # Follow-up fragments often omit app — leave as-is; ContextEngine rewrite may be passed as text
            return text
        # object with rewrite / active_task
        for attr in ("rewritten", "resolved_text", "text"):
            val = getattr(context, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return text

    def _llm_decompose(self, text: str, goal: Goal, *, world=None, context=None) -> TaskPlan | None:
        t0 = time.perf_counter()
        try:
            from neuron.v3.grounded_planner import grounded_plan, validate_or_reject
            world_state = ""
            if world is not None:
                try:
                    snap = world.snapshot()
                    world_state = str(getattr(snap, "to_observe_dict", lambda: {})())
                except Exception:
                    world_state = ""
            raw = grounded_plan(
                text,
                context=str(context or ""),
                world_state=world_state[:2000],
                normalized=goal.normalized,
            )
            if not raw:
                return None
            validation = validate_or_reject(raw)
            if not getattr(validation, "ok", False):
                return None
            ok, err, steps = validate_llm_plan_dict(raw if isinstance(raw, dict) else {})
            if not ok:
                log.info("llm plan rejected: %s", err)
                return None
            plan = templates.legacy_steps_to_plan(steps, goal, source="llm")
            self.stats["llm_ms"] = (time.perf_counter() - t0) * 1000
            return plan
        except Exception as exc:
            log.debug("llm decompose failed: %s", exc)
            self.stats["llm_ms"] = (time.perf_counter() - t0) * 1000
            return None

    def _select_subgoal(self, plan: TaskPlan) -> Subgoal | None:
        for sg in plan.subgoals:
            if sg.status in (
                StepStatus.PENDING,
                StepStatus.READY,
                StepStatus.RUNNING,
                StepStatus.UNCERTAIN,
                StepStatus.BLOCKED,
            ):
                # Skip permanently blocked clarify without tools
                if sg.status == StepStatus.BLOCKED and sg.intent == "clarify":
                    return sg
                if sg.status == StepStatus.BLOCKED and not satisfy.dependencies_met(sg, plan.subgoals):
                    continue
                if sg.status == StepStatus.BLOCKED:
                    # dependency now met?
                    if satisfy.dependencies_met(sg, plan.subgoals):
                        sg.status = StepStatus.READY
                        return sg
                    continue
                return sg
        return None

    def _ground_tool_action(self, plan: TaskPlan, sg: Subgoal) -> PlanningDecision:
        t0 = time.perf_counter()
        tool = plan_tools.pick_tool(sg.intent, preferred=sg.preferred_tools)
        if not tool:
            # Prefer resolve path if reference present
            if (sg.target_hints or {}).get("reference"):
                return self._dec(
                    plan,
                    DecisionKind.RESOLVE,
                    reason="no tool; need semantic resolve",
                    subgoal=sg,
                    intent=ActionIntent(
                        kind="resolve",
                        reference=str(sg.target_hints.get("reference")),
                        subgoal_id=sg.subgoal_id,
                    ),
                )
            return self._dec(
                plan,
                DecisionKind.FAIL,
                reason=f"no registered tool for intent={sg.intent}",
                subgoal=sg,
            )

        args = dict(sg.target_hints or {})
        args.pop("reference", None)
        args.pop("_satisfied", None)
        # Normalize mute/volume args toward registry schema
        if tool == "volume":
            if "action" not in args and "mute" in args:
                args = {"action": "mute" if args.get("mute") else "unmute"}
            elif "action" not in args and args.get("direction"):
                args = {"action": str(args.get("direction"))}
        ok, err, coerced = plan_tools.validate_tool_call(tool, args)
        if not ok:
            return self._dec(
                plan,
                DecisionKind.FAIL,
                reason=f"invalid tool args: {err}",
                subgoal=sg,
            )

        risk = plan_tools.tool_risk(tool)
        ga = GroundedAction(
            tool=tool,
            arguments=coerced,
            target=sg.description,
            expected_result=(sg.completion_criteria[0] if sg.completion_criteria else ""),
            risk=risk,
            subgoal_id=sg.subgoal_id,
            reason=f"intent={sg.intent}",
            from_intent=ActionIntent(
                kind=tool,
                args=coerced,
                target=sg.description,
                subgoal_id=sg.subgoal_id,
                reason=sg.intent,
            ),
        )
        self.stats["ground_ms"] = (time.perf_counter() - t0) * 1000

        # Safety gate
        try:
            from neuron.safety.levels import BLOCKED, CONFIRM, HIGH, SAFE
            from neuron.safety.policy import classify
            c = classify(tool, coerced)
            tier = c.tier
        except Exception:
            tier = risk
            BLOCKED, CONFIRM, HIGH, SAFE = "blocked", "confirm", "high", "safe"

        if tier == BLOCKED:
            plan.status = PlanStatus.BLOCKED
            return self._dec(
                plan,
                DecisionKind.FAIL,
                reason=f"blocked by safety: {tool}",
                subgoal=sg,
                grounded=ga,
            )
        if tier in (CONFIRM, HIGH):
            plan.status = PlanStatus.WAITING_FOR_CONFIRMATION
            self._pending_confirm = ga
            return self._dec(
                plan,
                DecisionKind.CONFIRM,
                reason=f"safety tier={tier}",
                subgoal=sg,
                grounded=ga,
                needs_confirmation=True,
            )

        sg.status = StepStatus.RUNNING
        return self._dec(
            plan,
            DecisionKind.ACT,
            reason=f"tool={tool} tier={tier}",
            subgoal=sg,
            grounded=ga,
            confidence=1.0,
        )

    def _ground_via_resolve(
        self,
        plan: TaskPlan,
        sg: Subgoal,
        world,
        context,
        resolution,
        ref: str,
    ) -> PlanningDecision:
        from neuron.v4.resolve import ResolutionStatus

        res = resolution
        if res is None:
            try:
                from neuron.v4.resolve import context_from_engine, get_semantic_resolver
                ctx = context
                if ctx is None and world is not None:
                    ctx = context_from_engine(world=world)
                res = get_semantic_resolver().resolve(ref, world=world, context=ctx)
            except Exception as exc:
                return self._dec(
                    plan,
                    DecisionKind.OBSERVE,
                    reason=f"resolve error: {exc}",
                    subgoal=sg,
                    needs_observation=True,
                )

        status = getattr(res, "status", None)
        if status == ResolutionStatus.STALE_WORLD:
            plan.status = PlanStatus.WAITING_FOR_OBSERVATION
            return self._dec(
                plan,
                DecisionKind.OBSERVE,
                reason="STALE_WORLD",
                subgoal=sg,
                needs_observation=True,
            )
        if status == ResolutionStatus.INSUFFICIENT_CONTEXT:
            return self._dec(
                plan,
                DecisionKind.CLARIFY,
                reason="INSUFFICIENT_CONTEXT",
                subgoal=sg,
                clarify_prompt=f"Which element did you mean by '{ref}'?",
            )
        if status == ResolutionStatus.AMBIGUOUS:
            return self._dec(
                plan,
                DecisionKind.CLARIFY,
                reason="AMBIGUOUS — will not guess",
                subgoal=sg,
                clarify_prompt=f"Multiple matches for '{ref}'. Which one?",
            )
        if status == ResolutionStatus.NOT_FOUND:
            plan.status = PlanStatus.WAITING_FOR_OBSERVATION
            return self._dec(
                plan,
                DecisionKind.OBSERVE,
                reason="NOT_FOUND — re-observe or alternate",
                subgoal=sg,
                needs_observation=True,
            )
        if status != ResolutionStatus.RESOLVED:
            return self._dec(plan, DecisionKind.FAIL, reason=f"resolve status={status}", subgoal=sg)

        resolved = res.resolved
        conf = float(getattr(resolved, "confidence", 0.0) or getattr(res, "confidence", 0.0) or 0.0)
        if conf < _MIN_RESOLVE_CONFIDENCE:
            return self._dec(
                plan,
                DecisionKind.CLARIFY,
                reason=f"low confidence {conf:.2f}",
                subgoal=sg,
                clarify_prompt=f"Low confidence for '{ref}'. Confirm target?",
                confidence=conf,
            )

        element_id = getattr(resolved, "element_id", "") or ""
        tool = plan_tools.pick_tool("click", preferred=[t for t in sg.preferred_tools if t != "resolve"])
        if not tool:
            tool = "click"
        args = {"element_id": element_id}
        ok, err, coerced = plan_tools.validate_tool_call(tool, args)
        if not ok:
            # Fallback: pass element_id anyway for uia paths that accept loose args
            coerced = args
        ga = GroundedAction(
            tool=tool,
            arguments=coerced,
            target=ref,
            element_id=element_id,
            confidence=conf,
            risk=plan_tools.tool_risk(tool),
            subgoal_id=sg.subgoal_id,
            reason="semantic resolve",
            from_intent=ActionIntent(kind="click", reference=ref, subgoal_id=sg.subgoal_id),
        )
        # Safety
        try:
            from neuron.safety.levels import BLOCKED, CONFIRM, HIGH
            from neuron.safety.policy import classify
            tier = classify(tool, coerced).tier
        except Exception:
            tier = ga.risk
            BLOCKED, CONFIRM, HIGH = "blocked", "confirm", "high"
        if tier == BLOCKED:
            plan.status = PlanStatus.BLOCKED
            return self._dec(plan, DecisionKind.FAIL, reason="blocked", subgoal=sg, grounded=ga)
        if tier in (CONFIRM, HIGH):
            plan.status = PlanStatus.WAITING_FOR_CONFIRMATION
            self._pending_confirm = ga
            return self._dec(
                plan,
                DecisionKind.CONFIRM,
                reason=f"safety={tier}",
                subgoal=sg,
                grounded=ga,
                needs_confirmation=True,
                confidence=conf,
            )
        sg.status = StepStatus.RUNNING
        return self._dec(
            plan,
            DecisionKind.ACT,
            reason=f"resolved {element_id}",
            subgoal=sg,
            grounded=ga,
            confidence=conf,
        )

    def _note_result(self, plan: TaskPlan, last_result: dict[str, Any]) -> None:
        sid = str(last_result.get("subgoal_id") or "")
        if not sid:
            return
        ok = last_result.get("ok")
        detail = str(last_result.get("detail") or "")
        # Map to mark
        if ok is True:
            self.mark_subgoal(plan, sid, StepStatus.SUCCEEDED)
        elif ok is False:
            self.mark_subgoal(plan, sid, StepStatus.FAILED, error=detail)
        else:
            self.mark_subgoal(plan, sid, StepStatus.UNCERTAIN, error=detail)

    def _replan_ensure_app(self, plan: TaskPlan, world) -> None:
        for sg in plan.subgoals:
            if sg.intent == "open_app" and sg.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED):
                app = str((sg.target_hints or {}).get("name") or "")
                if app and satisfy.app_open_known(world, app) is False:
                    sg.status = StepStatus.READY
                    sg.attempt_count = min(sg.attempt_count, sg.max_attempts - 1)
                    plan.revision += 1
                    plan.meta["replan_reason"] = f"re-ensure {app}"
                    plan.status = PlanStatus.ACTIVE

    def _dec(
        self,
        plan: TaskPlan,
        kind: DecisionKind,
        *,
        reason: str = "",
        subgoal: Subgoal | None = None,
        subgoal_id: str = "",
        grounded: GroundedAction | None = None,
        intent: ActionIntent | None = None,
        clarify_prompt: str = "",
        needs_observation: bool = False,
        needs_confirmation: bool = False,
        confidence: float = 0.0,
    ) -> PlanningDecision:
        sg = subgoal
        return PlanningDecision(
            kind=kind,
            plan_id=plan.plan_id,
            goal_id=plan.goal.goal_id,
            subgoal_id=(sg.subgoal_id if sg else subgoal_id),
            subgoal_description=(sg.description if sg else ""),
            intent=intent or (grounded.from_intent if grounded else None),
            grounded=grounded,
            clarify_prompt=clarify_prompt,
            reason=reason,
            confidence=confidence,
            needs_observation=needs_observation,
            needs_confirmation=needs_confirmation,
            revision=plan.revision,
        )

    def _log_decision(self, d: PlanningDecision) -> None:
        tool = d.grounded.tool if d.grounded else ""
        eid = d.grounded.element_id if d.grounded else ""
        log.info(
            "plan_decision plan=%s goal=%s sg=%s kind=%s tool=%s eid=%s conf=%.2f rev=%s reason=%s",
            d.plan_id,
            d.goal_id,
            d.subgoal_id,
            d.kind.value,
            tool,
            eid[:48] if eid else "",
            d.confidence,
            d.revision,
            (d.reason or "")[:120],
        )


# Module singleton for AgentLoop
_PLANNER: HierarchicalPlanner | None = None


def get_hierarchical_planner(*, allow_llm: bool = False) -> HierarchicalPlanner:
    global _PLANNER
    if _PLANNER is None:
        _PLANNER = HierarchicalPlanner(allow_llm=allow_llm)
    return _PLANNER


def reset_hierarchical_planner() -> None:
    global _PLANNER
    _PLANNER = None


__all__ = [
    "HierarchicalPlanner",
    "get_hierarchical_planner",
    "reset_hierarchical_planner",
]
