# NEURON V4 Architecture Audit

**Date:** 2026-07-31  
**Scope:** Existing repository at `c:\fillo jarvis` (V3.9 baseline)  
**Constraint:** Extend in place. Do **not** rewrite the repo or replace working V3 systems.

---

## 1. Verdict

NEURON V3.9 is already a **closed-loop local desktop assistant** with a real OPAVR path:

```
HEAR (server + speech) → UNDERSTAND (nlu/intent/refs) → PLAN → ACT → VERIFY → RECOVER
```

V4 should **unify fragmented world/perception models**, add **hierarchical rolling planning**, and harden **verification / false-success**, not invent a second AgentLoop.

**Claim level today:** Local assistant with verify/recover. **Not** fully autonomous. **Not** production-ready unattended autopilot.

---

## 2. Repository map (what exists)

### 2.1 Top level

| Path | Role |
|------|------|
| `launch-jarvis.bat` / `launch-electron.bat` | Launchers |
| `index.html` + `js/app.js` + `css/` | **Primary** voice HUD (full duplex mic PCM) |
| `frontend/` | Electron/Vite UI — status/TTS/confirm; mic PCM incomplete |
| `README.md` | Operator docs + V3 status |
| `requirements.txt` | Python deps |

### 2.2 Backend core (hot path)

| Path | Approx. LOC | Role |
|------|------------:|------|
| `backend/server.py` | ~480 | FastAPI + `/ws` — PCM → STT → `brain.handle_command` → TTS |
| `backend/brain.py` | ~1500+ | Command entry, escape hatches, AgentLoop-first, large legacy fallback |
| `backend/actions.py` | ~1060 | Legacy OS “hands” (still used via tool bootstrap) |
| `backend/browser.py` | large | Playwright Chrome control |
| `backend/config.json` | — | Models, voice, agent, safety, media gate |
| `backend/nlu.py` | — | Speech cleanup / phrase normalize |
| `backend/screen_capture.py` | — | Multi-monitor capture (used by perception/windows) |
| `backend/vision.py` / `vision_agent.py` | — | Older vision / spoken fallback |

### 2.3 Neuron packages (authoritative modern stack)

```
backend/neuron/
  brain/          # AgentLoop, planner, executor, verifier, recover, tool_registry, computer_state
  v3/             # Façades + ContextEngine, ReferenceResolver, PerceptionEngine, CapabilityRouter
  speech/         # VoicePipeline, endpoint, wake, interrupt, system_audio, TTS
  safety/         # tiers, policy, confirm, failsafe
  skills/         # youtube, browser, windows, spotify, discord, files, blender
  learning/       # procedures, semantic sanitize, teach
  windows/        # monitors, apps, state, input
  perception/     # Phase 5 pipeline (UIA → OCR → VLM)
  uia/            # Accessibility inspect/actions
  browser/        # DOM / browser agent
  memory/         # scopes + store
  tools/          # thin tool adapters into windows/browser/…
```

### 2.4 Docs & tests

| Path | Role |
|------|------|
| `backend/docs/V3_FINAL_REPORT.md` | V3.9 measured results |
| `backend/docs/V3.8_IMPLEMENTATION_REPORT.md` | Multi-monitor / semantic skills |
| `backend/tests/reliability/` | **151** workflows — plan / mock / live |
| `backend/tests/run_v3_baseline.py` | Aggregated safe suite |
| `backend/tests/run_v39_hardening_tests.py` | TEST A–D conversation scenarios |

---

## 3. Runtime path (actual)

```
Frontend WS (PCM / transcript / control)
    → server.py VoicePipeline (VAD, endpoint, media gate, wake)
    → brain.handle_command
         → confirm / stop / teach / skip_ad escape hatches
         → neuron.brain.agent.run
              → intent + ReferenceResolver + CapabilityRouter (± multi_app)
              → AgentLoop.run → loop.run_opavr
                   OBSERVE → PLAN/validate → SAFETY → ACT(one step)
                   → OBSERVE → VERIFY → diagnose → recover/retry/replan
              → ContextEngine / WorldState updates
         → on agent failure / rules_fallback → legacy brain.py regex + vision + LLM
    → TTS + optional `confirm` WS event
```

Ideal V4 loop (target):

