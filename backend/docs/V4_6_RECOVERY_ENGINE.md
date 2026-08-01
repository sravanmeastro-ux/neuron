# NEURON V4.6 — Recovery Engine

**Date:** 2026-07-31  
**Phase:** V4.6  
**Depends on:** V4.5 VerificationEngine  
**Does not:** V4.7 NLU/context dialogue, switch default voice to HierarchicalPlanner, or a second AgentLoop

---

## 1. Existing recovery audit

| Component | Role | V4.6 disposition |
|-----------|------|------------------|
| `verifier.diagnose_failure` | String/heuristic → V3 categories + strategy hint | Reused; preferred taxonomy when OPAVR supplies `legacy_diagnosis` |
| `v3.loop_types.decide_recovery` | Bounded retry/alternate/replan/ask/fail | Still called; V4 overlays strategy/status/clarify when present |
| `brain.recover.deterministic_recovery` | Category alternate step lists (popup→esc, …) | Still supplies OPAVR `alt_probe` |
| OPAVR failure branch | retry / alternate / llm_replan / ask | Bridge: `meta["recovery_v4"]`; selective V4 step inject |
| Hierarchical `apply_action_outcome` | Subgoal status from verification | Recovery via `apply_to_plan` / `apply_recovery` |
| AgentLoop | Authoritative runtime | `recover_action`, `cancel_recovery` — no second loop |
| Semantic revalidation / perception | Target refresh | REGROUND / REOBSERVE decisions; resolver runs at act time |
| Safety classify | SAFE/CONFIRM/HIGH/BLOCKED | Alternates reclassified; BLOCKED → FAIL, no workaround |

**What already worked:** V3 category diagnose, bounded `decide_recovery`, deterministic popup/focus/monitor recoveries, OPAVR llm_replan preserving completed steps, interrupt/cancel.

**Duplication addressed:** One typed `RecoveryDecision` is the common representation; V3 strategy strings remain compatibility fields.

**Not deleted:** All V3/V3.9 recovery paths remain; V4 is additive + bridge.

**OPAVR inject policy (compat):** Only prepend V4 steps that are recovery primitives (`FOCUS_THEN_RETRY`, `WAIT`, `RETRY`, `REGROUND`, `REOBSERVE`) or safe dismiss/focus alternates (`press_keys`, `focus_app`, … / `POPUP_DETECTED`). Peer click-tool registry alternates are **not** injected into `alt_probe` so empty `deterministic_recovery` still reaches LLM replan.

---

## 2. Architecture

```
ACT → VERIFY (V4.5)
        │
   SUCCESS → CONTINUE
   FAILURE | UNCERTAIN
        │
        ▼
diagnose()  → FailureDiagnosis (category, evidence, retryable)
        │
        ▼
RecoveryEngine.decide()  → RecoveryDecision (kind + actions + budget)
        │
        ├── REOBSERVE / WAIT / REGROUND / FOCUS_THEN_RETRY
        ├── ALTERNATE_TOOL (safety-checked via ToolRegistry preference)
        ├── REPLAN / CLARIFY / FAIL / CANCEL
        ▼
execute (AgentLoop / OPAVR) → VERIFY again (never bypass V4.5)
```

**Rules:**  
- `ActionResult.ok` ≠ task success (V4.5).  
- UNCERTAIN ≠ SUCCESS; gather evidence before re-act; never spam fullscreen.  
- No blind identical retry without new observation / focus / reground / state change.  
- BLOCKED has no workaround.  
- Budget exhaustion → FAIL or CLARIFY.  
- Cycles (`category|tool|world_fp`) escalate to REPLAN/FAIL.

---

## 3. Failure taxonomy

`PERCEPTION_FAILURE`, `TARGET_NOT_FOUND`, `TARGET_STALE`, `TARGET_AMBIGUOUS`, `ELEMENT_NOT_FOUND`, `FOCUS_FAILURE`, `WINDOW_FAILURE`, `TOOL_FAILURE`, `ACTION_NO_EFFECT`, `VERIFICATION_FAILURE`, `VERIFICATION_UNCERTAIN`, `TIMEOUT`, `APPLICATION_NOT_READY`, `APPLICATION_CLOSED`, `APP_NOT_RUNNING`, `DEPENDENCY_UNMET`, `INVALID_TOOL`, `INVALID_ARGUMENTS`, `PERMISSION_DENIED`, `SAFETY_DENIED`, `USER_CANCELLED`, `CONTEXT_INSUFFICIENT`, `POPUP_DETECTED`, `WRONG_MONITOR`, `PAGE_NOT_LOADED`, `UNKNOWN_FAILURE`

Diagnosis is evidence-driven (VerificationReport + ActionResult + resolution status + optional legacy category). Not solely exception strings.

---

## 4. Recovery decision kinds

