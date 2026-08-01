"""OPTIONAL read-only V4.3 semantic resolution smoke.

Observes desktop (no mutations), then attempts resolve() for common phrases.
Does NOT click, type, launch, move, or close anything.

Usage (from backend/):
  python tests/run_v4_semantic_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _safe(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


def main() -> int:
    from neuron.v4.perception import get_perception_engine, reset_perception_engine
    from neuron.v4.resolve import get_semantic_resolver, reset_semantic_resolver, context_from_engine
    from neuron.v4.world import reset_world_model, get_world_model

    reset_world_model()
    reset_perception_engine()
    reset_semantic_resolver()

    pe = get_perception_engine()
    print("V4.3 semantic smoke (read-only)...")
    obs = pe.observe(deep=True, use_uia=True, use_browser=True, use_ocr=False, push_world=True)
    wm = get_world_model()
    print(
        f"  world elements={len(wm.current.visible_elements)} "
        f"app={_safe(wm.get_active_application())} "
        f"conf={obs.confidence:.2f}"
    )

    resolver = get_semantic_resolver()
    ctx = context_from_engine(world=wm)
    phrases = [
        "search box",
        "close button",
        "the first button",
        "Settings",
    ]
    for phrase in phrases:
        r = resolver.resolve(phrase, world=wm, context=ctx, allow_stale=True)
        rid = r.resolved.element_id if r.resolved else ""
        role = r.resolved.role if r.resolved else ""
        name = _safe(r.resolved.name if r.resolved else "")
        print(
            f"  [{r.status.value}] {phrase!r} -> "
            f"id={_safe(rid)[:24]} role={role} name={name!r} "
            f"conf={r.confidence:.2f} ms={r.latency_ms:.1f} "
            f"cands={len(r.candidates)}"
        )

    print("Smoke complete (no desktop mutations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
