"""Learn reusable workflows from observation sequences + seed presets."""

from __future__ import annotations

from typing import Any

from neuron.workflows import editor, store
from neuron.workflows.types import Workflow, WorkflowStep
from neuron.workflow_intelligence.apps import step_for
from neuron.workflow_intelligence.observe import recent_app_sequence


# Named presets: utterance-facing recipes over observed surfaces
PRESETS: dict[str, dict[str, Any]] = {
    "start_game_development": {
        "name": "Start Game Development",
        "description": "Launch Unreal + Cursor + GitHub for game development.",
        "apps": ["unreal", "cursor", "github"],
        "triggers": (
            "start game development",
            "game development",
            "start game dev",
            "prepare for unreal",
            "start unreal workflow",
        ),
        "tags": ["workflow_intelligence", "preset", "game", "unreal"],
    },
    "start_coding": {
        "name": "Start Coding",
        "description": "Launch Cursor + VS Code + Browser + GitHub for coding.",
        "apps": ["cursor", "vscode", "browser", "github"],
        "triggers": (
            "start coding",
            "start coding session",
            "prepare for coding",
            "coding workflow",
            "start development",
        ),
        "tags": ["workflow_intelligence", "preset", "coding"],
    },
    "prepare_for_blender": {
        "name": "Prepare for Blender",
        "description": "Launch Blender + reference Browser for 3D work.",
        "apps": ["blender", "browser"],
        "triggers": (
            "prepare for blender",
            "start blender",
            "blender workflow",
            "ready for blender",
        ),
        "tags": ["workflow_intelligence", "preset", "blender"],
    },
}


def _find_by_name(name: str) -> Workflow | None:
    for w in store.list_workflows():
        if (w.name or "").lower() == name.lower():
            return w
        if "workflow_intelligence" in (w.tags or []) and (w.name or "").lower() == name.lower():
            return w
    return None


def build_steps(apps: list[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for app in apps:
        steps.extend(step_for(app))
    return steps


def upsert_workflow(
    name: str,
    *,
    apps: list[str],
    description: str = "",
    tags: list[str] | None = None,
) -> Workflow:
    existing = _find_by_name(name)
    steps = build_steps(apps)
    tag_list = list(tags or [])
    if "workflow_intelligence" not in tag_list:
        tag_list.append("workflow_intelligence")
    if existing:
        existing.description = description or existing.description
        existing.tags = sorted(set((existing.tags or []) + tag_list))
        existing.steps = [WorkflowStep.from_dict(s) for s in steps]
        existing.channels = ["applications", "browser", "timing"]
        existing.version = int(existing.version or 1) + 1
        return store.save(existing)
    wf = Workflow(
        id=store.new_id(name),
        name=name,
        description=description or f"Auto workflow: {', '.join(apps)}",
        steps=[WorkflowStep.from_dict(s) for s in steps],
        tags=tag_list,
        channels=["applications", "browser", "timing"],
        variables={"apps": apps},
    )
    return store.save(wf)


def ensure_presets() -> dict[str, Any]:
    created: list[str] = []
    updated: list[str] = []
    for key, preset in PRESETS.items():
        before = _find_by_name(preset["name"])
        wf = upsert_workflow(
            preset["name"],
            apps=list(preset["apps"]),
            description=str(preset.get("description") or ""),
            tags=list(preset.get("tags") or []),
        )
        (updated if before else created).append(wf.id)
    return {"ok": True, "created": created, "updated": updated, "presets": list(PRESETS.keys())}


def match_preset(text: str) -> str | None:
    low = (text or "").strip().lower().rstrip(".!?")
    for key, preset in PRESETS.items():
        for trig in preset.get("triggers") or ():
            if trig in low or low == trig:
                return key
    return None


def learn_from_observations(*, min_apps: int = 2, window: str | None = None) -> dict[str, Any]:
    seq = recent_app_sequence(window_s=3600.0, limit=20)
    # Keep only known intelligence surfaces, preserve order
    known = []
    for a in seq:
        if a in ("cursor", "vscode", "blender", "unreal", "browser", "github"):
            if not known or known[-1] != a:
                known.append(a)
    if len(known) < min_apps:
        return {
            "ok": False,
            "error": f"Need at least {min_apps} observed apps in the last hour (got {known}).",
            "sequence": known,
        }
    # Prefer matching a preset signature
    for key, preset in PRESETS.items():
        apps = list(preset["apps"])
        if known[: len(apps)] == apps or set(apps).issubset(set(known)):
            wf = upsert_workflow(
                preset["name"],
                apps=apps,
                description=str(preset.get("description") or ""),
                tags=list(preset.get("tags") or []) + ["learned"],
            )
            return {"ok": True, "workflow": wf.summary(), "source": "preset_match", "sequence": known}

    label = name or ("Learned: " + " → ".join(known[:5]))
    wf = upsert_workflow(
        label,
        apps=known[:6],
        description=f"Auto-learned from observation: {' → '.join(known[:6])}",
        tags=["workflow_intelligence", "learned", "auto"],
    )
    return {"ok": True, "workflow": wf.summary(), "source": "observation", "sequence": known}


def list_intelligence_workflows() -> list[dict[str, Any]]:
    rows = []
    for w in store.list_workflows():
        tags = w.tags or []
        if "workflow_intelligence" in tags or "learned" in tags or "preset" in tags:
            rows.append(w.summary())
    # Also include by preset name
    names = {p["name"].lower() for p in PRESETS.values()}
    for w in store.list_workflows():
        if (w.name or "").lower() in names:
            s = w.summary()
            if s not in rows and not any(r["id"] == s["id"] for r in rows):
                rows.append(s)
    return rows


def suggest_for_text(text: str) -> dict[str, Any]:
    key = match_preset(text)
    if key:
        return {"ok": True, "preset": key, "name": PRESETS[key]["name"], "apps": PRESETS[key]["apps"]}
    seq = recent_app_sequence(window_s=1800.0, limit=10)
    if len(seq) >= 2:
        return {"ok": True, "preset": None, "name": "Learned session", "apps": seq[:5], "from": "observations"}
    return {"ok": False, "error": "No matching preset or recent observations."}
