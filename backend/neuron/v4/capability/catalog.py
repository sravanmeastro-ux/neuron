"""CapabilityCatalog — semantic/index layer over ToolRegistry (not an executor)."""

from __future__ import annotations

import logging
import re
from typing import Any

from neuron.v4.capability.expectations import preconditions_for, verification_for
from neuron.v4.capability.types import (
    CapabilityDescriptor,
    CapabilityDomain,
    CapabilityKind,
    CapabilityStats,
    FailureMemory,
)

log = logging.getLogger("neuron.v4.capability")

_CATALOG: "CapabilityCatalog | None" = None

# CapabilityRouter ID → preferred ToolRegistry tool (shared semantics)
_ROUTER_BINDINGS: dict[str, str] = {
    "youtube.skip_ad": "youtube.skip_ad",
    "youtube.home": "youtube.home",
    "youtube.search": "youtube.search",
    "youtube.play_first": "youtube.play_result",
    "youtube.play_second": "youtube.play_result",
    "youtube.fullscreen": "youtube.fullscreen",
    "youtube.pause": "youtube.ensure_playback",
    "youtube.play": "youtube.ensure_playback",
    "windows.open_app": "windows.open_app",
    "windows.focus_app": "windows.focus_app",
    "windows.close_app": "windows.close_app",
    "windows.move_to_monitor": "windows.move_to_monitor",
    "browser.open": "open_website",
    "browser.search": "browser.search",
    "browser.open_url": "browser_navigate",
    "files.open_downloads": "open_folder",
    "files.find": "files.find",
    "files.open": "files.open",
    "input.type": "type_text",
    "input.copy": "press_keys",
    "input.paste": "press_keys",
    "input.escape": "press_keys",
    "input.hotkey": "hotkey",
    "ui.scroll": "scroll",
    "ui.click": "click_element",
    "ui.find": "find_element",
    "ui.inspect": "analyze_screen",
    "system.volume": "volume",
    "system.wait": "wait",
    "system.speak": "speak",
    "system.verify": "verify",
    "procedure.run": "run_procedure",
}

# Legacy router tool names (may still be emitted by CapabilityRouter)
_ROUTER_LEGACY_TOOLS: dict[str, str] = {
    "skip_ad": "youtube.skip_ad",
    "youtube_home": "youtube.home",
    "search_site": "youtube.search",
    "play_result": "youtube.play_result",
    "fullscreen": "youtube.fullscreen",
    "ensure_playback": "youtube.ensure_playback",
    "open_app": "windows.open_app",
    "focus_app": "windows.focus_app",
    "close_app": "windows.close_app",
    "move_window_to_monitor": "windows.move_to_monitor",
    "open_website": "browser.open",
    "search_web": "browser.search",
    "browser_navigate": "browser.open_url",
}

_INTENT_MAP: dict[str, list[str]] = {
    "open_app": ["windows.open_app", "open_app"],
    "focus_app": ["windows.focus_app", "focus_app"],
    "move_monitor": ["windows.move_to_monitor", "move_window_to_monitor"],
    "close_app": ["windows.close_app", "close_app"],
    "maximize": ["windows.maximize", "maximize_app"],
    "minimize": ["windows.minimize", "minimize_app"],
    "youtube_search": ["youtube.search", "browser.search", "browser_search", "search_site"],
    "youtube_play": ["youtube.play_result", "play_result"],
    "youtube_fullscreen": ["youtube.fullscreen", "fullscreen"],
    "youtube_home": ["youtube.home", "youtube_home", "open_website"],
    "youtube_pause": ["youtube.ensure_playback", "ensure_playback", "media"],
    "open_website": ["open_website", "browser_navigate", "browser.open_tab"],
    "browser_search": ["browser.search", "browser_search", "search_site"],
    "browser_navigate": ["browser_navigate", "browser.navigate", "open_website"],
    "volume": ["volume"],
    "mute": ["volume"],
    "media": ["media", "youtube.ensure_playback"],
    "click": ["click_ui_element", "click_element", "browser_click", "click"],
    "type": ["type_text", "browser_type"],
    "press": ["press_keys", "hotkey"],
    "scroll": ["scroll", "browser_scroll"],
    "find_file": ["files.find", "search_files"],
    "open_file": ["files.open", "open_file"],
    "open_folder": ["files.open_folder", "open_folder"],
    "spotify_open": ["spotify.open", "open_app"],
    "discord_open": ["discord.open", "open_app"],
    "blender_open": ["blender.open", "open_app"],
    "observe": ["analyze_screen", "inspect_screen"],
    "run_procedure": ["run_procedure"],
}


