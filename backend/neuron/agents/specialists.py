"""Specialized agents — thin wrappers over existing NEURON capabilities."""

from __future__ import annotations

from typing import Any

from neuron.agents.base import BaseAgent
from neuron.agents.types import AgentMessage, AgentResult, AgentRole


class PlannerAgent(BaseAgent):
    role = AgentRole.PLANNER

    def handle(self, message: AgentMessage) -> AgentResult:
        text = str((message.payload or {}).get("text") or (message.payload or {}).get("goal") or "").strip()
        if not text:
            return self.fail("Planner needs a goal text.")
        try:
            from neuron.autonomous.engine import plan_goal
            goal, graph, risk_info = plan_goal(text)
        except Exception:
            from neuron.taskplan.decompose import build_graph
            from neuron.taskplan.extract import extract_goal
            goal = extract_goal(text)
            graph = build_graph(text, goal=goal)
            risk_info = {}
        if not graph or not graph.subtasks:
            return self.fail("Could not decompose goal.", goal=text)
        return self.ok(
            f"Planned {len(graph.subtasks)} steps (risk={risk_info.get('level', '?')}).",
            acted=False,
            goal=goal.to_dict(),
            plan=graph.to_dict(),
            risk=risk_info,
            next_roles=["executor"],
        )


class ExecutorAgent(BaseAgent):
    role = AgentRole.EXECUTOR

    def handle(self, message: AgentMessage) -> AgentResult:
        payload = message.payload or {}
        # Single tool step
        action = str(payload.get("action") or payload.get("tool") or "").strip()
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        confirmed = bool(payload.get("confirmed", False))
        text = str(payload.get("text") or payload.get("goal") or "").strip()

        if action:
            try:
                from neuron.brain import tool_registry
                tool_registry.ensure_bootstrapped()
                result = tool_registry.execute(action, args or {}, confirmed=confirmed)
                ok = True
                msg = str(result)
                if hasattr(result, "success"):
                    ok = bool(result.success)
                    msg = str(getattr(result, "message", None) or msg)
                elif isinstance(result, dict):
                    ok = bool(result.get("ok", result.get("success", True)))
                    msg = str(result.get("message") or result.get("error") or msg)
                return self.ok(msg[:400], acted=ok, result=msg[:200]) if ok else self.fail(msg[:400])
            except Exception as exc:
                return self.fail(str(exc))

        if text:
            try:
                from neuron.autonomous.engine import handle_autonomous
                out = handle_autonomous(text, confirmed=confirmed, force=True)
                if out is None:
                    return self.fail("Executor: not a runnable workflow.")
                say, acted, meta = out
                return self.ok(say or "", acted=acted, meta=meta)
            except Exception as exc:
                return self.fail(str(exc))
        return self.fail("Executor needs action or goal text.")


class VisionAgent(BaseAgent):
    role = AgentRole.VISION

    def handle(self, message: AgentMessage) -> AgentResult:
        req = str(
            (message.payload or {}).get("request")
            or (message.payload or {}).get("text")
            or (message.payload or {}).get("query")
            or ""
        ).strip()
        if not req:
            return self.fail("Vision needs a request.")
        try:
            from neuron.screen import handle as screen_handle
            sr = screen_handle(req, force=True)
            if sr is None:
                # Fallback tool
                from neuron.brain import tool_registry
                tool_registry.ensure_bootstrapped()
                r = tool_registry.execute("screen_understand", {"request": req}, confirmed=True)
                return self.ok(str(r)[:400], acted=True)
            return self.ok(sr.say or "", acted=bool(sr.acted and sr.ok), screen=getattr(sr, "to_dict", lambda: {})())
        except Exception as exc:
            return self.fail(str(exc))


class BrowserAgent(BaseAgent):
    role = AgentRole.BROWSER

    def handle(self, message: AgentMessage) -> AgentResult:
        p = message.payload or {}
        op = str(p.get("op") or p.get("action") or "navigate").lower()
        url = str(p.get("url") or p.get("site") or "").strip()
        query = str(p.get("query") or p.get("text") or "").strip()
        confirmed = bool(p.get("confirmed", True))
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            if op in ("search", "browser_search") and query:
                r = tool_registry.execute(
                    "browser_search",
                    {"site": p.get("site") or "google", "query": query},
                    confirmed=confirmed,
                )
            elif op in ("research",) and query:
                r = tool_registry.execute("browser_research", {"query": query}, confirmed=confirmed)
            elif url:
                try:
                    r = tool_registry.execute("browser_navigate", {"url": url}, confirmed=confirmed)
                except Exception:
                    r = tool_registry.execute("open_website", {"site": url}, confirmed=confirmed)
            elif query:
                r = tool_registry.execute("browser_search", {"site": "google", "query": query}, confirmed=confirmed)
            else:
                return self.fail("Browser needs url or query.")
            return self.ok(str(r)[:400], acted=True)
        except Exception as exc:
            return self.fail(str(exc))


