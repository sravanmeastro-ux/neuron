# NEURON V4.1 — DesktopWorldModel

**Date:** 2026-07-31  
**Phase:** V4.1  
**Depends on:** V4.0 (`neuron/v4/types.py`), V3.9 OPAVR AgentLoop  
**Does not:** replace AgentLoop, delete ComputerState/WorldState, or start V4.2 perception rewrite

---

## 1. Architecture

```
raw observation (observe_world / ComputerState / WorldState / Observation / ScreenContext)
        │
        ▼
  adapters.normalize  →  DesktopState (typed snapshot)
        │
        ▼
  DesktopWorldModel.update(...)
        │
        ├── previous DesktopState  (pre-action)
        └── current  DesktopState  (post-action / latest)
        │
        ▼
  AgentLoop / queries / to_observe_dict() → ContextEngine WorldState (compat)
```

**Owner:** `neuron.v4.world.DesktopWorldModel` (process singleton via `get_world_model()`).

**Rule:** Call sites must not mutate `DesktopState` fields in place. Always `update_*` / `record_interaction`.

---

## 2. State ownership

| Concern | Owner | Notes |
|---------|-------|-------|
| Structured desktop snapshot (V4) | **DesktopWorldModel** | Authoritative for V4 consumers |
| Live multi-source capture | `ComputerState.capture` | Still composes UIA/DOM/OCR; adapter feeds V4 |
| Verified focus for ContextEngine | `v3.WorldState` | Attempt ≠ confirmed; sync *from* DesktopState when useful |
| Perception element lists | `v3.Observation` / `ScreenContext` | Adapters only in V4.1; V4.2 will enrich model |
| Goal / retries | `GoalState` (unchanged) | Parallel to world model |
| Typed loop fields | `v4.AgentState` | Can `apply_desktop_snapshot` |

Avoid two independently mutating copies: AgentLoop pushes the same `observe_world` dict into both ContextEngine and DesktopWorldModel.

---

## 3. Typed models

| Type | Role |
|------|------|
| `DesktopState` | Full snapshot (monitors, windows, focus, cursor, elements, browser, history, confidence, fingerprint) |
| `MonitorState` | Geometry, work area, primary, roles, DPI if known |
| `WindowState` | hwnd, title, app/process, monitor, bounds, focus/minmax flags, confidence, knowledge |
| `ApplicationState` | Focused app identity + knowledge |
| `BrowserState` | URL/title/page_type/media when known |
| `UIElementState` | Semantic element (role/name/bounds/source/confidence) |
| `InteractionRecord` | Bounded scrubbed action history |
| `KnowledgeLevel` | `known` \| `inferred` \| `unknown` |

---

## 4. Legacy mapping

| Legacy | → V4 | Eventually |
|--------|------|------------|
| `ComputerState` | `from_computer_state` / `update_from_computer_state` | Keep as capture engine; demote as SoT |
| `v3.WorldState` | `from_world_state` + `sync_world_state_from_desktop` | Keep verified semantics; fields mirror DesktopState focus |
| `v3.Observation` | `from_v3_observation` | Merge into perception→world pipeline in V4.2 |
| `ScreenContext` | `from_screen_context` | Same |
| `observe_world` dict | `from_observe_dict` / `to_observe_dict` | Stay as wire format inside loop |
| `AgentState.desktop` dict | filled from DesktopState | Prefer queries on world model |

**Deprecate later (not now):** treating `ComputerState` module globals `_LAST_STATE` as the only diff source — prefer `DesktopWorldModel.diff_snapshots()`.

---

## 5. Update flow & snapshots

```python
wm = get_world_model()
wm.update_from_observe_dict(world_before)   # pushes previous
# … ACT …
wm.update_from_observe_dict(world_after)
wm.record_interaction(action, result=…, ok=…)
diff = wm.diff_snapshots()  # previous vs current
before = wm.snapshot_previous()
after = wm.snapshot()
```

Snapshots are deep copies — safe to retain across steps.