def _domain_for_name(name: str) -> CapabilityDomain:
    n = (name or "").lower()
    if n.startswith("youtube.") or n in ("skip_ad", "fullscreen", "play_result", "ensure_playback", "youtube_home"):
        return CapabilityDomain.YOUTUBE
    if n.startswith("browser.") or n.startswith("browser_") or n in ("open_website", "search_site", "search_web"):
        return CapabilityDomain.BROWSER
    if n.startswith("windows.") or n in (
        "open_app", "focus_app", "close_app", "move_window_to_monitor", "maximize_app", "minimize_app",
        "move_window", "get_monitors", "get_windows",
    ):
        if "monitor" in n or "move" in n:
            return CapabilityDomain.MONITOR if "monitor" in n else CapabilityDomain.WINDOW
        return CapabilityDomain.APP if any(x in n for x in ("open", "focus", "close")) else CapabilityDomain.WINDOW
    if n.startswith("files.") or n in ("open_file", "open_folder", "search_files"):
        return CapabilityDomain.FILE
    if n.startswith("blender."):
        return CapabilityDomain.BLENDER
    if n.startswith("spotify.") or n.startswith("discord."):
        return CapabilityDomain.INTEGRATION
    if n in ("volume", "media", "wait", "speak", "verify"):
        return CapabilityDomain.SYSTEM if n != "media" else CapabilityDomain.MEDIA
    if n in ("type_text", "press_keys", "hotkey", "press_key"):
        return CapabilityDomain.KEYBOARD
    if n in ("click", "click_element", "click_ui_element", "scroll", "browser_click"):
        return CapabilityDomain.UI
    if n == "run_procedure" or n.startswith("procedure.") or "." not in n and "procedure" in n:
        return CapabilityDomain.PROCEDURE
    if re.match(r"^(blender|spotify|discord)\.", n):
        return CapabilityDomain.INTEGRATION
    return CapabilityDomain.UNKNOWN


