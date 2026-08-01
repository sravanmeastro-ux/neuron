# V4.10 — Hierarchical Voice Canary + LIVE Migration

**Status:** Complete (default remains LEGACY)  
**Constraint:** One AgentLoop. No VoiceAgentLoop. Procedure learning stays OFF.

---

## 1. Legacy voice architecture (audited)

```
js/app.js mic PCM
 → server.py /ws VoicePipeline.push_pcm (Whisper STT)
 → server._run_command
 → brain.handle_command (nlu.understand)
 → confirm/stop escapes
 → neuron.brain.agent.run
 → V4.7 understand_for_agent
 → intent.understand + CapabilityRouter.route
 → AgentLoop.run → run_opavr → executor
 → server._send_command_response → TTS
```

Confirmation `"yes"` → `resume_confirmation_via_agent_loop` (early in `brain.handle_command`).  
Stop → `server` interrupt first; brain `is_stop_phrase`; AgentLoop polls interrupt.

---

## 2. Hierarchical voice path (opt-in)

Same STT → `brain` → `agent.run`, then **before** CapabilityRouter:

```
maybe_handle_voice
 → VoiceRequest (request_id, normalized transcript)
 → decide_route (LEGACY|SHADOW|CANARY|HIERARCHICAL)
 → SHADOW: compare_shadow (no mutate) → fall through legacy execute
 → CANARY/HIERARCHICAL: HierarchicalPlanner → plan → Safety → AgentLoop.run
 → typed outcome → TTS language
```

No second executor.

---

## 3. Routing modes

| Mode | Behavior |
|------|----------|
| **LEGACY** | Production path only (default) |
| **SHADOW** | Legacy executes; hierarchical plans/compares only |
| **CANARY** | Allowlisted intents may execute hierarchical; else legacy |
| **HIERARCHICAL** | Hierarchical primary; deny rules still force legacy for unsafe |

Master flag: `agent.hierarchical_voice_enabled` (default **false**).  
Without master flag, all modes fail closed to **LEGACY**.

Config:

```json
"hierarchical_voice_enabled": false,
"voice_routing_mode": "LEGACY"
```

---

## 4. Canary allowlist (semantic intents)

`APP_OPEN`, `WINDOW_FOCUS`, `WINDOW_MOVE`, `WINDOW_MAXIMIZE`, `BROWSER_NAVIGATE`, `YOUTUBE_SEARCH`, `YOUTUBE_HOME`, `VOLUME_SIMPLE`, `MUTE`

**Deny:** sensitive/destructive language, forbidden tools, high/blocked risk, low STT confidence (when present), learned procedures (`run_procedure` / `learned.*`), missing verification family.

---

## 5. Route commit

`begin_route` → before first mutation: fallback to legacy allowed.  
`mark_mutation` → committed: **no** full legacy replay (prevents duplicate open).

---

## 6. Shadow

Plans via `HierarchicalPlanner.create_plan` then `cancel`. Never calls mutating tools.  
Metrics: `VOICE_SHADOW_MISMATCH_COUNT`, `SHADOW_MUTATION_COUNT` (required 0).

---

## 7. Response / TTS outcomes

Typed: `SUCCESS | FAILURE | UNCERTAIN | WAITING_FOR_CONFIRMATION | WAITING_FOR_CLARIFICATION | CANCELLED`.  
Hierarchical path must not emit bare “Done.” for UNCERTAIN/FAILURE (`UNVERIFIED_COMPLETION_RESPONSE_COUNT`).

---

## 8. Confirmation / clarification / cancel

Unchanged owners: brain confirm regex → AgentLoop resume; V4.7 clarification pending; stop/interrupt cancels hierarchical plan + TTS.

---

## 9. Migration gates / READY_FOR_DEFAULT

`MigrationReadinessReport.ready_for_default` is **computed**. Requires LIVE + soak PASS, sample thresholds, all safety/parity gates.  

V4.10 leaves default **LEGACY** and typically `READY_FOR_DEFAULT=false` until LIVE/soak are run and reviewed.

Report: `backend/tests/v4_voice_migration_report.json`

---

## 10. Rollback (config only)

1. `hierarchical_voice_enabled=false`  
2. `voice_routing_mode=LEGACY`  
3. Restart / reload  
4. Say cancel / Neuron stop for pending confirm/tasks  

---

## 11. LIVE policy

All harnesses default dry-run. `--live` required. Soak bounded by max tasks/runtime. Procedure learning remains false.

---

## 12. Tests

| Harness | Role |
|---------|------|
| `run_v4_voice_shadow.py` | Shadow parity, mutation=0 |
| `run_v4_voice_canary.py` | Eligibility, commit, safety |
| `run_v4_voice_smoke.py` | End-to-end MOCK + report |
| `run_v4_voice_live.py` | LIVE probe (default NOT_RUN) |
| `run_v4_voice_soak.py` | Soak (default NOT_RUN) |

---

## 13. Known limitations

- Default still LEGACY / flag off  
- LIVE measured parity and soak still required before default switch  
- Multi-turn dialogue UX uses existing ConversationState (not a new chat stack)  
- Latency percentiles need larger LIVE samples  
- Optional mic/TTS hardware tests are manual, not CI
