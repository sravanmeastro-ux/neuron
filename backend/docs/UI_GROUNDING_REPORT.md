# UI Grounding Engine — Report

Date: 2026-08-02  
Constraints honored: Screen Understanding (`neuron/screen`), Computer Use, Element Resolver, and `screen_capture` were **not rewritten**. UI Grounding is a compose-only enforcement layer: observe → detect → ground → click → verify, and it **gates** the global `click` tool plus `computer_use.primitives.click_xy`.

## 1. Problem

The planner previously assumed controls existed and could focus/click imaginary windows.

**Rule:** Never execute mouse clicks without visual grounding. Never assume a window or button exists.

## 2. Pipeline

```
Intent
  ↓
Focus Application (optional)
  ↓
Screenshot (multi-monitor + DPI-aware)
  ↓
Detect UI Elements (UIA + OCR + icon heuristics)
  ↓
Ground requested target (text / bbox / icon + confidence)
  ↓
Click (only if confidence ≥ threshold)
  ↓
Observe result
  ↓
Verify success
  ↓
Continue (retry / scroll if needed)
```

## 3. Features

| Feature | Implementation |
|---------|----------------|
| UI element grounding | `match.ground_target` over `screen.detect` snapshot |
| Bounding box matching | IoU + geometric plausibility scores |
| Text matching | Exact / substring / token overlap |
| Icon matching | `role=icon` + small-square UIA heuristics |
| Confidence scoring | Weighted blend → min threshold (default 0.35) |
| Retry + new screenshot | Up to `max_retries` with fresh capture |
| Scroll if not visible | Scroll-down between retries |
| Multi-monitor | `screen_capture.list_monitors` / capture_monitor |
| DPI scaling | `SetProcessDpiAwareness` + LOGPIXELSX scale |

## 4. Click gate

- `tool_registry` **`click`** → `ui_grounding.gate.grounded_click`
- `computer_use.primitives.click_xy` → refuses unless `force=True` or raw-click context token (set only inside the grounding pipeline after a match)

Bare `x,y` clicks must still match a **nearby detected element** or they are refused.

## 5. Package

`backend/neuron/ui_grounding/`

| Module | Role |
|--------|------|
| `capture.py` | Screenshot, monitors, DPI |
| `detect_ui.py` | Element detection wrapper + icons |
| `match.py` | Text/bbox/icon/confidence |
| `pipeline.py` | Full grounded interaction |
| `verify.py` | Post-click observation |
| `gate.py` | Tool-facing click enforcement |
| `bridge.py` | Voice compose hook |

## 6. Tools / config

| Tool | Purpose |
|------|---------|
| `ui_ground_status` | Monitors + DPI + policy |
| `ui_ground_run` | Ground / click / observe |
| `click` | **Gated** grounded click |

```json
"agent": { "ui_grounding": true },
"ui_grounding": {
  "min_confidence": 0.35,
  "max_retries": 3,
  "allow_scroll": true
}
```

## 7. Examples

- “Ground and click Save”
- “Click the login button”
- “UI grounding status”

## 8. Bench

```bash
cd backend
python tests/run_ui_grounding_bench.py
```

## 9. Non-goals

- Does not replace Screen Understanding planner for descriptive Q&A  
- Does not remove UIA Invoke paths inside Element Resolver for non-mouse actuation — **mouse** clicks are gated  
- VLM icon embedding similarity is heuristic (role/size/name), not a separate CNN classifier yet
