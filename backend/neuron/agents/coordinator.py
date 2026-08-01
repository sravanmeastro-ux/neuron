"""Coordinator — routes goals to specialized agents and composes results."""

from __future__ import annotations

import re
from typing import Any

from neuron.agents.bus import MessageBus, get_bus, reset_bus
from neuron.agents.specialists import build_specialists
from neuron.agents.types import AgentMessage, AgentResult, AgentRole


_SIMPLE = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|focus\s+\w+)$",
    re.I,
)

_MEMORY = re.compile(r"\b(remember|what did i|recall|memory|forget that|pinned)\b", re.I)
_RESEARCH = re.compile(r"\b(research|summarize|look up|investigate|sources?\s+on)\b", re.I)
_BROWSER = re.compile(r"\b(https?://|www\.|youtube|google|navigate|search\s+the\s+web|open\s+site)\b", re.I)
_VISION = re.compile(r"\b(click|look at|on screen|find (the )?button|read (the )?screen|what('s| is) on (my )?screen)\b", re.I)
_CODE = re.compile(r"\b(vs\s*code|visual studio code|cursor ide|open (the )?project|python file|hello world)\b", re.I)
_DESKTOP = re.compile(r"\b(open|launch|focus|close|minimize|maximize)\s+\w+", re.I)
_MULTI = re.compile(
    r"\b(then|after that|and then|multi[- ]?step|workflow|plan (and|to)|download .+ install|"
    r"create .+ then|move .+ zip)\b",
    re.I,
)


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        return bool((cfg.get("agent") or {}).get("multi_agent_system", True))
    except Exception:
        return True


def looks_like_multi_agent(text: str) -> bool:
    """True when Coordinator should claim (multi-specialist or explicit multi-agent)."""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if low.startswith("multi agent") or low.startswith("coordinate") or "with agents" in low:
        return True
    # Don't steal ultra-simple Category A
    if _SIMPLE.match(t) and not _MULTI.search(t):
        return False
    # Multi-step / research / memory+desktop / vision workflows
    if _MULTI.search(t):
        return True
    # Explicit specialist domains that benefit from communication
    signals = sum(bool(p.search(t)) for p in (_MEMORY, _RESEARCH, _BROWSER, _VISION, _CODE))
    if signals >= 2:
        return True
    if _RESEARCH.search(t) or (_MEMORY.search(t) and len(t.split()) > 4):
        return True
    if _MULTI.search(t) or (" and " in low and _DESKTOP.search(t) and (_BROWSER.search(t) or _CODE.search(t))):
        return True
    return False


def select_roles(text: str) -> list[str]:
    """Ordered specialist roles for this goal (planner first when multi-step)."""
    roles: list[str] = []
    multi = bool(_MULTI.search(text))
    if multi:
        roles.append(AgentRole.PLANNER.value)
    if _MEMORY.search(text):
        roles.append(AgentRole.MEMORY.value)
    if _RESEARCH.search(text):
        roles.append(AgentRole.RESEARCH.value)
    if _BROWSER.search(text) and AgentRole.RESEARCH.value not in roles:
        roles.append(AgentRole.BROWSER.value)
    if _VISION.search(text):
        roles.append(AgentRole.VISION.value)
    if _CODE.search(text):
        roles.append(AgentRole.CODE.value)
    if _DESKTOP.search(text) and AgentRole.CODE.value not in roles:
        roles.append(AgentRole.DESKTOP.value)
    # Executor only when we planned a workflow or multiple acting domains
    acting = [r for r in roles if r not in (AgentRole.PLANNER.value, AgentRole.MEMORY.value)]
    if multi or len(acting) >= 2:
        if AgentRole.EXECUTOR.value not in roles:
            roles.append(AgentRole.EXECUTOR.value)
        if multi and AgentRole.PLANNER.value not in roles:
            roles.insert(0, AgentRole.PLANNER.value)
    # Dedupe preserve order
    seen = set()
    out = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    if not out:
        out = [AgentRole.DESKTOP.value]
    return out