`REOBSERVE`, `REGROUND`, `RETRY`, `ALTERNATE_TOOL`, `FOCUS_THEN_RETRY`, `WAIT`, `REPLAN`, `CLARIFY`, `FAIL`, `CANCEL`

Mapped to V3 strategies: retry / alternate / replan / ask_user / blocked / fail.

---

## 5. Budgets (`RecoveryBudget`)

Centralized defaults (conservative):

| Limit | Default |
|-------|---------|
| same-action retry | 1 |
| re-observe | 2 |
| re-ground | 2 |
| alternate tool | 2 |
| replan | 2 |
| total recovery attempts | 6 |
| cycle threshold | 2 |

---

## 6. Policy highlights

| Topic | Behavior |
|-------|----------|
| Uncertain | REOBSERVE first; fullscreen never spammed; may FAIL/REPLAN if still unknown |
| Stale target | REOBSERVE → REGROUND when reference exists; else REPLAN (no peer-click invent) |
| Focus | focus target → verify → one retry of original if budget allows |
| App ready | WAIT + REOBSERVE; do not relaunch spam while starting |
| Alternate tools | ToolRegistry / preference list; BLOCKED rejected; CONFIRM/HIGH → CLARIFY |
| Coordinates | Last resort only with fresh bounds + `allow_coords`; still VERIFY |
| Replan | Preserve verified completed subgoals; revise remaining method |
| Clarify | Structured `clarify_prompt` for V4.7 presentation |
| Cancel | `Neuron stop` → `cancel()`; no further desktop recovery actions |
| History | Bounded; cycle fingerprint; no private UI content in logs |

---

## 7. Integrations

- **Package:** `neuron/v4/recover/` (`types`, `diagnose`, `engine`, `alternates`, `bridge`)
- **AgentLoop:** `recover_action`, `cancel_recovery`
- **Planner:** `apply_recovery` / `RecoveryEngine.apply_to_plan` (REPLAN, CLARIFY, FAIL, CANCEL, keep subgoal active for soft recoveries)
- **OPAVR:** `reset_recovery_engine()` per `run_opavr`; `recover_from_verification(..., legacy_diagnosis=...)`; `meta["recovery_v4"]`

---

## 8. Voice migration readiness

**Current default:** voice → CapabilityRouter / flat OPAVR  

**Target:** voice → Goal → HierarchicalPlanner → AgentLoop  

**Exact blockers before HierarchicalPlanner can be default voice path:**
1. CapabilityRouter still owns most single-step intents; Hierarchical path is opt-in (`create_task_plan` / `plan_next`).
2. No measured parity suite proving CapabilityRouter vs HierarchicalPlanner on reliability core (and LIVE-sensitive desktop tasks).
3. Multi-turn follow-ups / deixis / clarification UX still need V4.7 Context + NLU as first-class goals.
4. OPAVR still advances some mock/sparse cases via legacy hard-True deferral (documented in V4.5) — hierarchical path must not regress honesty.
5. Domain skills / learning procedures still route through CapabilityRouter; planner tool preference must cover the same surface without silent downgrade.

Recovery + Verification now work on **both** paths; switching default is deferred until the above are closed.

---

## 9. Metrics / logging

`[RECOVER][task_id][action_id]` — category, verification status, decision, attempt, budget remaining, alternate, outcome, latency (no private UI text).

Engine stats: attempts, success, failed, uncertain, cycles_blocked, clarify, replan, alternate.

---

## 10. Tests

| Suite | Requirement |
|-------|-------------|
| `run_v4_unit_tests.py` | V4.6 cases PASS |
| `run_v4_recovery_tests.py` | scenarios PASS, `RECOVERY_LOOP_COUNT=0` |
| `run_v4_recovery_smoke.py` | MOCK PASS |
| `run_v4_false_success_tests.py` | `FALSE_SUCCESS_COUNT=0` |
| Perception / Semantic / Planner / Verification smokes | PASS |
| V3 baseline | PASS=31, NEW_FAIL=0 |
| Reliability plan + mock core | exit=0 |

---

## 11. Known limitations

- REGROUND encodes intent; live SemanticElementResolver call remains at act time.
- OPAVR encodes REOBSERVE as short wait (loop always re-observes each tick).
- Coordinate fallback only when bounds + `allow_coords`.
- Domain-specific recoveries beyond ToolRegistry still lean on `deterministic_recovery`.
- Full conversational clarification presentation is V4.7.

---

## 12. Recommended V4.7 start

**Context + Natural Language Understanding:** unify ContextEngine + ReferenceResolver with HierarchicalPlanner goals; present `RecoveryKind.CLARIFY` prompts naturally; multi-turn task continuity and barge-in-aware dialogue; do not weaken VerificationEngine or RecoveryEngine contracts (`UNCERTAIN ≠ SUCCESS`, no safety bypass).
