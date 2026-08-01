"""Developer Mode orchestrator — routes SE workflows to capabilities."""

from __future__ import annotations

from typing import Any

from neuron.developer import analyze, build_test, deps, git_ops, index as index_mod, refactor
from neuron.developer.detect import classify_dev_intent
from neuron.developer.types import DevCapability, DevResult


def _ide_open(ide: str = "cursor") -> DevResult:
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        mapping = {
            "cursor": ("cursor.open", "Cursor"),
            "code": ("vscode.open", "Code"),
            "vscode": ("vscode.open", "Code"),
            "devenv": ("open_app", "Visual Studio"),
            "visual": ("open_app", "Visual Studio"),
        }
        key = ide.lower()
        tool, app = mapping.get(key, ("cursor.open", "Cursor"))
        if tool == "open_app":
            r = tool_registry.execute("open_app", {"name": app}, confirmed=True)
        else:
            # try plugin tool then fallback
            if tool_registry.get(tool) or tool_registry.get(tool.replace(".", "_")):
                t = tool if tool_registry.get(tool) else tool.replace(".", "_")
                r = tool_registry.execute(t, {}, confirmed=True)
            else:
                r = tool_registry.execute("open_app", {"name": app}, confirmed=True)
        return DevResult(ok=True, say=f"Opening {app}.", acted=True, capability=DevCapability.IDE.value, data={"result": str(r)[:200]})
    except Exception as exc:
        return DevResult(ok=False, error=str(exc), capability=DevCapability.IDE.value)