class MemoryAgent(BaseAgent):
    role = AgentRole.MEMORY

    def handle(self, message: AgentMessage) -> AgentResult:
        p = message.payload or {}
        op = str(p.get("op") or "query").lower()
        text = str(p.get("text") or p.get("query") or p.get("memory") or "").strip()
        try:
            from neuron import memory_engine as mem
            if op in ("remember", "store", "save") and text:
                item = mem.remember(text)
                return self.ok(
                    "Remembered.",
                    acted=True,
                    item_id=getattr(item, "item_id", ""),
                    content=text[:200],
                )
            if op in ("forever",) and text:
                item = mem.remember_forever(text)
                return self.ok("Pinned forever.", acted=True, item_id=getattr(item, "item_id", ""))
            if op in ("prompt", "context"):
                blob = mem.for_prompt()
                return self.ok(blob[:500] or "(empty memory)", acted=False, context=blob[:2000])
            # query
            q = text or "recent"
            hits = mem.query_memories(q)
            return self.ok(str(hits)[:500], acted=False, hits=hits)
        except Exception as exc:
            return self.fail(str(exc))


class DesktopAgent(BaseAgent):
    role = AgentRole.DESKTOP

    def handle(self, message: AgentMessage) -> AgentResult:
        p = message.payload or {}
        op = str(p.get("op") or p.get("action") or "open").lower()
        name = str(p.get("name") or p.get("app") or p.get("text") or "").strip()
        confirmed = bool(p.get("confirmed", True))
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            tool = {
                "open": "open_app",
                "open_app": "open_app",
                "focus": "focus_app",
                "focus_app": "focus_app",
                "close": "close_app",
                "close_app": "close_app",
                "windows": "get_windows",
                "apps": "get_running_apps",
            }.get(op, op if op in ("open_app", "focus_app", "close_app", "get_windows", "get_running_apps") else "open_app")
            args: dict[str, Any] = {}
            if tool in ("open_app", "focus_app", "close_app") and name:
                args["name"] = name
            r = tool_registry.execute(tool, args, confirmed=confirmed)
            return self.ok(str(r)[:400], acted=True)
        except Exception as exc:
            return self.fail(str(exc))


class CodeAgent(BaseAgent):
    role = AgentRole.CODE

    def handle(self, message: AgentMessage) -> AgentResult:
        p = message.payload or {}
        op = str(p.get("op") or "open").lower()
        path = str(p.get("path") or p.get("folder") or "").strip()
        text = str(p.get("text") or "").strip()
        confirmed = bool(p.get("confirmed", True))
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            if op in ("open_folder", "folder") and path:
                r = tool_registry.execute("open_folder", {"location": path}, confirmed=confirmed)
            elif op in ("open_file", "file") and path:
                r = tool_registry.execute("open_file", {"path": path}, confirmed=confirmed)
            elif op in ("vscode", "code", "cursor"):
                app = "Cursor" if "cursor" in op else "Code"
                # Prefer plugin tools if present
                tool = "cursor.open" if app == "Cursor" else "vscode.open"
                if tool_registry.get(tool) or tool_registry.get(tool.replace(".", "_")):
                    r = tool_registry.execute(tool.replace(".", "_") if not tool_registry.get(tool) else tool, {}, confirmed=confirmed)
                else:
                    r = tool_registry.execute("open_app", {"name": app}, confirmed=confirmed)
            elif text:
                r = tool_registry.execute("open_app", {"name": "Code"}, confirmed=confirmed)
            else:
                r = tool_registry.execute("open_app", {"name": "Code"}, confirmed=confirmed)
            return self.ok(str(r)[:400], acted=True)
        except Exception as exc:
            return self.fail(str(exc))


class ResearchAgent(BaseAgent):
    role = AgentRole.RESEARCH

    def handle(self, message: AgentMessage) -> AgentResult:
        p = message.payload or {}
        query = str(p.get("query") or p.get("text") or p.get("topic") or "").strip()
        if not query:
            return self.fail("Research needs a query.")
        confirmed = bool(p.get("confirmed", True))
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            if tool_registry.get("browser_research"):
                r = tool_registry.execute("browser_research", {"query": query}, confirmed=confirmed)
            elif tool_registry.get("web_search_summarize"):
                r = tool_registry.execute("web_search_summarize", {"query": query}, confirmed=confirmed)
            else:
                r = tool_registry.execute("browser_search", {"site": "google", "query": query}, confirmed=confirmed)
            return self.ok(str(r)[:500], acted=True)
        except Exception as exc:
            return self.fail(str(exc))


def build_specialists() -> list[BaseAgent]:
    return [
        PlannerAgent(),
        ExecutorAgent(),
        VisionAgent(),
        BrowserAgent(),
        MemoryAgent(),
        DesktopAgent(),
        CodeAgent(),
        ResearchAgent(),
    ]