```
RECEIVE_GOAL → UNDERSTAND → OBSERVE → GROUND → PLAN → SELECT_ACTION
→ SAFETY_CHECK → ACT → WAIT_FOR_EFFECT → OBSERVE_AGAIN → VERIFY
→ RECOVER_OR_CONTINUE → COMPLETE → LEARN (bounded)
```

Most phases **already exist**; they are split across modules and not always typed as one `AgentState`.

---

## 4. Working capabilities (keep)

| Capability | Where | Maturity |
|------------|-------|----------|
| Local Whisper STT + VAD + endpoint | `neuron/speech` | Implemented |
| Media-bleed / speaker gate | `system_audio` + endpoint | Implemented (post-V3.9) |
| Wake / conversation / barge-in / stop | speech + interrupt | Implemented |
| AgentLoop OPAVR | `brain/loop.py` | Implemented |
| Safety tiers + confirm + failsafe | `neuron/safety` | Implemented |
| ToolRegistry + skills bootstrap | `brain/tool_registry` | Implemented |
| Domain skills | `neuron/skills/*` | Implemented |
| Multi-monitor NL refs | `windows/monitors.py` | Implemented (geometry-based) |
| Grounded LLM planner (Ollama) | `brain/planner.py` | Implemented |
| Plan validator / injection resistance | `v3/plan_validator.py` | Implemented |
| Verifier + failure diagnosis | `brain/verifier.py` | Implemented |
| Adaptive recovery | `recover.py` + `v3/loop_types` | Implemented |
| Context + deixis | ContextEngine + ReferenceResolver + V4.7 ConversationEngine | Implemented |
| Semantic procedure learning | `learning/semantic.py` | Implemented |
| Reliability bench 151 × 3 modes | `tests/reliability` | Implemented |
| ComputerState live snapshot | `brain/computer_state.py` | Implemented — **best seed for DesktopWorldModel** |

---

## 5. Module-by-module notes

### 5.1 AgentLoop (`neuron/brain/loop.py` + `agent_loop.py`)

- **Reuse:** Sole closed loop. `AgentLoop` is a thin façade over `run_opavr`.
- **Extend:** Explicit lifecycle phases; typed `AgentState`; stream phase events to UI; confirm resume must re-enter loop (today confirm runs bare `execute_plan` — **skips VERIFY/RECOVER**).
- **Do not:** Create a competing second loop.

### 5.2 Understanding (`agent.py`, `intent.py`, `nlu.py`, CapabilityRouter)

- Split across NLU cleanup, intent, reference resolve, capability route, recipes.
- Works for many phrases; still regex/pattern heavy.
- **Extend:** Natural paraphrase map + single structured `Goal` before planning.
- **Gap:** Multi-clause goals often need multi_app regex or LLM flat steps, not hierarchical decomposition.

### 5.3 World / observation (fragmented — V4 priority)

| Structure | Role | Issue |
|-----------|------|-------|
| `ComputerState` | Rich live desktop capture | Closest to DesktopWorldModel |
| `v3.WorldState` | *Verified* facts only | Flat; no element tree |
| `v3.Observation` / `PerceivedElement` | Perception cascade output | Parallel shape |
| `ScreenContext` | Phase 5 text blob | Third parallel shape |
| `brain/world_model.py` | Prose for planner | Should become a *view* |

**V4.1 status:** `neuron.v4.world.DesktopWorldModel` is the structured SoT; ComputerState/WorldState/Observation/ScreenContext remain as capture/verified/perception adapters (see `docs/V4_1_DESKTOP_WORLD_MODEL.md`).

### 5.4 Perception

- **V3 PerceptionEngine** cascades API → DOM → UIA → OCR → VLM.
- **Phase 5** `neuron/perception` still underlying.
- Root `vision.py` / `vision_agent.py` remain as fallbacks.
- **Gaps:** No first-class screen-diff module API; weak stable element IDs; OCR not event-driven; coords still exist as fallback (correct) but must stay last.

### 5.5 Element + reference resolution

- V3 `ElementResolver` + V2 `brain/element_resolver` both live (**duplication**).
- ReferenceResolver is strong on deixis rules; needs joint identity with world-model entities.

### 5.6 Planner

- Real planner: `brain/planner.py` (Ollama JSON steps + grounding channels).
- `v3/grounded_planner.py`: **façade only**.
- `multi_app.py`: narrow regex staged plans — **experimental generality**.
- **Gap:** Flat `steps[]` only — no HTN / rolling “next meaningful step” planner.