def dispatch(capability: str, args: dict[str, Any] | None = None) -> DevResult:
    args = args or {}
    root = args.get("root")

    if capability == DevCapability.STATUS.value:
        idx = index_mod.index_project(root)
        return DevResult(
            ok=True,
            say=f"Developer Mode online for '{idx.name}' ({', '.join(idx.languages) or 'unknown stack'}).",
            capability=capability,
            data={"index": idx.to_dict()},
        )

    if capability == DevCapability.INDEX.value:
        idx = index_mod.index_project(root)
        return DevResult(ok=True, say=f"Indexed {idx.name}: {idx.file_count} files, langs={idx.languages}.", capability=capability, data=idx.to_dict())

    if capability == DevCapability.ANALYZE.value:
        data = analyze.analyze_project(root)
        return DevResult(ok=True, say=data["summary"], capability=capability, data=data)

    if capability == DevCapability.DEPS.value:
        graph = deps.dependency_graph(root)
        return DevResult(
            ok=True,
            say=f"Dependency graph: {graph['node_count']} nodes, {graph['edge_count']} edges.",
            capability=capability,
            data=graph,
        )

    if capability == DevCapability.BUILD.value:
        info = build_test.detect_build_commands(root)
        cmds = info.get("commands") or []
        if args.get("run") and cmds:
            # Prefer first build-like command; require explicit run flag from classifier carefully
            chosen = next((c for c in cmds if c["name"] == "build"), cmds[0])
            # Default to detect-only unless args.run is True and confirmed-ish — still allow monitor
            if args.get("execute"):
                result = build_test.run_monitored(chosen["cmd"], root)
                return DevResult(
                    ok=result.get("ok", False),
                    say=f"Build {'passed' if result.get('passed') else 'failed'}: {chosen['cmd']}",
                    acted=True,
                    capability=capability,
                    data={"detect": info, "result": result},
                )
        preview = ", ".join(c["cmd"] for c in cmds[:4]) or "none detected"
        return DevResult(
            ok=True,
            say=f"Build commands: {preview}. Say 'execute build' to run.",
            capability=capability,
            data=info,
            suggestions=[c["cmd"] for c in cmds[:5]],
        )

    if capability == DevCapability.TEST.value:
        info = build_test.detect_test_commands(root)
        cmds = info.get("commands") or []
        if args.get("execute") or (args.get("run") and args.get("cmd")):
            cmd = args.get("cmd") or (cmds[0]["cmd"] if cmds else "pytest -q")
            if not cmd and cmds:
                cmd = cmds[0]["cmd"]
            if args.get("execute"):
                result = build_test.run_monitored(cmd, root)
                return DevResult(
                    ok=result.get("ok", False),
                    say=f"Tests {'passed' if result.get('passed') else 'failed'}: {cmd}",
                    acted=True,
                    capability=capability,
                    data={"detect": info, "result": result},
                )
        preview = ", ".join(c["cmd"] for c in cmds[:4]) or "none detected"
        return DevResult(
            ok=True,
            say=f"Test commands: {preview}. Use developer_run with execute to monitor.",
            capability=capability,
            data=info,
            suggestions=[c["cmd"] for c in cmds[:5]],
        )

    if capability == DevCapability.DIAGNOSTICS.value:
        blob = str(args.get("text") or args.get("error") or "")
        # Strip the leading command words for cleaner parse when user said "fix this compile error: ..."
        data = analyze.parse_diagnostics(blob)
        primary = data.get("primary")
        say = (
            f"Found {data['count']} diagnostic(s). Primary: {primary}"
            if primary else "No structured diagnostics found — paste the full compiler output."
        )
        return DevResult(ok=True, say=str(say)[:500], capability=capability, data=data)

    if capability == DevCapability.EXPLAIN.value:
        data = analyze.explain_code_or_trace(str(args.get("text") or ""))
        return DevResult(ok=True, say=data.get("explanation") or "", capability=capability, data=data)

    if capability == DevCapability.BUGS.value:
        data = analyze.localize_bug(str(args.get("text") or ""), root)
        return DevResult(ok=True, say=data.get("advice") or "", capability=capability, data=data)

    if capability == DevCapability.REFACTOR.value:
        data = refactor.refactor_suggestions(str(args.get("text") or ""), root)
        tips = "; ".join(data.get("suggestions") or [])[:400]
        return DevResult(ok=True, say=f"Refactor suggestions: {tips}", capability=capability, data=data, suggestions=data.get("suggestions") or [])

    if capability == DevCapability.GIT.value:
        op = str(args.get("op") or "status")
        if op == "review":
            data = git_ops.git_show_latest(root)
            remote = git_ops.github_remote(root)
            say = f"Latest commit: {data.get('subject')} ({data.get('hash', '')[:8]}) by {data.get('author')}."
            return DevResult(ok=bool(data.get("ok")), say=say, capability=capability, data={**data, "github": remote})
        if op == "log":
            data = git_ops.git_log(root)
            return DevResult(ok=data.get("ok", False), say="Recent commits:\n" + "\n".join(data.get("commits") or [])[:400], capability=capability, data=data)
        if op == "diff":
            data = git_ops.git_diff(root)
            return DevResult(ok=data.get("ok", False), say=data.get("diff_stat") or "(clean)", capability=capability, data=data)
        data = git_ops.git_status(root)
        return DevResult(ok=data.get("ok", False), say=data.get("stdout") or data.get("stderr") or "git status", capability=capability, data=data)

    if capability == DevCapability.GITHUB.value:
        data = git_ops.github_remote(root)
        urls = data.get("github_urls") or []
        return DevResult(ok=True, say=f"GitHub: {', '.join(urls) or 'no github remote'}", capability=capability, data=data)

    if capability == DevCapability.IDE.value:
        return _ide_open(str(args.get("ide") or "cursor"))

    if capability == DevCapability.SCAFFOLD.value:
        data = refactor.scaffold_plan(str(args.get("goal") or args.get("text") or ""), root)
        steps = " → ".join(data.get("steps") or [])
        return DevResult(ok=True, say=f"Scaffold plan ({data.get('kind')}): {steps}", capability=capability, data=data, suggestions=data.get("steps") or [])

    if capability == DevCapability.DOCS.value:
        data = refactor.docs_outline(root)
        return DevResult(ok=True, say=f"Documentation outline ready for {data.get('project', {}).get('name')}.", capability=capability, data=data)

    return DevResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, root: str | None = None) -> tuple[str, bool, dict]:
    intent = classify_dev_intent(text)
    cap = intent.get("capability") or DevCapability.ANALYZE.value
    args = dict(intent.get("args") or {})
    if root:
        args["root"] = root
    # Allow execute only when confirmed for build/test side effects
    if confirmed and cap in (DevCapability.BUILD.value, DevCapability.TEST.value):
        args["execute"] = True
    # If user explicitly asked to run tests, mark run but still prefer execute when confirmed
    low = text.lower()
    if "execute build" in low or "run the build" in low:
        args["execute"] = True
        cap = DevCapability.BUILD.value
    if re_run_tests(low):
        args["run"] = True
        if confirmed or "execute" in low:
            args["execute"] = True

    result = dispatch(cap, args)
    meta = {
        "path": "developer",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say or f"{cap} ok.", True, meta
    return result.error or result.say or f"{cap} failed.", True, meta


def re_run_tests(low: str) -> bool:
    return "run" in low and "test" in low
