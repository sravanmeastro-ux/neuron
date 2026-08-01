# NEURON V4.5 — Verification Engine

**Date:** 2026-07-31  
**Phase:** V4.5  
**Depends on:** V4.1–V4.4 (WorldModel, Perception, Semantic Resolve, Hierarchical Planner)  
**Does not:** RecoveryEngine (V4.6), skill migration (V4.8), or a second AgentLoop

---

## 1. Existing verification audit (summary)

| Path | Finding |
|------|---------|
| `neuron.brain.verifier.VerifyResult` | Binary `ok: bool` — soft-True paths treat missing evidence as success |
| `run_opavr` | Advanced on `vr.ok and act_ok`; ignored screen_diff |
| `HierarchicalPlanner.apply_action_outcome` | Trusted caller `ok=True` as SUCCEEDED |
| `ToolSpec.verify` | Stub, unused |
| Screen diff / revalidate | Available but unused by verifier |
| Soft notes (`soft-accept`, `no contradiction`, …) | Fake-success risk |

**Decision:** Add authoritative `neuron.v4.verify.VerificationEngine`. Keep `brain.verifier` for V3. Bridge in OPAVR: world-checkable actions require V4 **SUCCESS** to advance; non-observable (e.g. volume) fall back to legacy with `verification_not_observable` meta.

---

## 2. Architecture

```
GroundedAction / step
        │
        ▼
ActionResult          ← executor only (executed / error)
        │
        ▼
OBSERVE (targeted) → DesktopWorldModel.current (+ previous)
        │
        ▼
VerificationEngine.verify(expectation, before, after, screen_diff, action_result)
        │
        ▼
VerificationReport { SUCCESS | FAILURE | UNCERTAIN }
        │
        ├── AgentLoop / run_opavr (advance only on SUCCESS)
        └── HierarchicalPlanner.apply_verification(...)
```

**Rule:** `ActionResult.ok` never alone yields SUCCESS.

---

## 3. Types

- `VerificationExpectation` + `ExpectationKind` (typed; not prose)
- `VerificationEvidence` (bounded facts, sources, conflicts)
- `VerificationReport` (status, confidence, method, latency, retryable, cancelled)
- Reuses `neuron.v4.types.VerificationOutcome`

---

## 4. Strategies implemented

| Kind | Evidence |
|------|----------|
| APP_OPEN / WINDOW_EXISTS | Window query (process-without-window → UNCERTAIN) |
| WINDOW_FOCUSED | Foreground app/window |
| WINDOW_ON_MONITOR | Geometry / monitor_id (neg/vertical OK) |
| WINDOW_MAXIMIZED / WINDOW_FULLSCREEN | `classify_fullscreen` |
| MEDIA_FULLSCREEN | `BrowserState.fullscreen` — maximized ≠ media FS |
| URL_MATCH / PAGE_STATE | Browser URL (title-only → UNCERTAIN) |
| ELEMENT_* | Presence / revalidate / weak screen_diff |
| TEXT_IN_FIELD | Observable value; sensitive → UNCERTAIN |
| SCREEN_CHANGED | Weak alone; trivial score → UNCERTAIN |
| NONE (volume) | Not world-observable → UNCERTAIN |

---

## 5. Confidence / conflicts

Central thresholds: `CONF_HIGH=0.85`, `CONF_MEDIUM=0.55`, `CONF_LOW=0.35`, `CONF_SUCCESS_MIN=0.55`.

Conflicts (e.g. maximized vs media fullscreen unknown) → UNCERTAIN, not SUCCESS.

Evidence precedence: WIN32 window/geometry > deterministic browser URL > title-only > screen_diff alone > ActionResult.

---

## 6. Wait / cancel

`wait_until` polls with per-expectation timeouts (focus short, open_app longer, browser longer).  
`Neuron stop` / interrupt cancels polling promptly.

---

## 7. AgentLoop / planner

- `AgentLoop.verify_action(...)` → `VerificationReport`
- `apply_plan_outcome(..., verification=)` — `ok=True` without verification → UNCERTAIN
- `HierarchicalPlanner.apply_verification` / `plan_is_complete` (SUCCEEDED|SKIPPED only)

---

## 8. OPAVR bridge

After legacy `verify_execution_step`:

1. Run `VerificationEngine.verify_step` (no live legacy re-entry).
2. Store `meta["verification_v4"]`.
3. If expectation **not_observable** → keep legacy advancement; set `verification_not_observable`.
4. Else if `agent.v4_verify_authoritative` (default **true**):
   - V4 **SUCCESS** → advance
   - V4 **FAILURE** → block (prefer legacy failure text for diagnose); **except** sparse/mock worlds (`active_application=mock` / no hwnd) with hard legacy True → defer (harness compat)
   - V4 **UNCERTAIN** → block soft-legacy; defer only to **hard** legacy True (recovery tests)
5. Flag `legacy_ok_but_v4_not_success` / `legacy_soft_blocked_by_v4` when they disagree.

Migration path: CapabilityRouter/flat steps → HierarchicalPlanner + `verify_action` + `apply_verification`. Voice path remains until later phase flips routing.

Config:

- `agent.v4_verify_authoritative` (default true)
- `agent.v4_verify_wait` (default false — avoid long sleeps on every OPAVR step; hierarchical/tests can wait)

---

## 9. Remaining caller-ok / false-success risks

| Risk | Status |
|------|--------|
| Hierarchical `ok=True` without verification | Now UNCERTAIN |
| OPAVR volume/mute | Legacy (not_observable) — documented |
| Soft legacy when authoritative off | Meta `legacy_false_success_risk` |
| Chat-only `Done.` with no tools | Unchanged legacy |
| ToolSpec.verify still empty | Future domain hooks |

---

## 10. Tests

- `run_v4_unit_tests.py` — V4.5 cases
- `run_v4_false_success_tests.py` — **FALSE_SUCCESS_COUNT=0**
- `run_v4_verification_smoke.py` — read-only facts

---

## 11. Known UNKNOWN areas

- Media fullscreen without browser.fullscreen signal
- System volume / mute observability
- Click without semantic expected transition
- Title-only browser inference
- Password field values (intentionally unverified)

---

## 12. Recommended start for V4.6 RecoveryEngine

1. Consume `VerificationReport` FAILURE/UNCERTAIN + `diagnose_failure` categories  
2. Bounded strategies: retry / alternate tool / replan / clarify (reuse `v3.loop_types.decide_recovery`)  
3. Wire into `run_opavr` failure branch + hierarchical `apply_verification`  
4. Never invent success; UNCERTAIN may re-observe then recover  
5. No second AgentLoop  
