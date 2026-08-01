# V4.9 — Procedure Learning + Personalization

**Status:** Complete  
**Constraint:** Default voice path unchanged. No second AgentLoop. No second memory system.

---

## 1. Existing learning / memory audit

| System | Role | V4.9 reuse |
|--------|------|------------|
| `neuron/learning/procedures.py` | Teach/demo save + `run_procedure` via AgentLoop | Persistence bridge + execution |
| `neuron/learning/semantic.py` | Coord drop, privacy scrub | Privacy scrub / sanitize |
| `neuron/learning/teach.py` | Demonstration teaching UX | Unchanged (USER_DEFINED) |
| `PersistentMemory` | Durable allowlisted prefs | Preference durable writes |
| `ConversationState` (V4.7) | Short-lived linguistic context | Parameter reuse / deixis |
| `DesktopWorldModel` | Live desktop | Not persisted as procedure memory |
| `CapabilityCatalog` (V4.8) | Discovery boundary | COMPOSITE registration |
| `ToolRegistry` | Tool handlers | `run_procedure` + skill ids |
| Voice recipes | Phrase → tool | Legacy phrase bindings |

**Do not duplicate:** raw conversation history as procedures; full desktop snapshots; a parallel executor.

**Default:** `agent.procedure_learning_enabled = false` — auto-learn from verified successes is off; teach/explicit accept still available for tests via `force`.

---

## 2. Architecture

```
USER GOAL
 → Planner (may select learned COMPOSITE)
 → CapabilityCatalog
 → Safety (fresh every run)
 → AgentLoop
 → ACT → VERIFY → RECOVER
 → VERIFIED SUCCESS TRACE (only)
 → ProcedureLearner (eligibility → generalize → privacy → candidate)
 → ProcedureRegistry (versioned JSON + legacy bridge)
 → CapabilityCatalog COMPOSITE
```

Learning never marks a trace verified. LLM may name/match; must validate into typed structures.

---

## 3. Boundaries

| Store | Contents |
|-------|----------|
| ConversationState | Short-lived linguistic/task context |
| DesktopWorldModel | Observable current desktop |
| TaskPlan | Execution state |
| ProcedureRegistry | Reusable workflow definitions |
| Preferences | Small durable typed choices |

---

## 4. ProcedureDefinition

Fields: `procedure_id`, `name`, `description`, `intent_family`, `parameters`, `steps`, `preconditions`, `completion_criteria`, `risk_summary`, `source` (`BUILT_IN|LEGACY|USER_DEFINED|LEARNED`), `version`, `aliases`, `enabled`, `confidence`, timestamps, verified success/failure/uncertain/recovery stats, `evidence_count`.

Stable IDs (`learned.*`). Not keyed by display name alone.

---

## 5. Eligibility (VERIFIED SUCCESS only)

Eligible only if:

- `final_status == SUCCESS`
- `task_verified`
- every required step `verification == SUCCESS`
- not cancelled / blocked
- safety_ok
- ≥ 2 semantic steps (trivial atomics rejected)

**Not eligible:** executor ok + UNCERTAIN; FAILURE; incomplete; BLOCKED.

---

## 6. VerifiedTaskTrace

Bounded: goal, intent family, capability/tools, args (scrubbed), verification outcomes, recovery flags, final evidence refs.

**Excluded:** screenshots, OCR dumps, passwords, tokens, clipboard, arbitrary UI text, raw coordinates as identity.

---

## 7. Generalization

- Prefer semantic tools over coordinates (coords dropped; cannot persist as durable steps).
- `query` / `monitor` / ordinals promoted to parameters (constants become defaults).
- App/browser parameterized only when it varies across evidence.
- Recovery-successful domain skills preferred in candidate structure.

---

## 8. Candidates / evidence

`ProcedureCandidate` before registry write. Auto-accept needs `MIN_EVIDENCE_FOR_AUTO_ACCEPT=3` (or explicit force). One-off commands do not silently fill the registry.

---

## 9. Privacy / volatile filter

Reject: passwords, tokens, session URLs, OCR/clipboard blobs, hwnd/pid/runtime ids, raw click coordinates, oversized UI text.

`PROCEDURE_PRIVACY_VIOLATION_COUNT` = **persisted** unsafe procedures (must stay 0).  
Rejects increment `PROCEDURE_PRIVACY_REJECT_COUNT` only.

---

## 10. Storage / versioning / dedup

- Primary V4 store: `backend/learned_v4_procedures.json` (schema-validated, atomic tmp replace).
- Bridge: `neuron.learning.procedures.save_procedure` for AgentLoop `run_procedure`.
- Fingerprint on intent + tool/bindings → merge evidence; version bump on deliberate update.
- Corrupt records skipped (never executable).
- `PROCEDURE_DUPLICATE_COUNT` increments only on accidental duplicate id creation (must stay 0).

---

## 11. Execution

```
Goal → match procedure → instantiate params → expand TaskPlan/subgoals
 → capability tools → Safety → AgentLoop → Verify → Recover
```

**No** opaque `run_learned_procedure()` macro replay of recorded clicks.

Intermediate verification preserved per subgoal. RecoveryEngine stays active. One failure does not rewrite the learned definition.

---

## 12. Safety

Learned procedures **never** inherit prior confirmation. Every future action is reclassified. BLOCKED remains BLOCKED. Risk summary is advisory; instantiated actions are authoritative.

---

## 13. Preferences

Scopes: `GLOBAL | DOMAIN | PROCEDURE | TASK`.

Priority: task instruction → procedure explicit → domain explicit → global explicit → inferred (≥5 evidence) → system default.

Explicit outranks inferred. Unavailable preferred tool → alternate/clarify (caller responsibility).

---

## 14. Catalog / planner

Enabled procedures register as `CapabilityKind.COMPOSITE` with `tool_name=run_procedure`.  
`HierarchicalPlanner._try_learned_procedure` expands strong alias/confidence matches into subgoals. Built-in atomic youtube templates still preferred for weak trivial searches.

---

## 15. User controls

`neuron.v4.learn.controls`: list / inspect / enable / disable / delete / add alias.

---

## 16. Learning enable/disable

`config.json` → `agent.procedure_learning_enabled` (default **false**).

---

## 17. Metrics / logs

`[LEARN]` `[PROCEDURE]` `[PREFERENCE]`

Counters: candidates, accepts, privacy rejects, duplicates merged, verified success rates.

---

## 18. Tests

| Harness | Role |
|---------|------|
| `run_v4_unit_tests.py` | Eligibility, privacy, catalog flag |
| `run_v4_procedure_tests.py` | Full V4.9 scenarios |
| `run_v4_procedure_smoke.py` | MOCK end-to-end |
| `run_v4_procedure_live.py` | Dry-run default; `--live` refuses silent exec |

---

## 19. LIVE policy

Default dry-run. No silent live learning. `--live` still does not auto-execute in the probe harness.

---

## 20. Known limitations

- Auto-learn hook is gated off by default (teach path remains primary for users).
- LLM naming/matching assist is optional; validation always required.
- Aggressive procedure optimization deferred.
- Default voice path still not HierarchicalPlanner (V4.10 blockers remain).
