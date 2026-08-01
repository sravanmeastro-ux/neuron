# NEURON V4.2 — Perception Engine

**Date:** 2026-07-31  
**Phase:** V4.2  
**Depends on:** V4.1 DesktopWorldModel  
**Does not:** replace AgentLoop, replace DesktopWorldModel, implement ElementResolver (V4.3), or claim LIVE autonomy

---

## 1. Architecture

```
Win32 / UIA / browser / (optional OCR/screen)
        │
        ▼
PerceptionEngine.observe(...)     # full gather
   or normalize_into_world(blob)  # AgentLoop cheap path
        │
        ▼
PerceptionResult { desktop: DesktopState, failures, timing, screen_diff, … }
        │
        ▼
DesktopWorldModel.update(...)
        │
        ├── previous snapshot
        └── current snapshot
        │
        ▼
AgentLoop / verifier (observe_world still used for verify evidence)
```

**Authoritative V4 observe API:** `neuron.v4.perception.PerceptionEngine`

**Reuse (not duplicated):**
- `neuron.windows.monitors` / `state` — monitors, foreground, top windows
- `neuron.uia.inspect` — accessibility tree walk
- `neuron.perception.capture_ops` / `ocr` — capture + RapidOCR (optional)
- `browser.current_url` — deterministic URL when available
- `verifier.observe_world` / `ComputerState.capture` — still feed AgentLoop verify; V4 normalizes into world model

---

## 2. Observation flow

| Mode | Method | Cost |
|------|--------|------|
| Full observe | `observe(deep=…, use_ocr=…)` | Win32 + optional UIA/browser/OCR/capture |
| Window | `observe_window` | observe + focus filter |
| Monitor | `observe_monitor` | observe + window filter |
| Region | `observe_region` | capture fingerprint for region |
| Action-targeted | `observe_for_action(step)` | picks deep/browser/monitor hints |
| Loop normalize | `normalize_into_world(observe_dict)` | no second full scan |

AgentLoop (OPAVR) uses **normalize_into_world** after `observe_world` so verify evidence and world model stay aligned without double capture.

---

## 3. Source priority

1. **WIN32** — monitors, window bounds, foreground, cursor  
2. **UI_AUTOMATION** — semantic elements (role/name/automation id/bounds)  
3. **BROWSER** — URL when Playwright/browser module exposes it  
4. **OCR** — optional local RapidOCR only when requested  
5. **SCREEN** — transient capture fingerprint (not permanent storage)  
6. Coordinates — never primary; not invented here  

One source failing returns **partial** observation (`failures[]` + remaining data). Never fabricate SUCCESS.

---

## 4. DesktopWorldModel integration

- `push_world=True` (default) → `wm.update(desktop)`
- `screen_diff` compares previous vs current (`diff_desktop_states`)
- `wm.update_from_perception(result)` helper available
- `AgentLoop.last_perception()` → latest `PerceptionResult`
- Meta keys: `perception_confidence`, `perception_sources`, `perception_timing_ms`, `world_diff`

---

## 5. Monitor / window perception

- Monitors from live geometry (negative coords + vertical layouts supported).
- Windows from UIA top-level list + foreground; mapped to monitors via bounds.
- Foreground from OS/UIA — deterministic.
- Filtering: skips empty titles / NEURON HUD title; not aggressively destructive.

---

## 6. UI Automation

- `walk_elements(interesting_only=True)` with bounded depth/count.
- Normalized to `UIElementState` with role via `normalize_uia_role`.
- Sensitive names (password/pin/…) skipped.
- Failures → `UIA_TIMEOUT` / `ACCESS_DENIED` without wiping Win32 data.

---

## 7. Element identity

`stable_element_id(...)` hashes:

application, hwnd, automation_id, role, name, hierarchy path, quantized bounds

Returns `(id, identity_confidence)`. Not list indexes. V4.3 ElementResolver will consume these IDs.

---

## 8. Capture

- Supports desktop / monitor / window / region intents.
- Returns `CaptureMeta` (bounds, size, fingerprint, kind).
- **Does not** require permanent screenshot files (`path` left empty in V4 path).
- Expensive capture/OCR **off** by default in AgentLoop normalize path.

---

## 9. Screen diff

`diff_desktop_states(before, after)`:

- foreground / app / monitor / window set / geometry / elements / URL  
- optional capture fingerprint pair  
- `change_score` 0..1; meaningful if ≥ 0.08  
- Not raw `image_a != image_b`

---

## 10. OCR

- Optional; uses existing RapidOCR.
- If unavailable → `OCR_UNAVAILABLE`; NEURON continues.
- Sensitive lines scrubbed.
- Not run on every loop.

---

## 11. Browser / fullscreen limitations

| Field | Status |
|-------|--------|
| URL | KNOWN when `browser.current_url()` works |
| Title | from window (INFERRED alone) |
| `media_state` | **unknown** (not faked) |
| MEDIA_FULLSCREEN | **unknown** |
| WINDOW_FULLSCREEN / MAXIMIZED / NORMAL | geometry classification when bounds known |

Title-alone never gets high browser confidence.

---

## 12. Performance

`PerceptionResult.timing_ms` tracks:

`monitors_ms`, `windows_ms`, `cursor_ms`, `uia_ms`, `browser_ms`, `capture_ms`, `ocr_ms`, `normalize_ms`, `total_ms`

Normalize path is milliseconds-scale (dict adapt + ID assign).

---

## 13. Privacy

- No permanent screenshot storage in V4 observe path.
- Password-like element names / OCR lines skipped.
- Logs: source, latency, counts, confidence — not full OCR dumps.

---

## 14. Files created

| Path | Role |
|------|------|
| `neuron/v4/perception/__init__.py` | Exports |
| `neuron/v4/perception/types.py` | PerceptionResult, errors, CaptureMeta, ScreenDiff, FullscreenKind |
| `neuron/v4/perception/element_ids.py` | Stable IDs + role normalize |
| `neuron/v4/perception/screen_diff.py` | Structured diff |
| `neuron/v4/perception/engine.py` | PerceptionEngine |
| `tests/run_v4_perception_smoke.py` | Optional read-only smoke |
| `docs/V4_2_PERCEPTION_ENGINE.md` | This doc |

## 15. Files modified

| Path | Change |
|------|--------|
| `neuron/v4/__init__.py` | Export perception |
| `neuron/v4/world/model.py` | `update_from_perception` |
| `neuron/brain/loop.py` | normalize_into_world on pre/post observe |
| `neuron/brain/agent_loop.py` | `last_perception()` |
| `tests/run_v4_unit_tests.py` | V4.2 cases |
| `docs/V4_ARCHITECTURE_AUDIT.md` | V4.2 status |

---

## 16. Dependencies

**None added.** Reuses RapidOCR / uiautomation / Pillow already in the project.

---

## 17. Tests

```
python tests/run_v4_unit_tests.py
python tests/run_v4_perception_smoke.py   # optional read-only
python tests/run_v3_baseline.py
```

---

## 18. Known limitations / UNKNOWN

- Media fullscreen / play-pause not detected.
- DPI often absent from monitor enum.
- UIA tree incomplete for some apps (games overlays, elevated).
- Browser URL depends on existing browser worker.
- OCR off in AgentLoop by default.
- Confirm-resume still skips full OPAVR (older debt).

---

## 19. Recommended start for V4.3

**Semantic ElementResolver:** resolve “first video”, “search box”, “that button” using V4.2 stable element IDs + DesktopWorldModel.visible_elements + ReferenceResolver — without rebuilding identity from scratch.
