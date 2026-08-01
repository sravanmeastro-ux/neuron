# NEURON V4.7 — Context + Natural Language Understanding

**Date:** 2026-07-31  
**Phase:** V4.7  
**Depends on:** V4.0–V4.6  
**Does not:** switch default voice to HierarchicalPlanner, rewrite Whisper, start V4.8

---

## 1. Existing context/NLU audit

| Component | Role | V4.7 disposition |
|-----------|------|------------------|
| `nlu.py` | Fillers, STT mishears, polish | Reused; casual variants extended (`bring up`, `I need`) |
| `neuron.brain.intent` | stop/recipe/deterministic/llm kinds | Reused on agent path |
| `v3.capability_router` | Fast deterministic plans | Remains default for simple commands |
| `v3.context_engine` | Session events + WorldState | Reused as verified desktop event store |
| `v3.reference_resolver` | Deixis rewrite / clarify | Bridged from ConversationEngine |
| `brain.resolver` (Phase 8) | Snapshot ordinals | Unchanged parallel on LLM path |
| `v4.SemanticElementResolver` | Live UI match | Unchanged |
| Safety `confirm` / `policy` | Confirmation pending | Separate from ClarificationState |
| Recovery `CLARIFY` | Structured prompt | Populates pending clarification |

**Decision:** Add `neuron.v4.context.ConversationEngine` as the conversational boundary. Do **not** create a second ContextEngine or NLU stack.

---

## 2. Ownership boundaries

| Store | Owns |
|-------|------|
| DesktopWorldModel | Observable desktop |
| ConversationState | Linguistic refs, task continuity, result sets, pending clarify/confirm |
| TaskPlan | Goal/subgoal execution |
| Persistent memory | Durable prefs/procedures only (existing policy) |

ConversationState stores IDs/refs — not full UI dumps or passwords.

---

## 3. Architecture

```
USER UTTERANCE
      ↓
normalize (nlu + casual) → ParsedUtterance
      ↓
parse → GoalCandidate (deterministic families)
      ↓
pending CONFIRM? → ConfirmationState (scoped)
pending CLARIFY? → ClarificationState (resume)
      ↓
detect continuity (NEW / FOLLOW_UP / CORRECTION / ELLIPSIS / CANCEL)
      ↓
ReferenceResolver bridge + result-set / task expansion
      ↓
UnderstandingResult + RouteDest
      ↓
FAST_PATH (CapabilityRouter)  |  HIERARCHICAL (opt-in)  |  CLARIFY
```

AgentLoop remains authoritative. HierarchicalPlanner is **not** the default voice path yet.

---

## 4. Normalization

- Fillers / politeness / STT via `nlu.py`
- Casual: bring up, I need, open up, start/launch → open
- Self-correction: `open Spotify, no, Chrome` → final Chrome
- Leading `actually …` treated as correction/follow-up
- Negation preserved explicitly (`don't open …` → REJECT, not stripped)

---

## 5. Intent families

OPEN, CLOSE, FOCUS, MOVE, SEARCH, NAVIGATE, PLAY, PAUSE, CLICK, TYPE, SELECT, SCROLL, VOLUME, MULTI_STEP_GOAL, FOLLOW_UP, CORRECTION, CANCEL, CONFIRMATION, CLARIFICATION_RESPONSE, FULLSCREEN, STOP, UNKNOWN, …

Deterministic first. LLM not used for mute/stop/open known apps; LLM never executes tools.

---

## 6. Follow-ups / multi-turn

Verified task facts (app, monitor, query, result set) drive continuity.

Example: Open Chrome on monitor 2 → Go to YouTube → Search Blender → Play first → Fullscreen.

Stale assumptions invalidated when verification fails or world contradicts.

---

## 7. Deixis / result sets / freshness

- Pronouns bridged through ReferenceResolver + task active app / result set
- Ordinals use fresh ResultSet only
- Central TTLs in `FRESHNESS_TTL` (element 45s, result set 120s, clarify 120s, …)
- No random resolution when referent missing → CLARIFY

---

## 8. Clarification vs confirmation

| | Clarification | Confirmation |
|---|---------------|--------------|
| Meaning | Ambiguous target/intent | Known action needs authorization |
| State | `ClarificationState` | `ConfirmationState` |
| “yes” | Only if yes_no / single option | Authorizes exact pending action |
| Unrelated command | Does not resolve | Does **not** authorize |

RecoveryKind.CLARIFY → `on_recovery_clarify` → pending clarification.

---

## 9. Verification-driven updates

- SUCCESS → strong facts (app, monitor, query, fullscreen true)
- UNCERTAIN → mark unknown (e.g. media_fullscreen)
- FAILURE → do **not** claim success facts (e.g. monitor 2)

---

## 10. Routing policy (migration-ready)

| Example | Route |
|---------|-------|
| mute / open chrome / volume up | FAST_PATH |
| open chrome on monitor 2 | HIERARCHICAL |
| compound multi-step | HIERARCHICAL |
| follow-up / play first one | HIERARCHICAL |
| ambiguous / no referent | CLARIFY |
| don't open X | REJECT |

CapabilityRouter still executes most single-step voice intents. Fast path updates ConversationState on verify so later “move it …” shares semantics.

---

## 11. Privacy

No persistence of full transcripts, OCR dumps, form contents, passwords. Bounded turns/entities only.

---

## 12. Tests

- `run_v4_unit_tests.py` V4.7 cases
- `run_v4_context_tests.py` — multi-turn, clarify, confirm, verify rules, parity
- `run_v4_context_smoke.py` — clarify resume demo
- Required: `ROUTING_CONTEXT_MISMATCH_COUNT=0`, `FALSE_SUCCESS_COUNT=0`, `RECOVERY_LOOP_COUNT=0`

---

## 13. Known limitations

- HierarchicalPlanner still opt-in for voice
- LLM compound decomposition not fully wired (deterministic compound split only)
- Confirm resume still has legacy executor-only debt in `brain.handle_command` (documented earlier)
- Media identity may remain UNKNOWN when perception cannot establish it
- Phase 8 resolver remains a parallel path on LLM planning

---

## 14. Remaining blockers before HierarchicalPlanner default

1. Measured CapabilityRouter vs HierarchicalPlanner parity on reliability core + LIVE
2. Domain skills/procedures full planner coverage
3. Confirm resume through AgentLoop (not bare executor)
4. Richer multi-turn dialogue UX polish
5. Opt-in flag / canary before flipping default

---

## 15. Recommended V4.8 start

**Domain Skills + Tool Integration:** register domain skills as first-class HierarchicalPlanner tool preferences; unify CapabilityRouter capabilities with ToolRegistry intents; ensure skill failure → RecoveryEngine alternate without hard-coded chains; keep ConversationState semantics shared.