class CapabilityCatalog:
    """Index over ToolRegistry + CapabilityRouter shared IDs."""

    def __init__(self) -> None:
        self._by_id: dict[str, CapabilityDescriptor] = {}
        self._by_tool: dict[str, str] = {}  # tool → capability_id
        self.stats: dict[str, CapabilityStats] = {}
        self.failures = FailureMemory()
        self._built = False
        self._building = False
        self.duplicate_impl_count = 0
        self.legacy_only: list[str] = []
        self.planner_only: list[str] = []
        self.shared: list[str] = []

    def rebuild(self) -> None:
        if self._building:
            return
        self._building = True
        try:
            self._by_id.clear()
            self._by_tool.clear()
            self.legacy_only.clear()
            self.planner_only.clear()
            self.shared.clear()
            self.duplicate_impl_count = 0
            self._built = False
            self._build()
            self._built = True
        finally:
            self._building = False

    def ensure(self) -> None:
        if self._built or self._building:
            return
        self.rebuild()

    def _build(self) -> None:
        from neuron.brain import tool_registry as tr

        tr.ensure_bootstrapped()
        registered = set(tr.names())

        # Prefer dotted skill names as canonical when both exist
        for name in sorted(registered):
            spec = tr.get(name)
            if not spec:
                continue
            if not getattr(spec, "planner_visible", True) and name not in (
                "wait", "speak", "verify",
            ):
                # Still index but planner_enabled=False for hidden
                pass
            cap_id = name
            # Prefer dotted as id when underscore alias of skill
            domain = _domain_for_name(name)
            kind = CapabilityKind.ATOMIC
            if name == "run_procedure" or name.startswith("blender.") and "render" in name:
                kind = CapabilityKind.COMPOSITE if "render" in name or name == "run_procedure" else CapabilityKind.ATOMIC
            if name == "run_procedure" or (
                hasattr(spec, "description") and "procedure" in str(getattr(spec, "description", "")).lower()
            ):
                if name != "run_procedure" and "." in name and not name.startswith(("youtube.", "windows.", "browser.", "files.", "spotify.", "discord.", "blender.")):
                    kind = CapabilityKind.PROCEDURE

            risk = getattr(spec, "risk", None) or "safe"
            try:
                from neuron.safety.policy import risk_of
                risk = risk_of(name) or risk
            except Exception:
                pass

            desc = CapabilityDescriptor(
                capability_id=cap_id,
                name=cap_id,
                domain=domain,
                description=str(getattr(spec, "description", "") or "")[:200],
                tool_name=tr.resolve_name(name) or name,
                aliases=[],
                kind=kind,
                risk_hint=str(risk).lower(),
                input_schema=dict(getattr(spec, "args_schema", None) or {}),
                verification_kind=verification_for(name),
                preconditions=preconditions_for(name),
                planner_enabled=bool(getattr(spec, "planner_visible", True)),
                fast_path_enabled=False,
                recovery_enabled=True,
                control_methods=list(getattr(spec, "control_methods", None) or []),
            )
            self._register(desc)

        # Overlay router shared semantics
        for router_id, preferred_tool in _ROUTER_BINDINGS.items():
            tool = preferred_tool
            if tool not in registered:
                # fall back to legacy router tool if skill missing
                try:
                    from neuron.v3.capability_router import _CAPABILITY_TOOLS
                    legacy = _CAPABILITY_TOOLS.get(router_id)
                    if legacy and legacy in registered:
                        tool = legacy
                except Exception:
                    pass
            if tool not in registered and tool.replace(".", "_") in registered:
                tool = tool.replace(".", "_")
            if tool not in registered:
                self.legacy_only.append(router_id)
                continue
            cap = self._get_raw(tool) or self._get_by_tool_raw(tool)
            if cap:
                if router_id not in cap.aliases:
                    cap.aliases.append(router_id)
                cap.router_id = router_id
                cap.fast_path_enabled = True
                if router_id not in self._by_id:
                    # alias lookup
                    self._by_id[router_id] = cap
                if router_id not in self.shared:
                    self.shared.append(router_id)
            else:
                self.legacy_only.append(router_id)

        # Intent keys
        for intent, tools in _INTENT_MAP.items():
            for t in tools:
                cap = self._get_raw(t) or self._get_by_tool_raw(t)
                if cap and intent not in cap.intent_keys:
                    cap.intent_keys.append(intent)

        # Planner-only: registered skills without router binding
        router_tools = set(_ROUTER_BINDINGS.values()) | set(_ROUTER_LEGACY_TOOLS.keys())
        for cid, cap in list(self._by_id.items()):
            if cap.capability_id != cid:
                continue  # alias entry
            if cap.fast_path_enabled or cap.router_id:
                continue
            if cap.tool_name in router_tools:
                continue
            if cap.domain in (
                CapabilityDomain.YOUTUBE,
                CapabilityDomain.BLENDER,
                CapabilityDomain.INTEGRATION,
                CapabilityDomain.BROWSER,
            ) and "." in cap.capability_id:
                if cap.capability_id not in self.planner_only:
                    self.planner_only.append(cap.capability_id)

        # Detect duplicate: dotted skill + legacy tool both planner-enabled for same intent
        for intent, tools in _INTENT_MAP.items():
            present = [t for t in tools if self.get(t) or self.get_by_tool(t)]
            dotted = [t for t in present if "." in t]
            legacy = [t for t in present if "." not in t]
            if dotted and legacy:
                # Not counted as duplicate implementation — shared semantics with aliases
                pass

        # V4.9 — sync enabled learned procedures as COMPOSITE capabilities
        try:
            from neuron.v4.learn.registry import get_procedure_registry
            get_procedure_registry().sync_catalog()
        except Exception:
            pass

        log.info(
            "[CAPABILITY] catalog built n=%d shared=%d legacy_only=%d planner_only=%d",
            len([c for i, c in self._by_id.items() if i == c.capability_id]),
            len(self.shared),
            len(self.legacy_only),
            len(self.planner_only),
        )

    def _register(self, desc: CapabilityDescriptor) -> None:
        existing = self._by_id.get(desc.capability_id)
        if existing and existing.tool_name != desc.tool_name:
            self.duplicate_impl_count += 1
        self._by_id[desc.capability_id] = desc
        self._by_tool[desc.tool_name] = desc.capability_id
        for a in desc.aliases:
            self._by_id[a] = desc

    def register(self, desc: CapabilityDescriptor) -> None:
        self.ensure()
        self._register(desc)

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        if not self._built:
            self.ensure()
        return self._by_id.get(capability_id)

    def get_by_tool(self, tool: str) -> CapabilityDescriptor | None:
        if not self._built:
            self.ensure()
        cid = self._by_tool.get(tool)
        if cid:
            return self._by_id.get(cid)
        return self._by_id.get(tool)

    def _get_raw(self, capability_id: str) -> CapabilityDescriptor | None:
        return self._by_id.get(capability_id)

    def _get_by_tool_raw(self, tool: str) -> CapabilityDescriptor | None:
        cid = self._by_tool.get(tool)
        if cid:
            return self._by_id.get(cid)
        return self._by_id.get(tool)

    def list_domain(self, domain: CapabilityDomain | str) -> list[CapabilityDescriptor]:
        self.ensure()
        d = domain if isinstance(domain, CapabilityDomain) else CapabilityDomain(str(domain).upper())
        out = []
        seen = set()
        for cid, cap in self._by_id.items():
            if cid != cap.capability_id:
                continue
            if cap.domain is d and cid not in seen:
                seen.add(cid)
                out.append(cap)
        return out

    def match_intent(self, intent: str) -> list[CapabilityDescriptor]:
        self.ensure()
        intent = (intent or "").strip().lower()
        names = list(_INTENT_MAP.get(intent, []))
        # Also from plan.tools candidates (names only — no pick_tool)
        try:
            from neuron.v4.plan.tools import candidates_for_intent
            for n in candidates_for_intent(intent):
                if n not in names:
                    names.append(n)
        except Exception:
            pass
        out: list[CapabilityDescriptor] = []
        seen = set()
        for n in names:
            cap = self.get(n) or self.get_by_tool(n)
            if not cap:
                # try resolve via registry alias
                try:
                    from neuron.brain import tool_registry as tr
                    rn = tr.resolve_name(n)
                    if rn:
                        cap = self.get_by_tool(rn) or self.get(rn)
                except Exception:
                    pass
            if cap and cap.capability_id not in seen and cap.planner_enabled:
                seen.add(cap.capability_id)
                out.append(cap)
        return out

    def find_alternates(
        self,
        intent: str,
        *,
        tried: set[str] | None = None,
        max_n: int = 5,
    ) -> list[CapabilityDescriptor]:
        tried = set(tried or set())
        out = []
        for cap in self.match_intent(intent):
            if cap.tool_name in tried or cap.capability_id in tried:
                continue
            if not cap.recovery_enabled:
                continue
            key = f"{intent}|{cap.tool_name}"
            if self.failures.recently_failed(key):
                continue
            out.append(cap)
            if len(out) >= max_n:
                break
        return out

    def supports(self, capability_id: str) -> bool:
        self.ensure()
        return capability_id in self._by_id

    def coverage_report(self) -> dict[str, Any]:
        self.ensure()
        unique = [c for i, c in self._by_id.items() if i == c.capability_id]
        return {
            "total": len(unique),
            "shared": list(self.shared),
            "legacy_only": list(self.legacy_only),
            "planner_only": list(self.planner_only)[:40],
            "LEGACY_ONLY_CAPABILITY_COUNT": len(self.legacy_only),
            "DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT": self.duplicate_impl_count,
            "by_domain": {
                d.value: len(self.list_domain(d))
                for d in CapabilityDomain
                if self.list_domain(d)
            },
        }

    def note_outcome(
        self,
        tool: str,
        *,
        exec_ok: bool | None = None,
        verify: str = "",
        latency_ms: float = 0.0,
        recovery: bool = False,
        intent: str = "",
    ) -> None:
        cap = self.get_by_tool(tool) or self.get(tool)
        key = cap.capability_id if cap else tool
        st = self.stats.setdefault(key, CapabilityStats())
        st.note(exec_ok=exec_ok, verify=verify, latency_ms=latency_ms, recovery=recovery)
        if verify.upper() == "FAILURE" or exec_ok is False:
            self.failures.note(f"{intent}|{tool}" if intent else tool)

    def canonical_tool(self, name: str) -> str | None:
        """Map router/legacy/alias → registered tool name."""
        self.ensure()
        if name in _ROUTER_LEGACY_TOOLS:
            preferred = _ROUTER_LEGACY_TOOLS[name]
            cap = self.get(preferred) or self.get_by_tool(preferred)
            if cap:
                return cap.tool_name
        cap = self.get(name) or self.get_by_tool(name)
        if cap:
            return cap.tool_name
        try:
            from neuron.brain import tool_registry as tr
            tr.ensure_bootstrapped()
            if tr.is_registered(name):
                return tr.resolve_name(name)
        except Exception:
            pass
        return None


def get_capability_catalog() -> CapabilityCatalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = CapabilityCatalog()
        _CATALOG.ensure()
    return _CATALOG


def reset_capability_catalog() -> CapabilityCatalog:
    global _CATALOG
    _CATALOG = CapabilityCatalog()
    _CATALOG.rebuild()
    return _CATALOG


__all__ = [
    "CapabilityCatalog",
    "get_capability_catalog",
    "reset_capability_catalog",
    "_INTENT_MAP",
]
