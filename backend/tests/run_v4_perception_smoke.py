"""OPTIONAL read-only V4.2 perception smoke test.

Safe: enumerates monitors/windows/foreground/UIA metadata only.
Does NOT click, type, move windows, launch, or close anything.

Usage (from backend/):
  python tests/run_v4_perception_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from neuron.v4.perception import get_perception_engine, reset_perception_engine
    from neuron.v4.world import reset_world_model

    reset_world_model()
    reset_perception_engine()
    pe = get_perception_engine()
    print("V4.2 perception smoke (read-only)…")
    res = pe.observe(
        deep=True,
        use_uia=True,
        use_browser=True,
        use_ocr=False,
        use_capture=False,
        push_world=True,
    )
    d = res.desktop
    print(f"  confidence={res.confidence:.2f} partial={res.partial} ok={res.ok}")
    print(f"  sources={res.sources_used}")
    print(f"  timing_ms={res.timing_ms}")
    print(f"  monitors={len(d.monitors)} windows={len(d.windows)} elements={len(d.visible_elements)}")
    if d.foreground_window:
        title = (d.foreground_window.title or "")[:60].encode("ascii", "replace").decode("ascii")
        app = ""
        if d.foreground_application:
            app = (d.foreground_application.name or "").encode("ascii", "replace").decode("ascii")
        print(f"  foreground={title!r} app={app or '?'} monitor={d.active_monitor_id}")
    if res.failures:
        print("  failures:")
        for f in res.failures:
            print(f"    - {f.code.value}: {f.detail[:100]}")
    if d.browser:
        print(
            f"  browser knowledge={d.browser.knowledge.value} "
            f"url={'yes' if d.browser.url else 'unknown'} "
            f"media={d.browser.media_state or 'unknown'}"
        )
    print("Smoke complete (no desktop mutations).")
    return 0 if (d.monitors or d.windows or d.foreground_window) else 1


if __name__ == "__main__":
    raise SystemExit(main())
