"""V4.5 verification smoke — READ-ONLY by default.

Observes world and verifies existing facts. No click/type/move/open.

Usage:
  python tests/run_v4_verification_smoke.py
  python tests/run_v4_verification_smoke.py --live   # still read-only facts; reserved flag
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    live = "--live" in argv
    if live:
        print("Note: --live reserved; this smoke remains read-only (no mutations).")

    from neuron.v4.perception import get_perception_engine, reset_perception_engine
    from neuron.v4.verify import (
        ExpectationKind,
        VerificationExpectation,
        get_verification_engine,
        reset_verification_engine,
    )
    from neuron.v4.world import get_world_model, reset_world_model

    reset_world_model()
    reset_perception_engine()
    reset_verification_engine()

    pe = get_perception_engine()
    print("V4.5 verification smoke (read-only)...")
    pe.observe(deep=True, use_uia=True, use_browser=True, use_ocr=False, push_world=True)
    wm = get_world_model()
    eng = get_verification_engine()

    app = wm.get_active_application() or ""
    fg = wm.get_foreground_window()
    print(f"  active_app={app!r} fg={(fg.title if fg else '')[:60]!r}")

    # Fact: if we have a foreground window, WINDOW_FOCUSED for that app
    if app:
        rep = eng.verify_fact(
            VerificationExpectation(kind=ExpectationKind.WINDOW_FOCUSED, application=app),
            world=wm,
        )
        print(f"  [focus {app}] {rep.status.value} conf={rep.confidence:.2f} — {rep.reason[:80]}")
    else:
        print("  [focus] skipped (no active app)")

    # Fact: windows on their monitors
    for w in list(wm.current.windows)[:3]:
        if w.monitor_id is None or not w.application:
            continue
        rep = eng.verify_fact(
            VerificationExpectation(
                kind=ExpectationKind.WINDOW_ON_MONITOR,
                application=w.application,
                monitor=int(w.monitor_id),
            ),
            world=wm,
        )
        print(
            f"  [mon {w.application} -> {w.monitor_id}] {rep.status.value} "
            f"conf={rep.confidence:.2f}"
        )

    # Fact: element exists if any
    els = list(wm.current.visible_elements)[:1]
    if els:
        rep = eng.verify_fact(
            VerificationExpectation(kind=ExpectationKind.ELEMENT_EXISTS, element_id=els[0].id),
            world=wm,
        )
        print(f"  [element] {rep.status.value} conf={rep.confidence:.2f}")
    else:
        print("  [element] skipped (none visible)")

    print("Smoke complete (no desktop mutations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
