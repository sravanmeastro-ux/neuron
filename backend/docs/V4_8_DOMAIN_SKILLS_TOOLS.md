# NEURON V4.8 — Domain Skills + Tool Integration

**Date:** 2026-07-31  
**Phase:** V4.8  
**Depends on:** V4.0–V4.7  
**Does not:** switch default voice to HierarchicalPlanner, start V4.9 learning

---

## 1. Audit summary

| Surface | Role | V4.8 disposition |
|---------|------|------------------|
| ToolRegistry / ToolSpec | Execution SSOT | Remains executor registry |
| CapabilityRouter | Fast utterance → steps | Bridged via shared IDs; not deleted |
| Domain skills (`neuron.skills`) | Dotted tools | Indexed in CapabilityCatalog |
| Procedures | `run_procedure` + learned | Planner-callable composite |
| `v4.plan.tools` | Intent preference | Delegates to catalog when built |
| `v4.recover.alternates` | Fallbacks | Prefers catalog `find_alternates` |

Ghost tools `uia_click` / `uia_type` removed from preference lists → `click_ui_element` / `type_text`.

---

## 2. Architecture

```
UnderstandingResult / Goal
        ↓
HierarchicalPlanner (ActionIntent)     CapabilityRouter (fast path)
        ↓                                         ↓
CapabilityCatalog.resolve_intent  ←──── shared capability_id / tool
        ↓
GroundedAction (validated, registered only)
        ↓
Safety (SAFE/CONFIRM/HIGH/BLOCKED)
        ↓
AgentLoop → ACT → VERIFY → RECOVER → continue
```

No second AgentLoop. Catalog is an **index**, not an executor.

---

## 3. CapabilityDescriptor

`capability_id`, `tool_name`, `domain`, `risk_hint`, `verification_kind`, `preconditions`, `planner_enabled`, `fast_path_enabled`, `recovery_enabled`, `router_id`, `aliases`, `kind` (ATOMIC/COMPOSITE/PROCEDURE), …

---

## 4. Domains registered

OS/APP/WINDOW/MONITOR/KEYBOARD/MOUSE/UI/BROWSER/YOUTUBE/MEDIA/FILE/BLENDER/SYSTEM/INTEGRATION/PROCEDURE/UNKNOWN

Only domains with real repository tools are populated.

---

## 5. Ranking

1. Intent candidate list order (domain skill first)  
2. YouTube intents prefer `youtube.*`  
3. Skip recently failed (session TTL)  
4. Skip BLOCKED  
5. Validate args via ToolRegistry  
6. Coordinates last (only if `allow_coords`)

---

## 6. Preconditions / verification

Examples: `youtube.play_result` → result index/set; `move_*` → app/window name.  
Verification kinds: APP_OPEN, WINDOW_FOCUSED, WINDOW_ON_MONITOR, URL_MATCH, PAGE_STATE, MEDIA_FULLSCREEN, …  
Executor ok ≠ task success (V4.5 unchanged).

---

## 7. Recovery integration

`suggest_recovery_alternates(intent)` → catalog → safety → GroundedAction.  
No separate hard-coded fallback ownership for covered intents.

---

## 8. Confirmation resume (blocker #3 fixed)

```
pending confirm → user "yes"
  → resume_confirmation_via_agent_loop()
  → AgentLoop.run(plan, confirmed=True)
  → observe / verify / recover
```

Expiration TTL 90s. Stale world fingerprint invalidates. Cancel clears.  
**Does not** call `executor.execute_plan` directly from `brain.handle_command`.

---

## 9. Coverage metrics (typical bootstrap)

| Metric | Value |
|--------|-------|
| Total indexed capabilities | ~188 |
| Shared router↔planner IDs | ~32 |
| LEGACY_ONLY_CAPABILITY_COUNT | 0 (with preferred skill bindings) |
| DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT | 0 for V4.8 new code |

Planner-only skills (Spotify/Discord/Blender/extra YouTube) remain available to HierarchicalPlanner without always having a CapabilityRouter pattern.

---

## 10. Tests

- `run_v4_capability_tests.py`
- `run_v4_capability_smoke.py`
- `run_v4_capability_parity.py` → `CAPABILITY_PARITY_MISMATCH_COUNT=0`
- `run_v4_capability_live.py` — dry-run default; `--live` required for mutations

---

## 11. Known limitations

- Default voice still CapabilityRouter/OPAVR for most intents  
- Some utterances skip router (parity harness SKIPs) — not counted as mismatch  
- LLM still cannot invent tools; unsupported → UNSUPPORTED_CAPABILITY  
- Procedure expansion depth left to existing `run_procedure` / AgentLoop  
- Confirm resume still uses flat one-step plan (sufficient for pending action)

---

## 12. Remaining blockers before hierarchical default

1. Measured LIVE + reliability-core parity suite beyond MOCK  
2. Canary/feature flag for voice path  
3. Richer multi-turn dialogue UX  
4. Broader LIVE capability soak tests  

---

## 13. Recommended V4.9 start

**Procedure Learning + Personalization:** learn/refine procedures from verified successes; store under existing memory policy; expose as COMPOSITE capabilities; never bypass verify/recover; personalize aliases without persisting private UI content.