---

## 6. Query interface

- `get_foreground_window()`
- `get_active_application()`
- `get_window_by_application(name)` / `get_windows_by_application(name)` (app/process preferred over title substring)
- `get_monitor_for_window(window)`
- `resolve_monitor_reference(ref, relative_to=…, application=…)`
- `get_visible_elements(role=…)`
- `get_recent_interactions(limit=…)`
- `diff_snapshots(before, after)`
- `to_observe_dict()`

Monitor refs use **world snapshot geometry**, not hardcoded “2 = right”. Supports negative coordinates and vertical stacks. `"other"` uses `relative_to` (window monitor) when provided — preserves V4.0 fix. `"the monitor with Chrome"` uses application→window→monitor.

---

## 7. Confidence / unknown

- Empty observation → low `observation_confidence`; no fabricated focus.
- App from title only → `KnowledgeLevel.INFERRED`.
- App/hwnd from OS fields → `KNOWN`.
- Monitor from geometry / explicit id → high confidence.
- Never coerce missing data to success for verification (V4.5 will consume this).

---

## 8. AgentLoop integration

In `neuron/brain/loop.py` (`run_opavr`):

- On task start: `get_world_model().set_task_id(...)`
- Pre-act observe → `update_from_observe_dict(world_before)`
- Post-act observe → `update_from_observe_dict(world_after)` + `record_interaction`
- Meta: `world_before_fp`, `world_after_fp`, `world_diff`, `world_active_app`, `task_id`

In `neuron/brain/agent_loop.py`:

- `AgentLoop.world` → `get_world_model()`
- `current_world_snapshot()` / `previous_world_snapshot()`

Existing ContextEngine / verifier paths unchanged.

---

## 9. Files created

| Path | Role |
|------|------|
| `backend/neuron/v4/world/__init__.py` | Package exports |
| `backend/neuron/v4/world/models.py` | Typed entities |
| `backend/neuron/v4/world/model.py` | DesktopWorldModel + singleton |
| `backend/neuron/v4/world/adapters.py` | Legacy ↔ V4 |
| `backend/docs/V4_1_DESKTOP_WORLD_MODEL.md` | This document |

## 10. Files modified

| Path | Change |
|------|--------|
| `backend/neuron/v4/__init__.py` | Export world types |
| `backend/neuron/v4/types.py` | AgentState world snapshot fields + `apply_desktop_snapshot` |
| `backend/neuron/brain/loop.py` | World model update on observe |
| `backend/neuron/brain/agent_loop.py` | `.world` / snapshot accessors |
| `backend/tests/run_v4_unit_tests.py` | V4.1 coverage |
| `backend/docs/V4_ARCHITECTURE_AUDIT.md` | V4.1 status note |

---

## 11. Tests / results

```
python tests/run_v4_unit_tests.py
python tests/run_v3_baseline.py   # includes V4 units + plan/mock core
```

Coverage: creation, snapshot isolation, update/previous/diff, negative X monitors, vertical monitors, primary/left/right/other, window→monitor, app lookup, monitor-with-app, unknown/confidence, bounded history + scrub, ComputerState adapter, WorldState adapter, AgentLoop access, AgentState apply.

---

## 12. Known limitations

1. Perception depth still comes from existing `observe_world` / ComputerState — V4.1 does not add OCR/UIA capture.
2. `BrowserState.media_state` / fullscreen flags are mostly empty until V4.2/skills fill them.
3. DPI/scale only if present in monitor dicts (often absent on Windows enum).
4. Singleton world model is process-global — tests must `reset_world_model()`.
5. Confirm-resume path still skips full OPAVR (V4.0 debt); world model not updated there yet.
6. Title-only app inference remains heuristic.

---

## 13. Recommended start for V4.2

**PerceptionEngine V4:** populate `DesktopWorldModel` from a single `observe()` that cascades API→DOM→UIA→OCR with screen-diff against `wm.previous`, stable element IDs, and region capture — without replacing AgentLoop.
