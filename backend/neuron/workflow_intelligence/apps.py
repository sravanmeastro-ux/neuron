"""Observed application targets for workflow intelligence."""

from __future__ import annotations

from typing import Any

# Canonical observed surfaces → open_app / browser step payloads
TARGETS: dict[str, dict[str, Any]] = {
    "cursor": {
        "label": "Cursor",
        "kind": "app",
        "args": {"name": "cursor"},
        "aliases": ("cursor", "cursor ide"),
    },
    "vscode": {
        "label": "VS Code",
        "kind": "app",
        "args": {"name": "code"},
        "aliases": ("vs code", "vscode", "visual studio code", "code"),
    },
    "blender": {
        "label": "Blender",
        "kind": "app",
        "args": {"name": "blender"},
        "aliases": ("blender",),
    },
    "unreal": {
        "label": "Unreal Engine",
        "kind": "app",
        "args": {"name": "UnrealEditor"},
        "aliases": ("unreal", "unreal engine", "ue5", "ue4", "unrealeditor"),
    },
    "browser": {
        "label": "Browser",
        "kind": "app",
        "args": {"name": "chrome"},
        "aliases": ("browser", "chrome", "edge", "firefox"),
    },
    "github": {
        "label": "GitHub",
        "kind": "browser",
        "args": {"url": "https://github.com"},
        "aliases": ("github", "gh", "github.com"),
    },
}


def normalize_target(text: str) -> str | None:
    low = (text or "").strip().lower()
    if not low:
        return None
    if low in TARGETS:
        return low
    for key, meta in TARGETS.items():
        for a in meta.get("aliases") or ():
            if a == low or a in low or low in a:
                return key
    return None


def step_for(target: str, *, wait_s: float = 1.2) -> list[dict[str, Any]]:
    key = normalize_target(target) or target
    meta = TARGETS.get(key)
    if not meta:
        return [{"kind": "app", "args": {"name": target}, "note": f"open {target}"}]
    steps = [{"kind": meta["kind"], "args": dict(meta["args"]), "note": f"open {meta['label']}"}]
    if wait_s > 0:
        steps.append({"kind": "wait", "args": {"ms": int(wait_s * 1000)}, "note": "settle"})
    return steps


def all_targets() -> list[str]:
    return list(TARGETS.keys())