### 5.7 Tools

- Real registry: `brain/tool_registry.py` (~710 LOC).
- `v3/tool_registry.py`: façade + primitives list.
- Bootstrap still wires **legacy `brain._EXECUTORS` / actions.py** and neuron tools (`overwrite=True`).
- Skills are good deterministic domain tools — prefer over mouse.

### 5.8 Verification & recovery

- Verifier is deep (~880 LOC) and category-aware.
- **Gaps:** Heuristic “no contradiction” can be soft; confirm path skips verify; not a declarative postcondition DSL; false-success is the critical V4 metric.
- Recovery bounded; WRONG_MONITOR defer-to-retry exists; coverage incomplete for many tools.

### 5.9 Safety

- Phase 8 intact — **do not weaken**.
- Planner must continue to go through `policy.allow` / confirm.
- PyAutoGUI failsafe + voice stop preserved.

### 5.10 Speech

- Preserve Whisper pipeline.
- Media gate + short safe commands (scroll/mute/cancel) recently improved.
- State machine (IDLE/LISTENING/…) exists informally via session/status strings — **formalize** for HUD.

### 5.11 Learning

- Outside AgentLoop (teach escape hatch) — OK for V4.0; later wire LEARN as post-success optional write of semantic procedures only.
- Semantic scrubbing already bans passwords/coords by default.

### 5.12 Frontend

- Legacy HUD is the working mic client.
- React frontend is display-oriented.
- **Gap:** No structured PLAN/ACT/VERIFY debug channel (optional panel for V4).

### 5.13 Reliability

- 151 tasks; PLAN/MOCK measured 100% in V3.9 report on prior machine.
- LIVE opt-in — must stay opt-in.
- **Extend to 200+** with failure injection + **false-success rate**.

---

## 6. Duplicated systems

| Pair | Nature | V4 action |
|------|--------|-----------|
| `v3/grounded_planner` ↔ `brain/planner` | Façade | Keep façade or fold into brain; no second planner |
| `v3/tool_registry` ↔ `brain/tool_registry` | Façade | Same |
| `agent_loop.py` ↔ `loop.py` | Thin wrapper | Keep |
| `actions.py` ↔ `neuron.tools` / `windows` | Dual OS stacks | Freeze actions as adapters; stop growing |
| `skills.py` (prompt) ↔ `neuron/skills` | Prose vs callables | Prefer callables; deprecate prompt growth |
| V3 `ElementResolver` ↔ `brain/element_resolver` | Dual | Unify behind one API |
| `ComputerState` / `WorldState` / `Observation` / `ScreenContext` | Parallel world views | Merge into DesktopWorldModel + views |
| `brain._execute_plan` ↔ `executor.execute_plan` | Dual executors | Legacy last-resort only |
| Legacy HUD ↔ `frontend/` | Dual UIs | Prefer one full-duplex client long-term |
| Stop/skip-ad regex in server vs brain | Duplicated phrases | Shared interrupt helper |

---

## 7. Technical debt

1. **`brain.py` size / legacy regex table** after AgentLoop — undermines single-loop purity.
2. **Confirm resume skips OPAVR** — verification hole.
3. **Three+ observation shapes** — planner/verifier/context disagree silently.
4. **PLAN bench** scores canonical shapes more than live LLM planner variance.
5. **MOCK stubs** verify success unless inject — can hide UIA flakiness.
6. **Monitor “other”** resolution depends on live foreground when window-relative context missing — tests/env sensitive (seen in baseline NEW_FAIL).
7. **God-ish modules:** `brain.py`, `verifier.py`, `tool_registry.py`, `reference_resolver.py` — extend carefully; extract, don’t rewrite.
8. **App memory / inventory JSON** on disk — local only; gitignored where personal.
9. **React mic incomplete** vs documented Electron path.

---

## 8. Experimental systems

| System | Note |
|--------|------|
| `multi_app` composer | Works for clear multi-app phrasing; not general HTN |
| openWakeWord | Optional |
| Blender render verify | Soft focus check, not full job OCR |
| Live multi-monitor on exotic layouts | Soft-pass on single display |
| CapabilityRouter free-form multi-app | Best with explicit phrasing |
| Media gate peak meter | Fails open if pycaw missing |
| VLM path in perception | Last resort; latency cost |