class Coordinator:
    """Routes work across specialists via the message bus."""

    def __init__(self, bus: MessageBus | None = None) -> None:
        self.bus = bus or get_bus()
        self._ready = False

    def ensure_agents(self) -> None:
        if self._ready and self.bus.roles():
            return
        for agent in build_specialists():
            agent.register(self.bus)
        self._ready = True

    def status(self) -> dict[str, Any]:
        self.ensure_agents()
        return {
            "enabled": _enabled(),
            "roles": self.bus.roles(),
            "history_n": len(self.bus.history(200)),
            "recent": self.bus.history(8),
        }

    def run(
        self,
        text: str,
        *,
        confirmed: bool = False,
        loop: Any | None = None,
    ) -> tuple[str, bool, dict]:
        self.ensure_agents()
        roles = select_roles(text)
        transcript: list[dict[str, Any]] = []
        acted_any = False
        says: list[str] = []

        # Announce
        self.bus.publish(
            AgentMessage(
                kind="broadcast",
                from_role=AgentRole.COORDINATOR.value,
                to_role="",
                payload={"text": text, "roles": roles},
            )
        )

        plan_data = None
        # Planner first when present
        if AgentRole.PLANNER.value in roles:
            pr = self.bus.request(
                AgentRole.PLANNER.value,
                {"text": text, "goal": text},
                from_role=AgentRole.COORDINATOR.value,
            )
            transcript.append({"role": "planner", **pr.to_dict()})
            says.append(pr.say)
            if pr.ok:
                plan_data = (pr.data or {}).get("plan")

        # Memory / Research / Vision / Browser / Code / Desktop as supporting
        for role in roles:
            if role in (AgentRole.PLANNER.value, AgentRole.EXECUTOR.value):
                continue
            payload: dict[str, Any] = {"text": text, "query": text, "confirmed": confirmed}
            if role == AgentRole.MEMORY.value:
                if re.search(r"\bremember\b", text, re.I):
                    payload["op"] = "remember"
                    # extract after remember
                    m = re.search(r"remember(?: that)?\s+(.+)$", text, re.I)
                    if m:
                        payload["text"] = m.group(1).strip()
                else:
                    payload["op"] = "query"
            if role == AgentRole.DESKTOP.value:
                payload["op"] = "open"
                m = re.search(r"\b(?:open|launch|focus)\s+([A-Za-z0-9][\w .+-]*)", text, re.I)
                if m:
                    payload["name"] = m.group(1).strip()
            if role == AgentRole.BROWSER.value:
                payload["op"] = "search" if "search" in text.lower() else "navigate"
                m = re.search(r"(https?://\S+)", text, re.I)
                if m:
                    payload["url"] = m.group(1)
            if role == AgentRole.CODE.value:
                payload["op"] = "cursor" if "cursor" in text.lower() else "vscode"

            r = self.bus.request(role, payload, from_role=AgentRole.COORDINATOR.value)
            transcript.append({"role": role, **r.to_dict()})
            if r.say:
                says.append(r.say)
            acted_any = acted_any or r.acted

        # Executor runs plan or full goal when multi-step
        if AgentRole.EXECUTOR.value in roles:
            # Prefer executing planned steps via bus communication with specialists
            if plan_data and isinstance(plan_data.get("subtasks"), list):
                for st in plan_data["subtasks"][:8]:
                    action = str(st.get("action") or "")
                    args = st.get("args") or {}
                    target_role = _action_to_role(action)
                    if target_role and target_role != AgentRole.EXECUTOR.value:
                        r = self.bus.request(
                            target_role,
                            {"action": action, "args": args, "text": st.get("description") or "", "confirmed": confirmed, "op": action},
                            from_role=AgentRole.COORDINATOR.value,
                        )
                    else:
                        r = self.bus.request(
                            AgentRole.EXECUTOR.value,
                            {"action": action, "args": args, "confirmed": confirmed},
                            from_role=AgentRole.COORDINATOR.value,
                        )
                    transcript.append({"role": r.role, "step": st.get("description"), **r.to_dict()})
                    if r.say:
                        says.append(r.say)
                    acted_any = acted_any or r.acted
                    if not r.ok and st.get("requires_confirm") and not confirmed:
                        return (
                            r.say or "Confirmation required.",
                            True,
                            {
                                "path": "multi_agent",
                                "needs_confirm": {"action": action, "args": args, "reason": r.error or r.say},
                                "agents": transcript,
                                "roles": roles,
                            },
                        )
            else:
                r = self.bus.request(
                    AgentRole.EXECUTOR.value,
                    {"text": text, "goal": text, "confirmed": confirmed},
                    from_role=AgentRole.COORDINATOR.value,
                )
                transcript.append({"role": "executor", **r.to_dict()})
                if r.say:
                    says.append(r.say)
                acted_any = acted_any or r.acted
                if (r.data or {}).get("meta", {}).get("needs_confirm"):
                    return r.say, True, {
                        "path": "multi_agent",
                        "needs_confirm": r.data["meta"]["needs_confirm"],
                        "agents": transcript,
                        "roles": roles,
                    }

        say = " ".join(s for s in says if s).strip() or f"Coordinated agents: {', '.join(roles)}."
        return say, True, {
            "path": "multi_agent",
            "roles": roles,
            "agents": transcript,
            "plan": plan_data,
            "bus_history": self.bus.history(12),
            "acted": acted_any,
        }


