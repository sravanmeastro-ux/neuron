"""Central AgentLoop — reliable closed-loop desktop agent execution.

V3.7 adaptive loop:
  OBSERVE → UNDERSTAND → PLAN → SAFETY CHECK → ACT → VERIFY
  on failure: diagnose → observe → retry / alternate / replan / ask user

This is a thin public facade over Phase 9 OPAVR (`run_opavr`).
Existing callers via neuron.brain.agent.run / brain.handle_command are unchanged.
"""

from __future__ import annotations

from typing import Any

from neuron.brain.goal import GoalState
from neuron.brain.loop import run_opavr
from neuron.brain.trace import Trace


class AgentLoop:
    """Closed-loop desktop agent.

    Prefer this entry when you want an explicit AgentLoop API.
    Internally delegates to run_opavr so behavior stays singular.
    """

    def __init__(
        self,
        *,
        confirmed: bool = False,
        trace: Trace | None = None,
    ):
        self.confirmed = confirmed
        self.trace = trace or Trace()
        self.last_goal: GoalState | None = None
        self.last_meta: dict[str, Any] = {}
        self._task_plan = None  # V4.4 TaskPlan | None
        self._planner = None

    @property
    def world(self):
        """V4.1 DesktopWorldModel — current/previous desktop snapshots."""
        from neuron.v4.world import get_world_model
        return get_world_model()

    @property
    def active_task_plan(self):
        """V4.4 hierarchical TaskPlan (if any)."""
        return self._task_plan

    def _hierarchical_planner(self):
        if self._planner is None:
            from neuron.v4.plan import get_hierarchical_planner
            self._planner = get_hierarchical_planner()
        return self._planner

    def create_task_plan(
        self,
        request: str,
        *,
        normalized: str = "",
        context=None,
        allow_llm: bool = False,
    ):
        """V4.4: decompose a user goal into a typed TaskPlan (no execution)."""
        from neuron.v4.plan import Goal as PlanGoal

        planner = self._hierarchical_planner()
        planner.allow_llm = allow_llm
        goal = PlanGoal(text=request, normalized=normalized or request)
        plan = planner.create_plan(
            request,
            normalized=normalized or request,
            context=context,
            goal=goal,
            world=self.world,
            allow_llm=allow_llm,
        )
        self._task_plan = plan
        try:
            self.world.set_task_id(plan.plan_id)
        except Exception:
            pass
        return plan

    def plan_next(
        self,
        *,
        confirmed: bool | None = None,
        resolution=None,
        last_result: dict | None = None,
        context=None,
    ):
        """V4.4: rolling next PlanningDecision from active TaskPlan + world."""
        planner = self._hierarchical_planner()
        if self._task_plan is not None:
            planner.load_plan(self._task_plan)
        decision = planner.plan_next(
            self._task_plan,
            world=self.world,
            context=context,
            resolution=resolution,
            confirmed=self.confirmed if confirmed is None else confirmed,
            last_result=last_result,
        )
        self._task_plan = planner.active_plan
        return decision

    def cancel_task_plan(self):
        """V4.4: cancel hierarchical plan (Neuron stop)."""
        planner = self._hierarchical_planner()
        plan = planner.cancel(self._task_plan)
        self._task_plan = plan
        return plan

    def apply_plan_outcome(
        self,
        decision,
        *,
        ok: bool | None = None,
        detail: str = "",
        verification=None,
    ):
        """V4.5: prefer VerificationOutcome/Report; caller ok alone ≠ success."""
        if self._task_plan is None or decision is None:
            return
        self._hierarchical_planner().apply_action_outcome(
            self._task_plan,
            decision,
            ok=ok,
            detail=detail,
            world=self.world,
            verification=verification,
        )

    def verify_action(
        self,
        *,
        grounded=None,
        step: dict | None = None,
        action_result=None,
        world_before=None,
        screen_diff=None,
        wait: bool = True,
        refresh=None,
    ):
        """V4.5: run VerificationEngine against current world."""
        from neuron.v4.verify import get_verification_engine

        eng = get_verification_engine()
        task_id = ""
        if self._task_plan is not None:
            task_id = self._task_plan.plan_id
        if grounded is not None:
            return eng.verify_grounded_action(
                grounded,
                world_before=world_before,
                world=self.world,
                screen_diff=screen_diff,
                action_result=action_result,
                task_id=task_id,
                wait=wait,
                refresh=refresh,
            )
        if step is not None:
            return eng.verify_step(
                step,
                world_before=world_before,
                world=self.world,
                screen_diff=screen_diff,
                action_result=action_result,
                task_id=task_id,
                wait=wait,
                refresh=refresh,
            )
        return eng.verify(
            world=self.world,
            action_result=action_result,
            task_id=task_id,
            wait=False,
        )

    def recover_action(
        self,
        *,
        verification=None,
        step: dict | None = None,
        action_result=None,
        interrupted: bool = False,
        state_changed: bool = False,
    ):
        """V4.6: decide recovery from VerificationReport / failure."""
        from neuron.v4.recover import recover_from_verification, get_recovery_engine

        task_id = ""
        if self._task_plan is not None:
            task_id = self._task_plan.plan_id
        decision = recover_from_verification(
            verification=verification,
            step=step or {},
            action_result=action_result if isinstance(action_result, dict) else (
                {"ok": getattr(action_result, "ok", None), "message": getattr(action_result, "message", "")}
                if action_result is not None else {}
            ),
            world=self.world,
            task_id=task_id,
            interrupted=interrupted,
            state_changed=state_changed,
        )
        if self._task_plan is not None:
            get_recovery_engine().apply_to_plan(
                self._task_plan,
                decision,
                planner=self._hierarchical_planner(),
            )
        return decision

    def cancel_recovery(self):
        """V4.6: cancel active recovery (Neuron stop)."""
        from neuron.v4.recover import get_recovery_engine
        d = get_recovery_engine().cancel()
        self.cancel_task_plan()
        try:
            from neuron.v4.context import cancel_for_stop
            cancel_for_stop()
        except Exception:
            pass
        return d

    def grounded_action_to_legacy(self, decision) -> dict | None:
        """Convert ACT PlanningDecision into a one-step AgentLoop plan dict."""
        if decision is None or getattr(decision, "grounded", None) is None:
            return None
        ga = decision.grounded
        return {
            "say": (self._task_plan.goal.text[:120] if self._task_plan else ""),
            "steps": [ga.to_legacy_step()],
            "source": "v4_hierarchical",
            "plan_id": getattr(decision, "plan_id", ""),
            "meta": {"v4_decision": decision.kind.value if hasattr(decision.kind, "value") else str(decision.kind)},
        }

    def current_world_snapshot(self):
        return self.world.snapshot()

    def previous_world_snapshot(self):
        return self.world.snapshot_previous()

    def last_perception(self):
        """Latest V4.2 PerceptionResult (if any)."""
        from neuron.v4.perception import get_perception_engine
        return get_perception_engine().last

    def semantic_resolve(self, reference: str, *, context=None, allow_stale: bool = False):
        """V4.3: resolve a natural UI reference against DesktopWorldModel (no click)."""
        from neuron.v4.resolve import context_from_engine, get_semantic_resolver
        ctx = context
        if ctx is None:
            try:
                ctx = context_from_engine(world=self.world)
            except Exception:
                ctx = None
        return get_semantic_resolver().resolve(
            reference, world=self.world, context=ctx, allow_stale=allow_stale
        )

    def revalidate_element(self, element_id: str, *, prior=None):
        """V4.3: check whether a previously resolved element is still valid."""
        from neuron.v4.resolve import get_semantic_resolver
        return get_semantic_resolver().revalidate(element_id, world=self.world, prior=prior)

    def run(
        self,
        request: str,
        *,
        context: str = "",
        normalized: str = "",
        plan: dict | None = None,
        observe_blob: str = "",
        confirmed: bool | None = None,
    ) -> tuple[str | None, bool, dict[str, Any], GoalState]:
        """
        Run the full closed loop for one user command.

        Returns (say, acted, meta, goal_state).
        """
        say, acted, meta, goal = run_opavr(
            request=request,
            context=context,
            normalized=normalized,
            plan=plan,
            confirmed=self.confirmed if confirmed is None else confirmed,
            observe_blob=observe_blob,
            trace=self.trace,
        )
        # V4.4: keep hierarchical plan in sync with interrupt / cancel
        try:
            if meta.get("interrupted") or (goal and getattr(goal, "status", "") == "interrupted"):
                self.cancel_task_plan()
                try:
                    from neuron.v4.recover import get_recovery_engine
                    get_recovery_engine().cancel()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from neuron.memory import scopes
            scopes.working().sync_goal_state(goal)
            # Note open_app / browser targets into session apps
            for entry in (getattr(goal, "action_history", None) or []):
                args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
                for key in ("name", "app", "query", "url", "site"):
                    val = args.get(key)
                    if not val:
                        continue
                    s = str(val).strip()
                    if key in ("url", "site") or "://" in s or "." in s and " " not in s:
                        scopes.session().note_site(s)
                    else:
                        scopes.session().note_app(s)
        except Exception:
            pass
        meta = dict(meta)
        meta["path"] = meta.get("path") or "agent_loop"
        meta["trace"] = self.trace.to_list()
        meta["goal"] = goal.to_dict() if goal else None
        try:
            wm = self.world
            meta.setdefault("world_after_fp", wm.current.ensure_fingerprint())
            meta["world_active_app"] = wm.get_active_application()
        except Exception:
            pass
        self.last_goal = goal
        self.last_meta = meta
        return say, acted, meta, goal

    def run_plan(
        self,
        request: str,
        plan: dict,
        *,
        context: str = "",
        confirmed: bool | None = None,
    ) -> tuple[str | None, bool, dict[str, Any], GoalState]:
        """Execute a pre-built structured plan under the closed loop."""
        return self.run(
            request,
            context=context,
            plan=plan,
            confirmed=confirmed,
        )


def run_agent_loop(
    request: str,
    *,
    context: str = "",
    normalized: str = "",
    plan: dict | None = None,
    confirmed: bool = False,
    observe_blob: str = "",
) -> tuple[str | None, bool, dict[str, Any], GoalState]:
    """Module-level convenience wrapper."""
    return AgentLoop(confirmed=confirmed).run(
        request,
        context=context,
        normalized=normalized,
        plan=plan,
        observe_blob=observe_blob,
    )