---

## 9. Missing capabilities (V4 gaps)

| Desired V4 piece | Status |
|------------------|--------|
| Unified `DesktopWorldModel` | **Done (V4.1)** — adapters keep legacy live |
| PerceptionEngine V4 | **Done (V4.2)** — observe + normalize_into_world |
| Semantic ElementResolver V4 | **Done (V4.3)** — world-model resolution |
| RecoveryEngine | **Done (V4.6)** — bounded, evidence-driven; OPAVR bridge |
| ConversationEngine / NLU | **Done (V4.7)** — continuity, clarify/confirm, routing policy |
| CapabilityCatalog / tools | **Done (V4.8)** — shared semantics; confirm→AgentLoop |
| First-class VerificationEngine + postcondition DSL | Partial (`verifier.py`) |
| Screen-diff as named API | Partial (`ComputerState` fingerprints) |
| Typed Goal/Task/Plan/AgentState suite | Partial (`GoalState` only) |
| ModelProvider abstraction | Coupled to Ollama helpers |
| Formal speech state machine → HUD | Informal status strings |
| LEARN inside loop (optional, scrubbed) | Outside loop |
| 200+ bench + false-success metric | 151; false-success not primary KPI |
| Optional debug panel (goal/step/verify) | Missing |
| Confirm re-enter AgentLoop | Missing |

---

## 10. Failure points (known)

| Failure | Severity | Notes |
|---------|----------|-------|
| False success (acted≠done) | **Critical** | Soft verify / confirm skip |
| Speaker bleed → wrong command | High | Mitigated by media gate; not eliminated |
| Wrong focus / wrong monitor | High | Recovery exists; still LIVE-sensitive |
| ELEMENT_NOT_FOUND / UI change | High | UIA/DOM flaky |
| Ollama down → rules_fallback | Medium | Legacy path keeps usability |
| Ambiguous deixis with no context | Medium | TEST D clarifies — keep |
| Single-monitor soft-pass | Low | Honest limitation |
| Infinite recover | Mitigated | Caps in config / loop |

---

## 11. Modules V4 can **reuse** as-is

- `neuron/brain/loop.py` (AgentLoop / OPAVR)
- `neuron/brain/executor.py`, `recover.py`, `tool_registry.py`
- `neuron/safety/*`
- `neuron/speech/*` (extend, don’t replace Whisper)
- `neuron/skills/*`
- `neuron/learning/semantic.py` + procedures store
- `neuron/windows/monitors.py` (geometry NL)
- `neuron/v3/context_engine.py`, `reference_resolver.py`, `plan_validator.py`, `loop_types.py`, `capability_router.py`
- `tests/reliability/*` (extend catalog; keep modes)
- `server.py` WS protocol (extend events; don’t break)

---

## 12. Modules V4 should **extend**

| Module | Extension |
|--------|-----------|
| `computer_state.py` + `world_state.py` | → **DesktopWorldModel** (V4.1) |
| `v3/perception_engine.py` + `perception/` | Screen-diff, stable IDs, region capture (V4.2) |
| `element_resolver` (unify V2+V3) | Semantic UI resolution (V4.3) |
| `planner.py` / `multi_app.py` | Hierarchical rolling planner (V4.4) |
| `verifier.py` | VerificationEngine + SUCCESS/FAILURE/UNCERTAIN (V4.5) |
| `recover.py` + `loop_types` | Bounded alternate-method chains (V4.6) |
| `context_engine` + ReferenceResolver | Stronger deixis + TTL (V4.7) |
| Domain skills | Semantic workflows + verify hints (V4.8) |
| `learning/procedures` | Semantic-only steps, success_rate (V4.9) |
| Reliability harness | 200+ tasks, false-success, inject (V4.10) |
| `brain.py` confirm path | Re-enter AgentLoop after confirm |
| `server.py` / HUD | Optional phase events + debug panel |

---

## 13. Modules that should **eventually be deprecated** (not deleted yet)

| Module | Reason | Migration |
|--------|--------|-----------|
| Growing regex tables in `brain.py` | Competes with AgentLoop | Freeze; route new intents to agent/skills |
| Root `skills.py` as LLM prose growth | Duplicates callable skills | Point planner at ToolRegistry docs |
| Root `vision.py` as primary click path | Superseded by UIA/perception cascade | Keep as last-resort only |
| Parallel `brain._execute_plan` for new code | No safety/timeouts | Executor only |
| Duplicate ElementResolvers | Confusion | One public API |
| Second AgentLoop (if anyone adds) | Forbidden | — |

