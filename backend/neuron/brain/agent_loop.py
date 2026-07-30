"""Central AgentLoop — reliable closed-loop desktop agent execution.

USER COMMAND
  → understand goal
  → observe computer
  → create plan
  → execute ONE step
  → observe computer again
  → verify expected_result
  → continue if successful
  → retry / replan if unsuccessful
  → finish only after verifying the final goal

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
