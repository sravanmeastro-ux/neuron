"""V4.6 RecoveryEngine — bounded, evidence-driven recovery.

Consumes VerificationReport FAILURE/UNCERTAIN.
Never converts UNCERTAIN → SUCCESS.
Never bypasses safety.
Never blind-retries identical action without new evidence.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.types import VerificationOutcome
from neuron.v4.recover import alternates, diagnose as diagnose_mod
from neuron.v4.recover.types import (
    FailureCategory,
    FailureDiagnosis,
    RecoveryAction,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryHistory,
    RecoveryHistoryEntry,
    RecoveryKind,
    RecoveryStatus,
)

log = logging.getLogger("neuron.v4.recover")


class RecoveryEngine:
    def __init__(self, budget: RecoveryBudget | None = None):
        self.budget = budget or RecoveryBudget()
        self.history = RecoveryHistory()
        self.last: RecoveryDecision | None = None
        self.cancelled = False
        self.stats = {
            "attempts": 0,
            "success": 0,
            "failed": 0,
            "uncertain": 0,
            "cycles_blocked": 0,
            "clarify": 0,
            "replan": 0,
            "alternate": 0,
        }
        self._last_world_fp = ""
        self._last_tool = ""
        self._last_category = ""

    def cancel(self) -> RecoveryDecision:
        self.cancelled = True
        d = RecoveryDecision(
            kind=RecoveryKind.CANCEL,
            reason="Neuron stop - recovery cancelled",
            status=RecoveryStatus.CANCELLED,
            strategy="fail",
            v3_status="INTERRUPTED",
            remaining_budget=self.budget.to_dict(),
        )
        self.last = d
        self._log(d)
        return d

    def reset_budget(self) -> None:
        self.budget = RecoveryBudget()
        self.cancelled = False

    def decide(
        self,
        *,
        verification=None,
        action_result: dict[str, Any] | None = None,
        tool: str = "",
        args: dict[str, Any] | None = None,
        expected_result: str = "",
        reference: str = "",
        element_id: str = "",
        intent: str = "",
        world=None,
        world_before_fp: str = "",
        world_after_fp: str = "",
        resolution_status: str = "",
        legacy_diagnosis: dict[str, Any] | None = None,
        interrupted: bool = False,
        task_id: str = "",
        action_id: str = "",
        subgoal_id: str = "",
        target_app: str = "",
        allow_coords: bool = False,
        state_changed_since_fail: bool = False,
    ) -> RecoveryDecision:
        t0 = time.perf_counter()
        self.stats["attempts"] += 1
        args = dict(args or {})

        if self.cancelled or interrupted or _interrupt():
            return self.cancel()

        # Optional legacy diagnose — only when caller supplies it (OPAVR bridge does).
        # Do not auto-call brain.verifier.diagnose_failure here (avoids live side effects).

        diagnosis = diagnose_mod.diagnose(
            verification=verification,
            action_result=action_result,
            tool=tool,
            args=args,
            legacy_diagnosis=legacy_diagnosis,
            resolution_status=resolution_status,
            world_before_fp=world_before_fp,
            world_after_fp=world_after_fp,
            interrupted=interrupted,
            task_id=task_id,
            action_id=action_id,
            subgoal_id=subgoal_id,
        )

        fp = world_after_fp or diagnosis.world_after_fp or ""
        cycle_fp = f"{diagnosis.category.value}|{tool}|{fp}"
        cycles = self.history.cycle_count(cycle_fp)
        if cycles >= RecoveryBudget.CYCLE_THRESHOLD:
            self.stats["cycles_blocked"] += 1
            d = RecoveryDecision(
                kind=RecoveryKind.FAIL if self.budget.remaining("REPLAN") <= 0 else RecoveryKind.REPLAN,
                diagnosis=diagnosis,
                reason=f"recovery cycle detected ({cycles}x) - escalate",
                status=RecoveryStatus.EXHAUSTED if self.budget.remaining("REPLAN") <= 0 else RecoveryStatus.READY,
                confidence=0.9,
                remaining_budget=self.budget.to_dict(),
                retry_count=self.budget.total_used,
                v3_status="FAILED" if self.budget.remaining("REPLAN") <= 0 else "NEEDS_REPLAN",
            )
            if d.kind is RecoveryKind.REPLAN and self.budget.can("REPLAN"):
                self.budget.consume("REPLAN")
                self.stats["replan"] += 1
            self._record(diagnosis, d, tool, fp, verification)
            d.latency_ms = (time.perf_counter() - t0) * 1000
            self.last = d
            self._log(d)
            return d

        if self.budget.exhausted() or not diagnosis.retryable:
            if diagnosis.category in (
                FailureCategory.SAFETY_DENIED,
                FailureCategory.PERMISSION_DENIED,
                FailureCategory.TARGET_AMBIGUOUS,
                FailureCategory.USER_CANCELLED,
            ):
                return self._terminal(diagnosis, t0, fp, tool, verification)
            d = RecoveryDecision(
                kind=RecoveryKind.FAIL,
                diagnosis=diagnosis,
                reason="recovery budget exhausted" if self.budget.exhausted() else "not retryable",
                status=RecoveryStatus.EXHAUSTED,
                remaining_budget=self.budget.to_dict(),
                v3_status="FAILED",
            )
            self.stats["failed"] += 1
            self._record(diagnosis, d, tool, fp, verification)
            d.latency_ms = (time.perf_counter() - t0) * 1000
            self.last = d
            self._log(d)
            return d

        d = self._decide_for_category(
            diagnosis,
            tool=tool,
            args=args,
            reference=reference or str(args.get("reference") or ""),
            element_id=element_id or str(args.get("element_id") or ""),
            intent=intent,
            target_app=target_app or str(args.get("name") or args.get("app") or ""),
            allow_coords=allow_coords,
            state_changed=state_changed_since_fail or (world_before_fp and world_after_fp and world_before_fp != world_after_fp),
            expected_result=expected_result,
        )
        d.diagnosis = diagnosis
        d.remaining_budget = self.budget.to_dict()
        d.retry_count = self.budget.total_used
        d.latency_ms = (time.perf_counter() - t0) * 1000
        self._record(diagnosis, d, tool, fp, verification)
        self.last = d
        self._log(d)
        return d

    def note_outcome(self, decision: RecoveryDecision, *, verification=None, ok: bool | None = None) -> None:
        """Record result of applying a recovery decision (after verify)."""
        if verification is not None:
            st = getattr(verification, "status", None) or getattr(verification, "outcome", None)
            if st is VerificationOutcome.SUCCESS:
                self.stats["success"] += 1
            elif st is VerificationOutcome.UNCERTAIN:
                self.stats["uncertain"] += 1
            else:
                self.stats["failed"] += 1
        elif ok is True:
            self.stats["success"] += 1
        elif ok is False:
            self.stats["failed"] += 1
        else:
            self.stats["uncertain"] += 1

    def apply_to_plan(self, plan, decision: RecoveryDecision, *, planner=None) -> None:
        """Map RecoveryDecision onto Hierarchical TaskPlan (no execution)."""
        from neuron.v4.plan.types import PlanStatus, StepStatus

        if plan is None or decision is None:
            return
        if decision.kind is RecoveryKind.CANCEL:
            plan.status = PlanStatus.CANCELLED
            plan.touch()
            return
        if decision.kind is RecoveryKind.CLARIFY:
            plan.status = PlanStatus.BLOCKED
            plan.meta["clarify_prompt"] = decision.clarify_prompt
            plan.meta["waiting_for_clarification"] = True
            plan.touch()
            return
        if decision.kind is RecoveryKind.FAIL:
            plan.status = PlanStatus.FAILED
            plan.meta["fail_reason"] = decision.reason
            sg = plan.current_subgoal()
            if sg:
                sg.status = StepStatus.FAILED
                sg.last_error = decision.reason
            plan.touch()
            return
        if decision.kind is RecoveryKind.REPLAN and planner is not None:
            planner.replan_bounded(plan, reason=decision.reason)
            return
        # REOBSERVE / RETRY / ALTERNATE / REGROUND / WAIT — keep subgoal active
        sg = plan.current_subgoal()
        if sg and sg.status in (StepStatus.RUNNING, StepStatus.FAILED, StepStatus.UNCERTAIN):
            sg.status = StepStatus.READY
            if decision.kind is RecoveryKind.REGROUND and decision.primary_action:
                sg.target_hints = dict(sg.target_hints or {})
                if decision.primary_action.reference:
                    sg.target_hints["reference"] = decision.primary_action.reference
            plan.touch()

    # ------------------------------------------------------------------ internals

    def _decide_for_category(
        self,
        diagnosis: FailureDiagnosis,
        *,
        tool: str,
        args: dict,
        reference: str,
        element_id: str,
        intent: str,
        target_app: str,
        allow_coords: bool,
        state_changed: bool,
        expected_result: str,
    ) -> RecoveryDecision:
        cat = diagnosis.category

        # Terminal
        if cat is FailureCategory.SAFETY_DENIED:
            return RecoveryDecision(
                kind=RecoveryKind.FAIL,
                reason="BLOCKED - no workaround",
                status=RecoveryStatus.BLOCKED,
                strategy="blocked",
                v3_status="BLOCKED",
                confidence=1.0,
            )
        if cat is FailureCategory.PERMISSION_DENIED:
            return RecoveryDecision(
                kind=RecoveryKind.CLARIFY,
                reason="permission / confirmation required",
                clarify_prompt=diagnosis.ask_prompt or "I need your confirmation to continue.",
                status=RecoveryStatus.NEEDS_CLARIFICATION,
                strategy="ask_user",
                v3_status="NEEDS_USER",
                confidence=0.95,
            )
        if cat is FailureCategory.TARGET_AMBIGUOUS:
            self.stats["clarify"] += 1
            return RecoveryDecision(
                kind=RecoveryKind.CLARIFY,
                reason="ambiguous target",
                clarify_prompt=diagnosis.ask_prompt or "Which one did you mean?",
                status=RecoveryStatus.NEEDS_CLARIFICATION,
                strategy="ask_user",
                v3_status="NEEDS_USER",
                confidence=0.9,
            )
        if cat is FailureCategory.USER_CANCELLED:
            return self.cancel()

        # UNCERTAIN / no-effect → REOBSERVE first (never spam same action)
        if cat in (
            FailureCategory.VERIFICATION_UNCERTAIN,
            FailureCategory.ACTION_NO_EFFECT,
            FailureCategory.PERCEPTION_FAILURE,
        ):
            if self.budget.can("REOBSERVE"):
                self.budget.consume("REOBSERVE")
                targets = _observe_targets(cat, tool)
                return RecoveryDecision(
                    kind=RecoveryKind.REOBSERVE,
                    actions=[RecoveryAction(
                        kind=RecoveryKind.REOBSERVE,
                        observe_targets=targets,
                        requires_verify=False,
                        reason="gather evidence before re-act",
                    )],
                    reason=f"re-observe for {cat.value}",
                    confidence=0.7,
                    v3_status="RETRY",
                )
            # No more observe — do not spam fullscreen/etc.
            if "fullscreen" in (tool or "").lower():
                self.stats["uncertain"] += 1
                return RecoveryDecision(
                    kind=RecoveryKind.FAIL,
                    reason="fullscreen still UNCERTAIN after re-observe budget - not spamming",
                    status=RecoveryStatus.EXHAUSTED,
                    v3_status="FAILED",
                    confidence=0.8,
                )
            if self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            if self.budget.can("REPLAN"):
                return self._replan(f"uncertain after reobserve: {diagnosis.reason}")
            return RecoveryDecision(kind=RecoveryKind.FAIL, reason="uncertain, budget spent", v3_status="FAILED")

        # Stale / missing target → REOBSERVE then REGROUND; no reference → REPLAN
        # (do not invent peer click tools that short-circuit OPAVR LLM replan)
        if cat in (FailureCategory.TARGET_STALE, FailureCategory.TARGET_NOT_FOUND, FailureCategory.ELEMENT_NOT_FOUND):
            if reference and self.budget.can("REGROUND"):
                acts = []
                if self.budget.can("REOBSERVE"):
                    self.budget.consume("REOBSERVE")
                    acts.append(RecoveryAction(
                        kind=RecoveryKind.REOBSERVE,
                        observe_targets=["elements", "window"],
                        requires_verify=False,
                        reason="refresh before reground",
                    ))
                self.budget.consume("REGROUND")
                acts.append(RecoveryAction(
                    kind=RecoveryKind.REGROUND,
                    reference=reference,
                    tool=tool,
                    arguments=dict(args),
                    expected_result=expected_result,
                    reason="re-resolve semantic target",
                ))
                return RecoveryDecision(
                    kind=RecoveryKind.REGROUND,
                    actions=acts,
                    reason="stale/missing target -> re-ground",
                    v3_status="RETRY",
                    confidence=0.75,
                )
            if reference and self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            return self._replan_or_fail("target missing")

        # Focus
        if cat is FailureCategory.FOCUS_FAILURE:
            app = target_app
            if app and self.budget.can("ALTERNATE_TOOL"):
                self.budget.consume("ALTERNATE_TOOL")
                self.stats["alternate"] += 1
                focus = alternates.focus_recovery_step(app)
                acts = []
                if focus:
                    acts.append(RecoveryAction(
                        kind=RecoveryKind.FOCUS_THEN_RETRY,
                        tool=focus["action"],
                        arguments=dict(focus["args"]),
                        expected_result=focus["expected_result"],
                        reason="restore focus",
                    ))
                if state_changed or True:
                    # After focus verify, one retry of original — only if budget
                    if self.budget.can("RETRY"):
                        self.budget.consume("RETRY")
                        acts.append(RecoveryAction(
                            kind=RecoveryKind.RETRY,
                            tool=tool,
                            arguments=dict(args),
                            expected_result=expected_result,
                            reason="retry after focus",
                        ))
                return RecoveryDecision(
                    kind=RecoveryKind.FOCUS_THEN_RETRY,
                    actions=acts,
                    reason=f"focus {app} then retry",
                    v3_status="RETRY",
                    confidence=0.8,
                )
            return self._replan_or_fail("focus recovery unavailable")

        # App not ready — WAIT + REOBSERVE, do not relaunch spam
        if cat in (FailureCategory.APPLICATION_NOT_READY, FailureCategory.APP_NOT_RUNNING):
            if self.budget.can("REOBSERVE"):
                self.budget.consume("REOBSERVE")
                return RecoveryDecision(
                    kind=RecoveryKind.WAIT,
                    actions=[
                        RecoveryAction(kind=RecoveryKind.WAIT, arguments={"seconds": 1.5}, requires_verify=False),
                        RecoveryAction(
                            kind=RecoveryKind.REOBSERVE,
                            observe_targets=["windows", "focus"],
                            requires_verify=False,
                            reason="wait for app window",
                        ),
                    ],
                    reason="application not ready - wait/reobserve (no relaunch spam)",
                    v3_status="RETRY",
                    confidence=0.7,
                )
            if self.budget.can("ALTERNATE_TOOL") and "open" not in (tool or "").lower():
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            # One focus alternate if open failed
            if self.budget.can("ALTERNATE_TOOL") and target_app:
                return self._alternate("focus_app", {"name": target_app}, "focus_app", False, f"{target_app} focused")
            return self._replan_or_fail("app not ready")

        if cat is FailureCategory.APPLICATION_CLOSED:
            if self.budget.can("REPLAN"):
                return self._replan("application closed - revise plan")
            return RecoveryDecision(kind=RecoveryKind.FAIL, reason="application closed", v3_status="FAILED")

        if cat is FailureCategory.WRONG_MONITOR:
            if self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, "move_monitor", allow_coords, expected_result)
            if self.budget.can("RETRY") and state_changed:
                return self._retry_once(tool, args, expected_result, "retry move after state change")
            return self._replan_or_fail("monitor placement failed")

        if cat is FailureCategory.POPUP_DETECTED:
            if self.budget.can("ALTERNATE_TOOL"):
                self.budget.consume("ALTERNATE_TOOL")
                self.stats["alternate"] += 1
                return RecoveryDecision(
                    kind=RecoveryKind.ALTERNATE_TOOL,
                    actions=[RecoveryAction(
                        kind=RecoveryKind.ALTERNATE_TOOL,
                        tool="press_keys",
                        arguments={"keys": "esc"},
                        expected_result="popup dismissed",
                        reason="dismiss popup",
                    )],
                    reason="dismiss popup",
                    v3_status="RETRY",
                )
            return self._replan_or_fail("popup")

        if cat is FailureCategory.TIMEOUT:
            if self.budget.can("REOBSERVE"):
                self.budget.consume("REOBSERVE")
                return RecoveryDecision(
                    kind=RecoveryKind.REOBSERVE,
                    actions=[RecoveryAction(
                        kind=RecoveryKind.REOBSERVE,
                        observe_targets=_observe_targets(cat, tool),
                        requires_verify=False,
                    )],
                    reason="timeout - observe before deciding",
                    v3_status="RETRY",
                )
            if self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            return self._replan_or_fail("timeout")

        if cat in (FailureCategory.TOOL_FAILURE, FailureCategory.INVALID_ARGUMENTS, FailureCategory.INVALID_TOOL):
            if cat is FailureCategory.INVALID_TOOL:
                return self._replan_or_fail("invalid tool")
            if self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            return self._replan_or_fail("tool failure")

        if cat is FailureCategory.VERIFICATION_FAILURE:
            # No blind retry
            if not state_changed and self._last_tool == tool and self._last_category == cat.value:
                if self.budget.can("ALTERNATE_TOOL"):
                    return self._alternate(tool, args, intent, allow_coords, expected_result)
                return self._replan_or_fail("verification failed, no state change")
            if self.budget.can("REOBSERVE"):
                self.budget.consume("REOBSERVE")
                return RecoveryDecision(
                    kind=RecoveryKind.REOBSERVE,
                    actions=[RecoveryAction(kind=RecoveryKind.REOBSERVE, observe_targets=_observe_targets(cat, tool))],
                    reason="verification failed - reobserve",
                    v3_status="RETRY",
                )
            if self.budget.can("ALTERNATE_TOOL"):
                return self._alternate(tool, args, intent, allow_coords, expected_result)
            return self._replan_or_fail("verification failure")

        if cat is FailureCategory.CONTEXT_INSUFFICIENT:
            self.stats["clarify"] += 1
            return RecoveryDecision(
                kind=RecoveryKind.CLARIFY,
                reason="insufficient context",
                clarify_prompt=diagnosis.ask_prompt or "I need more context.",
                status=RecoveryStatus.NEEDS_CLARIFICATION,
                strategy="ask_user",
                v3_status="NEEDS_USER",
            )

        # Default: alternate then replan — never blind retry
        if self.budget.can("ALTERNATE_TOOL"):
            return self._alternate(tool, args, intent, allow_coords, expected_result)
        if state_changed and self.budget.can("RETRY"):
            return self._retry_once(tool, args, expected_result, "retry after state change")
        return self._replan_or_fail(diagnosis.reason or "no recovery path")

    def _retry_once(self, tool, args, expected, reason) -> RecoveryDecision:
        self.budget.consume("RETRY")
        return RecoveryDecision(
            kind=RecoveryKind.RETRY,
            actions=[RecoveryAction(
                kind=RecoveryKind.RETRY,
                tool=tool,
                arguments=dict(args),
                expected_result=expected,
                reason=reason,
            )],
            reason=reason,
            v3_status="RETRY",
            confidence=0.6,
        )

    def _alternate(self, tool, args, intent, allow_coords, expected) -> RecoveryDecision:
        tried = {self._last_tool, tool} - {""}
        alts = alternates.suggest_alternates(
            tool, args, tried=tried, intent=intent, allow_coords=allow_coords
        )
        if not alts:
            return self._replan_or_fail("no safe alternate tool")
        # Safety check first alternate
        name, aargs = alts[0]
        risk = "safe"
        try:
            from neuron.safety.policy import classify
            from neuron.safety.levels import BLOCKED, CONFIRM, HIGH
            c = classify(name, aargs)
            risk = c.tier
            if c.tier == BLOCKED:
                return RecoveryDecision(
                    kind=RecoveryKind.FAIL,
                    reason=f"alternate {name} is BLOCKED - no workaround",
                    status=RecoveryStatus.BLOCKED,
                    strategy="blocked",
                    v3_status="BLOCKED",
                    safety_tier=risk,
                )
            if c.tier in (CONFIRM, HIGH):
                self.budget.consume("ALTERNATE_TOOL")
                self.stats["alternate"] += 1
                return RecoveryDecision(
                    kind=RecoveryKind.CLARIFY,
                    actions=[RecoveryAction(
                        kind=RecoveryKind.ALTERNATE_TOOL,
                        tool=name,
                        arguments=aargs,
                        expected_result=expected,
                        reason=f"confirm alternate {name}",
                    )],
                    reason=f"alternate {name} requires confirmation",
                    clarify_prompt=f"Confirm using {name}?",
                    status=RecoveryStatus.NEEDS_CLARIFICATION,
                    strategy="ask_user",
                    v3_status="NEEDS_USER",
                    safety_tier=risk,
                )
        except Exception:
            pass
        self.budget.consume("ALTERNATE_TOOL")
        self.stats["alternate"] += 1
        return RecoveryDecision(
            kind=RecoveryKind.ALTERNATE_TOOL,
            actions=[RecoveryAction(
                kind=RecoveryKind.ALTERNATE_TOOL,
                tool=name,
                arguments=aargs,
                expected_result=expected,
                reason=f"alternate for {tool}",
            )],
            reason=f"alternate tool {name}",
            safety_tier=risk,
            v3_status="RETRY",
            confidence=0.65,
        )

    def _replan(self, reason: str) -> RecoveryDecision:
        self.budget.consume("REPLAN")
        self.stats["replan"] += 1
        return RecoveryDecision(
            kind=RecoveryKind.REPLAN,
            reason=reason,
            strategy="replan",
            v3_status="NEEDS_REPLAN",
            confidence=0.7,
        )

    def _replan_or_fail(self, reason: str) -> RecoveryDecision:
        if self.budget.can("REPLAN"):
            return self._replan(reason)
        self.stats["failed"] += 1
        return RecoveryDecision(
            kind=RecoveryKind.FAIL,
            reason=reason,
            status=RecoveryStatus.EXHAUSTED,
            v3_status="FAILED",
        )

    def _terminal(self, diagnosis: FailureDiagnosis, t0, fp, tool, verification) -> RecoveryDecision:
        if diagnosis.category is FailureCategory.SAFETY_DENIED:
            d = RecoveryDecision(
                kind=RecoveryKind.FAIL, diagnosis=diagnosis,
                reason="BLOCKED", status=RecoveryStatus.BLOCKED,
                strategy="blocked", v3_status="BLOCKED",
            )
        elif diagnosis.category is FailureCategory.PERMISSION_DENIED:
            d = RecoveryDecision(
                kind=RecoveryKind.CLARIFY, diagnosis=diagnosis,
                clarify_prompt=diagnosis.ask_prompt or "Confirmation required.",
                status=RecoveryStatus.NEEDS_CLARIFICATION,
                strategy="ask_user", v3_status="NEEDS_USER",
            )
        elif diagnosis.category is FailureCategory.TARGET_AMBIGUOUS:
            d = RecoveryDecision(
                kind=RecoveryKind.CLARIFY, diagnosis=diagnosis,
                clarify_prompt=diagnosis.ask_prompt or "Which one?",
                status=RecoveryStatus.NEEDS_CLARIFICATION,
                strategy="ask_user", v3_status="NEEDS_USER",
            )
        else:
            d = self.cancel()
        d.remaining_budget = self.budget.to_dict()
        d.latency_ms = (time.perf_counter() - t0) * 1000
        self._record(diagnosis, d, tool, fp, verification)
        self.last = d
        self._log(d)
        return d

    def _record(self, diagnosis, decision, tool, fp, verification) -> None:
        vst = ""
        if verification is not None:
            st = getattr(verification, "status", None) or getattr(verification, "outcome", None)
            vst = st.value if hasattr(st, "value") else str(st or "")
        self.history.add(RecoveryHistoryEntry(
            category=diagnosis.category.value,
            kind=decision.kind.value,
            tool=tool,
            world_fp=(fp or "")[:32],
            verification=vst,
            result=decision.strategy,
            attempt=self.budget.total_used,
        ))
        self._last_world_fp = fp
        self._last_tool = tool
        self._last_category = diagnosis.category.value

    def _log(self, d: RecoveryDecision) -> None:
        cat = d.diagnosis.category.value if d.diagnosis else "-"
        log.info(
            "[RECOVER][%s][%s] cat=%s kind=%s attempt=%s budget=%s reason=%s",
            (d.diagnosis.task_id if d.diagnosis else "-") or "-",
            (d.diagnosis.action_id if d.diagnosis else d.decision_id) or "-",
            cat,
            d.kind.value,
            d.retry_count,
            d.remaining_budget.get("total", ""),
            (d.reason or "")[:100],
        )


def _observe_targets(cat: FailureCategory, tool: str) -> list[str]:
    tool_l = (tool or "").lower()
    if cat is FailureCategory.FOCUS_FAILURE:
        return ["focus", "windows"]
    if "monitor" in tool_l or cat is FailureCategory.WRONG_MONITOR:
        return ["windows", "monitors"]
    if "browser" in tool_l or "youtube" in tool_l:
        return ["browser", "focus"]
    if "click" in tool_l or "type" in tool_l:
        return ["elements", "window"]
    if cat in (FailureCategory.APPLICATION_NOT_READY, FailureCategory.APP_NOT_RUNNING):
        return ["windows", "focus"]
    return ["focus", "windows"]


def _interrupt() -> bool:
    try:
        from neuron.speech import interrupt as interrupt_mod
        return bool(interrupt_mod.interrupted())
    except Exception:
        return False


_ENGINE: RecoveryEngine | None = None


def get_recovery_engine() -> RecoveryEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RecoveryEngine()
    return _ENGINE


def reset_recovery_engine() -> None:
    global _ENGINE
    _ENGINE = None


__all__ = ["RecoveryEngine", "get_recovery_engine", "reset_recovery_engine"]