def _action_to_role(action: str) -> str:
    a = (action or "").lower()
    if a.startswith("browser_") or a in ("open_website", "search_web"):
        return AgentRole.BROWSER.value
    if a in ("screen_understand", "analyze_screen", "ocr_screen", "click_element", "click_ui_element"):
        return AgentRole.VISION.value
    if a in ("open_app", "focus_app", "close_app", "get_windows", "minimize_app"):
        return AgentRole.DESKTOP.value
    if a in ("open_file", "open_folder", "search_files") or a.startswith("vscode") or a.startswith("cursor"):
        return AgentRole.CODE.value
    if a.startswith("memory") or a in ("remember",):
        return AgentRole.MEMORY.value
    if a in ("browser_research", "web_search_summarize"):
        return AgentRole.RESEARCH.value
    return AgentRole.EXECUTOR.value


_COORD: Coordinator | None = None


def get_coordinator() -> Coordinator:
    global _COORD
    if _COORD is None:
        _COORD = Coordinator()
    return _COORD


def handle(
    text: str,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
) -> tuple[str, bool, dict]:
    return get_coordinator().run(text, confirmed=confirmed, loop=loop)


def tool_multi_agent_run(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    if not text:
        return fail("Need request text.")
    confirmed = bool(args.get("confirmed", False))
    say, acted, meta = handle(text, confirmed=confirmed)
    return ok(say, state=meta, method="multi_agent") if acted or meta else fail(say or "Failed", state=meta)


def tool_multi_agent_status(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    st = get_coordinator().status()
    return ok(f"Agents: {', '.join(st.get('roles') or [])}", state=st, method="multi_agent")


def tool_multi_agent_ask(args: dict | None = None) -> Any:
    """Direct bus request to a named specialist."""
    from neuron.windows.result import ok, fail
    args = args or {}
    role = str(args.get("role") or args.get("agent") or "").strip().lower()
    if not role:
        return fail("Need role (planner|executor|vision|browser|memory|desktop|code|research).")
    coord = get_coordinator()
    coord.ensure_agents()
    payload = dict(args)
    payload.pop("role", None)
    payload.pop("agent", None)
    r = coord.bus.request(role, payload, from_role=AgentRole.COORDINATOR.value)
    if r.ok:
        return ok(r.say or f"{role} ok", state=r.to_dict(), method="multi_agent")
    return fail(r.error or r.say or "Agent failed", state=r.to_dict(), method="multi_agent")
