"""Structured screen / desktop-state diff for V4.2.

Builds on DesktopWorldModel previous/current — not raw pixel equality alone.
"""

from __future__ import annotations

import hashlib
from typing import Any

from neuron.v4.perception.types import ScreenDiffResult
from neuron.v4.world.models import DesktopState


def diff_desktop_states(
    before: DesktopState | None,
    after: DesktopState | None,
    *,
    region_fingerprints: tuple[str, str] | None = None,
) -> ScreenDiffResult:
    """Compare two DesktopState snapshots (+ optional capture fingerprints)."""
    if before is None:
        return ScreenDiffResult(
            changed=True,
            change_score=1.0,
            reason="no_previous_state",
            confidence=0.5,
            after_fp=after.ensure_fingerprint() if after else "",
            window_changes=["first_observation"],
        )
    if after is None:
        return ScreenDiffResult(
            changed=False,
            change_score=0.0,
            reason="no_after_state",
            confidence=0.3,
            before_fp=before.ensure_fingerprint(),
        )

    window_changes: list[str] = []
    element_changes: list[str] = []
    score = 0.0
    fg_changed = False
    mon_changed = False

    bw = before.foreground_window
    aw = after.foreground_window
    if (bw.title if bw else "") != (aw.title if aw else ""):
        window_changes.append(
            f"focus_title: {(bw.title if bw else '')[:40]!r} -> {(aw.title if aw else '')[:40]!r}"
        )
        fg_changed = True
        score += 0.35
    if int(bw.hwnd if bw else 0) != int(aw.hwnd if aw else 0):
        window_changes.append(f"hwnd: {bw.hwnd if bw else 0} -> {aw.hwnd if aw else 0}")
        fg_changed = True
        score += 0.25

    ba = before.foreground_application.name if before.foreground_application else ""
    aa = after.foreground_application.name if after.foreground_application else ""
    if ba.lower() != aa.lower():
        window_changes.append(f"app: {ba} -> {aa}")
        fg_changed = True
        score += 0.3

    if before.active_monitor_id != after.active_monitor_id:
        window_changes.append(
            f"monitor: {before.active_monitor_id} -> {after.active_monitor_id}"
        )
        mon_changed = True
        score += 0.15

    # Window set changes (by hwnd/title)
    before_wins = {
        (w.hwnd or 0, (w.title or "")[:60]) for w in before.windows
    }
    after_wins = {
        (w.hwnd or 0, (w.title or "")[:60]) for w in after.windows
    }
    added_w = after_wins - before_wins
    removed_w = before_wins - after_wins
    if added_w:
        window_changes.append(
            "windows_added: " + ", ".join(t for _, t in list(added_w)[:5] if t)
        )
        score += min(0.2, 0.05 * len(added_w))
    if removed_w:
        window_changes.append(
            "windows_removed: " + ", ".join(t for _, t in list(removed_w)[:5] if t)
        )
        score += min(0.2, 0.05 * len(removed_w))

    # Geometry change for same hwnd
    b_by_hwnd = {w.hwnd: w for w in before.windows if w.hwnd}
    for w in after.windows:
        if not w.hwnd or w.hwnd not in b_by_hwnd:
            continue
        prev = b_by_hwnd[w.hwnd]
        if (
            prev.left != w.left
            or prev.top != w.top
            or prev.width != w.width
            or prev.height != w.height
            or prev.monitor_id != w.monitor_id
        ):
            window_changes.append(f"geometry:{w.hwnd}")
            score += 0.12
            break

    prev_ids = {(e.id or e.name or "").strip().lower() for e in before.visible_elements}
    cur_ids = {(e.id or e.name or "").strip().lower() for e in after.visible_elements}
    if prev_ids or cur_ids:
        added = sorted(cur_ids - prev_ids)[:8]
        removed = sorted(prev_ids - cur_ids)[:8]
        if added:
            element_changes.append("elements_added: " + ", ".join(added)[:120])
            score += min(0.25, 0.03 * len(added))
        if removed:
            element_changes.append("elements_removed: " + ", ".join(removed)[:120])
            score += min(0.25, 0.03 * len(removed))

    bu = before.browser.url if before.browser else ""
    au = after.browser.url if after.browser else ""
    if bu != au:
        window_changes.append(f"url: {bu[:40]} -> {au[:40]}")
        score += 0.2

    region_changed = False
    changed_regions: list[dict[str, Any]] = []
    if region_fingerprints:
        a_fp, b_fp = region_fingerprints
        if a_fp and b_fp and a_fp != b_fp:
            region_changed = True
            changed_regions.append({"kind": "capture_fingerprint", "before": a_fp, "after": b_fp})
            score += 0.2

    bfp = before.ensure_fingerprint()
    afp = after.ensure_fingerprint()
    if bfp != afp and score < 0.05:
        window_changes.append("fingerprint_changed")
        score += 0.1

    score = min(1.0, score)
    # Threshold: tiny noise < 0.08 counts as unchanged for "meaningful" signal
    meaningful = score >= 0.08 or region_changed
    conf = 0.85 if (window_changes or element_changes) else (0.6 if region_changed else 0.7)
    reason = (window_changes or element_changes or ["unchanged"])[0]
    return ScreenDiffResult(
        changed=meaningful,
        change_score=round(score, 3),
        changed_regions=changed_regions,
        window_changes=window_changes[:12],
        element_changes=element_changes[:12],
        foreground_changed=fg_changed,
        monitor_changed=mon_changed,
        confidence=conf,
        before_fp=bfp,
        after_fp=afp,
        reason=reason if meaningful else "unchanged",
    )


def cheap_image_fingerprint(image: Any) -> str:
    """Downscale + average-hash style fingerprint. Empty on failure."""
    try:
        img = image
        if hasattr(img, "convert"):
            img = img.convert("L")
        if hasattr(img, "resize"):
            img = img.resize((16, 16))
        pixels = list(img.getdata()) if hasattr(img, "getdata") else []
        if not pixels:
            return ""
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= avg else "0" for p in pixels)
        return hashlib.sha1(bits.encode("ascii")).hexdigest()[:16]
    except Exception:
        return ""