**Do not delete** legacy adapters until LIVE coverage proves replacements; mark deprecated in docs/comments first.

---

## 14. Proposed concrete V4 architecture (based on this repo)

```
neuron/v4/                      # NEW namespace — incremental, not a fork
  types.py                      # Goal, Task, Plan, PlanStep, Observation,
                                # Action, ActionResult, VerificationResult,
                                # RecoveryDecision, AgentState
  world/                        # DesktopWorldModel (wraps ComputerState+WorldState)
  perception/                   # thin upgrades over neuron.perception + v3 engine
  verify/                       # VerificationEngine façade over brain.verifier
  plan/                         # HierarchicalPlanner extending grounded planner
  model/                        # ModelProvider / LocalModelProvider (Ollama)

neuron/brain/loop.py            # EXTEND — same loop, richer AgentState
neuron/v3/*                     # KEEP as compatibility façades during migration
```

**Rules:**

1. One AgentLoop (`run_opavr`).
2. LLM proposes structured plans only through ToolRegistry + validator + safety.
3. Success = verification, never “input sent.”
4. UNCERTAIN ≠ SUCCESS.
5. After each phase: tests green, no V3.9 regressions, docs updated.

---

## 15. Phase plan (unchanged intent, mapped to reality)

| Phase | Focus | Seed in repo |
|-------|-------|--------------|
| **V4.0** | Audit + cleanup (this doc; confirm-path note; deprecate markers; fix monitor test env bugs) | — |
| **V4.1** | DesktopWorldModel | `ComputerState` + `WorldState` |
| **V4.2** | PerceptionEngine V4 | `v3/perception_engine` + `perception/` |
| **V4.3** | Semantic ElementResolver | unify resolvers |
| **V4.4** | Hierarchical planner | `planner` + generalize `multi_app` |
| **V4.5** | VerificationEngine | `verifier.py` |
| **V4.6** | RecoveryEngine | `recover` + `loop_types` |
| **V4.7** | Context + NL | ContextEngine + intent/nlu |
| **V4.8** | Domain skill migration | `neuron/skills` |
| **V4.9** | Procedure learning | `learning/*` |
| **V4.10** | Reliability + performance | `tests/reliability` |

---

## 16. Baseline test snapshot (this audit run)

Command: `python tests/run_v3_baseline.py` from `backend/`

**Initial audit run:** PASS=28, NEW_FAIL=2 (monitor `"other"` env-sensitive).

**After V4.0 cleanup:** monitor resolution is window-relative; `run_v4_unit_tests.py` added to baseline. Re-run baseline to confirm all green.

**NEW_FAIL root cause (fixed in V4.0):**

1. `run_v38_multi_monitor_skills_tests.py` — mock move `"other"` used live foreground without window-relative context.
2. `run_monitors_phase10.py` — `move_window_to_monitor` resolved `"other"` before using the target window’s monitor.

**Fix:** Resolve hwnd first; set `relative_to` from that window’s monitor; harden phase10 mock of `_list_windows_with_monitor`.

---

## 17. Engineering rules for the upgrade

- No fake success returns.
- No TODO-only “completed” modules.
- No second competing AgentLoop.
- No weakening safety tiers.
- No automatic LIVE desktop benches.
- Prefer free/local deps; justify new ones.
- Commit-ready after each phase; truthfulness in `V4_FINAL_REPORT.md` later.

---

## 18. Immediate next step

**PHASE V4.0 — Architecture cleanup** ✅ (audit + typed state + monitor `"other"` fix)

**PHASE V4.1 — DesktopWorldModel** ✅ — see `docs/V4_1_DESKTOP_WORLD_MODEL.md`

- Unified typed `DesktopWorldModel` / `DesktopState` with adapters for ComputerState, WorldState, Observation, ScreenContext.
- AgentLoop consumes current/previous snapshots; observe path updates the model.
- Legacy structures retained; DesktopWorldModel is V4 SoT for structured desktop state.

**Next:** PHASE V4.2 — PerceptionEngine upgrades that *populate* DesktopWorldModel (screen-diff, stable IDs). Do not start until V4.1 accepted.

