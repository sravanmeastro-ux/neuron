# NEURON V4.4 — Hierarchical Goal Planner

**Date:** 2026-07-31  
**Phase:** V4.4  
**Depends on:** V4.1 DesktopWorldModel, V4.2 PerceptionEngine, V4.3 Semantic Resolution  
**Does not:** build VerificationEngine (V4.5), recovery engine (V4.6), or replace AgentLoop

---

## 1. Existing planner audit

| Component | Role | V4.4 disposition |
|-----------|------|------------------|
| `neuron.brain.planner` | Ollama JSON steps + validate | Kept — optional LLM decompose backend |
| `neuron.v3.grounded_planner` | Façade over brain.planner | Kept — compatibility |
| `neuron.v3.multi_app` | Regex staged multi-app plans | **Wrapped** via `try_multi_app_as_plan` → typed Subgoals |
| `neuron.v3.capability_router` | Deterministic single/multi capability | Unchanged — still primary for V3 `run_opavr` path |
| `neuron.brain.loop.run_opavr` | Flat `pending_steps` OPAVR | **Authoritative** execution loop |
| Domain skills / ToolRegistry | Executable tools | Constrains V4 grounded actions |
| Safety `classify` | SAFE/CONFIRM/HIGH/BLOCKED | Gates ACT → CONFIRM / FAIL |
| V4.3 `ResolutionResult` | Semantic UI targets | Consumed for click grounding |

**Decision:** Add `neuron.v4.plan.HierarchicalPlanner` beside (not instead of) GroundedPlanner. AgentLoop gains rolling `create_task_plan` / `plan_next` APIs. Default `AgentLoop.run` still uses `run_opavr` (V3 path). No second AgentLoop.

---

## 2. Architecture

```
USER GOAL
   ↓
HierarchicalPlanner.create_plan()     # templates → multi_app wrap → optional LLM
   ↓
TaskPlan { Goal, Subgoals[], status }
   ↓
plan_next(world, resolution, …)      # ROLLING — one decision
   ↓
PlanningDecision { ACT | SKIP | OBSERVE | RESOLVE | CLARIFY | CONFIRM | COMPLETE | … }
   ↓
GroundedAction (tool + validated args + element_id?)
   ↓
Safety classify → ToolRegistry (via existing AgentLoop / run_opavr)
   ↓
apply_action_outcome(ok | False | None)   # None = UNCERTAIN ≠ SUCCESS
   ↓
plan_next(…) again
```

Perception → DesktopWorldModel → Planner. Planner does **not** call Win32 directly.

---

## 3. Model

| Type | Purpose |
|------|---------|
| `Goal` | goal_id, text, normalized, constraints, apps, monitor, completion, safety |
| `TaskPlan` | plan_id, goal, subgoals, current, status, revision, source |
| `Subgoal` | intent, preconditions, completion_criteria, preferred_tools, depends_on, attempts |
| `ActionIntent` | unresolved intent (may include semantic `reference`) |
| `GroundedAction` | registered tool + args (+ element_id / confidence) |
| `PlanningDecision` | structured next step (no chain-of-thought) |

Statuses: `PlanStatus` (PENDING…CANCELLED), `StepStatus` (PENDING…UNCERTAIN).

Note: `neuron.v4.types.Goal` (V4.0 thin) remains; hierarchical goal is `neuron.v4.plan.Goal` / `PlanGoal`.

---

## 4. Rolling planning

`plan_next` never expands a giant low-level click list up front. Templates create **subgoals**; each tick grounds **one** action from world + tools + resolution.

Already-satisfied subgoals → `SKIPPED` (UNKNOWN never skips).  
Dependencies: simple `depends_on` id list (no DAG scheduler).

---

## 5. Tool selection

Centralized in `neuron.v4.plan.tools.pick_tool`:

domain skill → OS/app tool → UIA → browser → keyboard → semantic UI → coords  

Only **registered** tools become `GroundedAction`. Invalid LLM tools rejected by `validate_llm_plan_dict`.

---

## 6. Semantic grounding

For click/reference subgoals:

| ResolutionStatus | Decision |
|------------------|----------|
| RESOLVED + conf ≥ 0.45 | ACT (grounded element_id) |
| AMBIGUOUS | CLARIFY (no random pick) |
| NOT_FOUND / STALE_WORLD | OBSERVE |
| INSUFFICIENT_CONTEXT | CLARIFY |
| Low confidence | CLARIFY |

---

## 7. Safety

`classify(tool, args)` before ACT:

- BLOCKED → FAIL / plan BLOCKED  
- CONFIRM / HIGH → `WAITING_FOR_CONFIRMATION` (pending grounded action held)  
- Confirmation authorizes **only** that pending action  

---

## 8. LLM boundaries

`allow_llm=False` by default. When enabled, uses `grounded_plan` → validate → typed Subgoals. LLM output never executes directly.

Deterministic templates cover: open/focus/move/mute/volume, YouTube workflows, multi-open, click-resolve, multi_app wrap.

---

## 9. AgentLoop integration

```python
loop.create_task_plan(request)
loop.plan_next()
loop.grounded_action_to_legacy(decision)  # optional one-step run_opavr plan
loop.apply_plan_outcome(decision, ok=…)
loop.cancel_task_plan()  # also on interrupt meta from run()
```

Interrupt / “Neuron stop” → `CANCELLED`; no further ACT.

---

## 10. Multi-app compatibility

`compose_multi_app_plan` steps → `legacy_steps_to_plan`. Prefer typed multi-open / YouTube templates when they match. Regex multi_app retained as fallback.

---

## 11. Completion / verification boundary

V4.4 records tool outcomes via `apply_action_outcome`. `ok=None` → UNCERTAIN (not SUCCESS).  
**V4.5 VerificationEngine** should replace outcome guessing with world-grounded verify hooks (existing `verifier` + expected_result).

---

## 12. Performance

Deterministic templates: no LLM. Track `plan_create_ms`, `plan_next_ms`, `ground_ms`, `llm_ms` on planner.stats.

---

## 13. Tests

- `tests/run_v4_unit_tests.py` — V4.4 cases (simple, skip, youtube, semantic, multi-app, safety, cancel, AgentLoop)
- `tests/run_v4_planner_smoke.py` — mock E2E YouTube-on-monitor-2 workflow (no live control)

---

## 14. Known limitations

- Default voice path still uses CapabilityRouter + flat steps (not forced through HierarchicalPlanner yet)
- Completion still trusts caller/`ok` until V4.5
- Template coverage is finite; unusual goals need LLM or fall back to clarify
- Observe-final subgoal is a soft boundary, not full verification
- Follow-up context relies on caller passing rewritten text / context object

---

## 15. Recommended start for V4.5 VerificationEngine

1. Consume `GroundedAction.expected_result` + DesktopWorldModel diffs  
2. Map existing `neuron.brain.verifier` / `VerifyResult` → `VerificationOutcome` (keep UNCERTAIN ≠ SUCCESS)  
3. Wire `apply_action_outcome` to VerificationEngine instead of raw `ok`  
4. Do not invent a second loop — plug into `run_opavr` verify phase + hierarchical `plan_next` continuation  
