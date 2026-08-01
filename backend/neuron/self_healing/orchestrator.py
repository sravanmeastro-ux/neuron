"""Self-healing orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.self_healing import recovery, watchdog
from neuron.self_healing.detect import classify_sh_intent
from neuron.self_healing.detectors import health_snapshot
from neuron.self_healing.types import SHCapability, SHResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> SHResult:
    args = args or {}
    recovery.ensure_builtin_modules()

    if capability == SHCapability.STATUS.value or capability == SHCapability.WATCHDOG_STATUS.value:
        st = watchdog.status()
        mods = recovery.list_modules()
        say = (
            f"Self-healing online. "
            f"Watchdog={'running' if st.get('running') else 'stopped'} "
            f"(ticks={st.get('ticks', 0)}, recoveries={st.get('recoveries', 0)}). "
            f"Modules={len(mods)}."
        )
        return SHResult(ok=True, say=say, capability=capability, data={"watchdog": st, "modules": mods})

    if capability == SHCapability.HEALTH.value or capability == SHCapability.SCAN.value:
        auto = bool(args.get("recover") or args.get("auto"))
        result = watchdog.run_once(auto_recover=auto)
        health = result.get("health") or {}
        faults = health.get("faults") or []
        if not faults:
            say = f"System healthy. CPU={health.get('sample', {}).get('cpu_percent')}% RAM={health.get('sample', {}).get('rss_mb')}MB."
        else:
            kinds = ", ".join(health.get("fault_kinds") or [])
            say = f"Detected: {kinds}."
            if result.get("recovery"):
                acts = ", ".join((result["recovery"] or {}).get("actions") or [])
                say += f" Auto-recovered via: {acts}."
        return SHResult(
            ok=True,
            say=say,
            acted=bool(result.get("recovery")),
            capability=capability,
            data=result,
            faults=faults,
            actions=((result.get("recovery") or {}).get("actions") or []),
        )

    if capability == SHCapability.RECOVER.value:
        snap = health_snapshot()
        rec = recovery.recover_from_faults(snap.get("faults") or [], auto=True)
        # Always run a recovery pass even if currently healthy
        if not snap.get("faults"):
            rec = recovery.recover_from_faults([], auto=True)
            # also restart failed
            fr = recovery.restart_failed_modules()
            rec.setdefault("details", []).append(fr)
            rec.setdefault("actions", []).append("restart_failed_modules")
        say = "Recovery applied: " + (", ".join(rec.get("actions") or []) or "none")
        return SHResult(ok=True, say=say, acted=True, capability=capability, data={"health": snap, "recovery": rec}, actions=rec.get("actions") or [], faults=snap.get("faults") or [])

    if capability == SHCapability.RESTART_MODULE.value:
        if args.get("all_failed"):
            data = recovery.restart_failed_modules()
            say = f"Restarted {data.get('count', 0)} module(s)."
            return SHResult(ok=bool(data.get("ok")), say=say, acted=True, capability=capability, data=data, actions=["restart_failed_modules"])
        name = str(args.get("name") or "").strip()
        if not name:
            return SHResult(ok=False, error="Need module name.", say="Need module name to restart.", capability=capability)
        data = recovery.restart_module(name)
        return SHResult(
            ok=bool(data.get("ok")),
            say=f"Module {name}: {'restarted' if data.get('ok') else data.get('error')}",
            acted=bool(data.get("ok")),
            capability=capability,
            data=data,
            error=str(data.get("error") or ""),
            actions=[f"restart:{name}"],
        )

    if capability == SHCapability.WATCHDOG_START.value:
        data = watchdog.start_watchdog(
            interval_s=float(args.get("interval_s") or 2.0),
            auto_recover=bool(args.get("auto_recover", True)),
        )
        return SHResult(ok=True, say=data.get("say") or "Watchdog started.", acted=True, capability=capability, data=data)

    if capability == SHCapability.WATCHDOG_STOP.value:
        data = watchdog.stop_watchdog()
        return SHResult(ok=True, say=data.get("say") or "Watchdog stopped.", acted=True, capability=capability, data=data)

    return SHResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False) -> tuple[str, bool, dict]:
    intent = classify_sh_intent(text)
    cap = intent.get("capability") or SHCapability.HEALTH.value
    args = dict(intent.get("args") or {})
    result = dispatch(cap, args)
    meta = {
        "path": "self_healing",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Self-healing failed.", True, meta