**PHASE V4.2 — PerceptionEngine** ✅ — see `docs/V4_2_PERCEPTION_ENGINE.md`

- `neuron.v4.perception.PerceptionEngine` observes Win32/UIA/browser/(optional OCR) into `DesktopState`.
- AgentLoop uses `normalize_into_world(observe_world_blob)` for stable IDs + screen_diff without a second full scan.
- Full `observe()` available for smoke/tests/targeted verification prep.

**Next:** PHASE V4.3 — Semantic ElementResolver on stable element IDs. Do not start until V4.2 accepted.

**PHASE V4.3 — Semantic Element Resolution** ✅ — see `docs/V4_3_SEMANTIC_ELEMENT_RESOLUTION.md`

- `SemanticElementResolver.resolve()` against `DesktopWorldModel.visible_elements`
- Ordinal / spatial / relational / deixis / AMBIGUOUS / revalidate
- `AgentLoop.semantic_resolve()` — no execution rewrite

**PHASE V4.6 — Recovery Engine** ✅ — see `docs/V4_6_RECOVERY_ENGINE.md`

- `RecoveryEngine` consumes VerificationReport; budgets; no blind retry; cycle detection
- OPAVR + HierarchicalPlanner bridges; AgentLoop `recover_action` / `cancel_recovery`
- Legacy `diagnose_failure` taxonomy preferred when present; OPAVR injects only recovery primitives / popup-focus dismiss (not peer click-tool invent)
- `FALSE_SUCCESS_COUNT=0`, `RECOVERY_LOOP_COUNT=0`; V3 baseline NEW_FAIL=0

**PHASE V4.7 — Context + NLU** ✅ — see `docs/V4_7_CONTEXT_NLU.md`

- `ConversationEngine` + `ConversationState` boundary over ContextEngine / ReferenceResolver / nlu
- Follow-ups, deixis, result sets, clarification vs confirmation, verification-gated facts
- CapabilityRouter remains default for simple commands; hierarchical routing prepared
- `ROUTING_CONTEXT_MISMATCH_COUNT=0`

**PHASE V4.8 — Domain Skills + Tools** ✅ — see `docs/V4_8_DOMAIN_SKILLS_TOOLS.md`

- `CapabilityCatalog` indexes ToolRegistry; planner WHAT→HOW via `resolve_intent`
- Confirmation resume through AgentLoop (not bare executor); TTL + scoped pending
- Recovery alternates prefer shared catalog; `CAPABILITY_PARITY_MISMATCH_COUNT=0`
- Default voice path **not** switched

**PHASE V4.9 — Procedure Learning + Personalization** ✅ — see `docs/V4_9_PROCEDURE_LEARNING.md`

- Learn only from VERIFIED SUCCESS traces; UNCERTAIN/FAILURE never become success examples
- Semantic parameterization (not coordinate macros); privacy/volatile filters
- `ProcedureRegistry` + CapabilityCatalog COMPOSITE; expand via TaskPlan/AgentLoop
- Preferences scoped; `procedure_learning_enabled` default false
- `PROCEDURE_DUPLICATE_COUNT=0`, `PROCEDURE_PRIVACY_VIOLATION_COUNT=0`
- Default voice path **still not** switched

**PHASE V4.10 — Hierarchical Voice Canary + LIVE Migration** ✅ — see `docs/V4_10_HIERARCHICAL_VOICE_MIGRATION.md`

- `voice_routing_mode` LEGACY|SHADOW|CANARY|HIERARCHICAL; `hierarchical_voice_enabled` default **false**
- SHADOW plan-only (`SHADOW_MUTATION_COUNT=0`); canary allowlist by semantic intent
- Route commit prevents legacy replay after hierarchical mutation
- Typed TTS outcomes; migration report with `READY_FOR_DEFAULT` computed (not forced)
- **Default remains LEGACY** — do not flip without LIVE/soak gates

**Remaining before hierarchical default:**

1. LIVE measured parity samples (≥20) beyond MOCK  
2. LIVE soak PASS under operator policy  
3. Latency budget validated on LIVE  
4. Explicit human review of `v4_voice_migration_report.json` then config change  

**Next:** Do not start V4.11 until default-switch decision is explicit.

---

*End of V4 architecture audit.*
