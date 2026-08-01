# NEURON V4.3 — Semantic Element Resolution

**Date:** 2026-07-31  
**Phase:** V4.3  
**Depends on:** V4.1 DesktopWorldModel, V4.2 PerceptionEngine (stable element IDs)  
**Does not:** rewrite AgentLoop, ToolRegistry, or Hierarchical Planner (V4.4)

---

## 1. Architecture

```
natural reference ("second video", "search box", "that button")
        │
        ▼
parse_reference()          # deterministic — no LLM for ordinal/role/spatial
        │
        ▼
ElementReference
        │
        ▼
SemanticElementResolver.resolve(ref, world, context)
        │
        ├── candidates ← DesktopWorldModel.visible_elements (no rescan)
        ├── role / text / app / monitor filters
        ├── relational geometry (optional)
        ├── score
        ├── ordinal (after filter)  — reading order: top→bottom, left→right
        ├── spatial (after filter)
        └── confidence / ambiguity gate
        │
        ▼
ResolutionResult { RESOLVED | AMBIGUOUS | NOT_FOUND | STALE_WORLD | INSUFFICIENT_CONTEXT }
```

**Authoritative API:** `neuron.v4.resolve.SemanticElementResolver`  
**Convenience:** `resolve(...)`, `AgentLoop.semantic_resolve(...)`

### Existing systems (not replaced)

| Module | Role vs V4.3 |
|--------|----------------|
| `v3.ReferenceResolver` | Conversation deixis / rewrite for agent routing — still used |
| `v3.ElementResolver` | Observation-based + V2 cascade fallback — still used |
| `brain.element_resolver` | Physical DOM/UIA/OCR/coords cascade — still used |
| **V4 SemanticElementResolver** | World-model semantic targeting for V4 planner path |

---

## 2. Types

- `ElementReference` — parsed intent (role, name, ordinal, position, relation, deixis, …)
- `ResolutionContext` — task/app/window/monitor/last element/result set
- `ElementCandidate` — scored UIElementState + reasons
- `ResolvedElement` — stable id, role, bounds, confidence
- `ResolutionResult` — status + band + latency (privacy-safe `to_dict`)
- `RevalidateStatus` — STILL_VALID / MOVED / CHANGED / MISSING / UNCERTAIN

---

## 3. Confidence strategy

Score blends (capped 0..1):

| Signal | Typical weight |
|--------|----------------|
| Source element confidence | ×0.15 |
| Role compatibility | +0.25 |
| Role–name alignment (e.g. Search) | ±0.15–0.4 |
| Text / automation id match | ×0.45 (+ exact bonus) |
| App / window context | +0.05 each |
| Last element / result set | +0.08–0.1 |
| Relation proximity | +0.25 × (1 − dist/280) |
| Spatial hint | +0.08 (+ extreme boost) |

**Bands:** HIGH ≥ 0.75 · MEDIUM ≥ 0.45 · LOW < 0.45  

LOW → do **not** auto-act (AMBIGUOUS / NOT_FOUND).  
Top-2 within Δ0.06 → **AMBIGUOUS** (unless unique nearest relational neighbor).

---

## 4. Ordering rules (ordinals)

1. Semantic / role / text filters first  
2. Sort remaining by reading order: **top→bottom, then left→right** (bounds centers; path as tiebreak)  
3. Apply `first` / `second` / `last`  

So “second video” ≠ second element globally.

---

## 5. Ambiguity

Two equally plausible “Settings” buttons → `AMBIGUOUS` + candidate list.  
Bare “that button” with many buttons and no context → `AMBIGUOUS` / `INSUFFICIENT_CONTEXT`.  
Empty `visible_elements` → `INSUFFICIENT_CONTEXT` / `STALE_WORLD` + `needs_reobserve` (no silent full scan).

---

## 6. AgentLoop integration

```python
loop.semantic_resolve("search box")
loop.revalidate_element(element_id, prior=resolved)
```

Uses `context_from_engine()` + current `DesktopWorldModel`.  
Does **not** execute clicks. Planner migration is V4.4+.

---

## 7. Files created / modified

**Created:** `neuron/v4/resolve/{__init__,types,roles,parse,resolver}.py`,  
`tests/run_v4_semantic_smoke.py`, `docs/V4_3_SEMANTIC_ELEMENT_RESOLUTION.md`

**Modified:** `neuron/v4/__init__.py`, `neuron/brain/agent_loop.py`,  
`tests/run_v4_unit_tests.py`, `docs/V4_ARCHITECTURE_AUDIT.md`

---

## 8. Known limitations

- YouTube “video” tiles often lack rich UIA roles → may return `INSUFFICIENT_CONTEXT` until domain skills enrich elements (V4.4/V4.8).
- Color matching is name/meta only (no vision color).
- Relational heuristics are 2D distance/direction — not layout-AI.
- Does not call OCR/capture from the resolver.
- V3 paths unchanged; not every UI action uses V4 resolve yet.

---

## 9. Recommended V4.4 start

**Hierarchical Planner:** consume `ResolutionResult` when planning `ui.click` / play_result steps; rolling OBSERVE → resolve → ACT → VERIFY, generalizing `multi_app` beyond regex.
