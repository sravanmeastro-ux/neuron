"""Workflow engine public API + tool handlers."""

from __future__ import annotations

from typing import Any

from neuron.workflows import editor, recorder, replay, store


def start_recording(name: str = "", channels: list[str] | None = None) -> dict[str, Any]:
    return recorder.start(name, channels=channels)


def stop_recording(name: str = "") -> dict[str, Any]:
    return recorder.stop(name, save=True)


def cancel_recording() -> dict[str, Any]:
    return recorder.cancel()


def recording_status() -> dict[str, Any]:
    return recorder.status()


def run_workflow(
    workflow_id: str,
    *,
    variables: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    wf = store.get(workflow_id)
    if not wf:
        return {"ok": False, "error": f"Unknown workflow: {workflow_id}"}
    return replay.replay(wf, variables=variables, dry_run=dry_run)


def _ok_tool(msg: str, **state: Any):
    from neuron.windows.result import ok
    return ok(msg, state=state or {})


def _fail_tool(msg: str, **state: Any):
    from neuron.windows.result import fail
    return fail(msg, state=state or {})


def tool_workflow_record(args: dict | None = None):
    args = args or {}
    action = str(args.get("action") or "start").lower()
    name = str(args.get("name") or args.get("label") or "").strip()
    if action in ("start", "begin"):
        ch = args.get("channels")
        if isinstance(ch, str):
            ch = [c.strip() for c in ch.split(",") if c.strip()]
        r = start_recording(name, channels=ch if isinstance(ch, list) else None)
        return _ok_tool(r.get("message") or r.get("error") or "record", **r) if r.get("ok") else _fail_tool(r.get("error") or "fail", **r)
    if action in ("stop", "save"):
        r = stop_recording(name)
        return _ok_tool(f"Saved workflow {r.get('id')}", **r) if r.get("ok") else _fail_tool(r.get("error") or "fail", **r)
    if action == "cancel":
        r = cancel_recording()
        return _ok_tool("Cancelled.", **r)
    if action == "status":
        return _ok_tool("Workflow recorder status.", **recording_status())
    return _fail_tool("action must be start|stop|cancel|status")


def tool_workflow_list(args: dict | None = None):
    rows = editor.list_all()
    return _ok_tool(f"{len(rows)} workflows.", workflows=rows)


def tool_workflow_run(args: dict | None = None):
    args = args or {}
    wid = str(args.get("id") or args.get("name") or args.get("workflow") or "").strip()
    if not wid:
        return _fail_tool("Need workflow id/name.")
    variables = args.get("variables") if isinstance(args.get("variables"), dict) else {}
    # allow flat var_foo=bar
    for k, v in args.items():
        if k.startswith("var_") and len(k) > 4:
            variables[k[4:]] = v
    dry = bool(args.get("dry_run") or args.get("dry"))
    r = run_workflow(wid, variables=variables, dry_run=dry)
    if r.get("ok"):
        return _ok_tool(r.get("message") or "Done.", **r)
    return _fail_tool(r.get("error") or "Replay failed.", **r)


def tool_workflow_edit(args: dict | None = None):
    args = args or {}
    action = str(args.get("action") or "get").lower()
    wid = str(args.get("id") or args.get("name") or "").strip()

    if action == "create":
        name = str(args.get("new_name") or args.get("label") or wid or "untitled")
        wf = editor.create_blank(name, variables=args.get("variables") if isinstance(args.get("variables"), dict) else None)
        return _ok_tool(f"Created {wf.id}", workflow=wf.to_dict())

    if action == "list":
        return tool_workflow_list(args)

    if not wid and action != "list":
        return _fail_tool("Need workflow id.")

    if action == "get":
        d = editor.get_detail(wid)
        if not d:
            return _fail_tool(f"Unknown workflow {wid}")
        return _ok_tool(d.get("name") or wid, workflow=d)

    if action == "delete":
        ok = store.delete(wid)
        return _ok_tool("Deleted.") if ok else _fail_tool("Not found.")

    if action == "set_variables":
        vars_ = args.get("variables") if isinstance(args.get("variables"), dict) else {}
        wf = editor.set_variables(wid, vars_, merge=not bool(args.get("replace")))
        return _ok_tool("Variables updated.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    if action == "replace_steps":
        steps = args.get("steps")
        if not isinstance(steps, list):
            return _fail_tool("steps must be a list")
        wf = editor.replace_steps(wid, steps)
        return _ok_tool("Steps replaced.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    if action == "insert_step":
        step = args.get("step")
        if not isinstance(step, dict):
            return _fail_tool("Need step dict")
        wf = editor.insert_step(wid, int(args.get("index") or 0), step)
        return _ok_tool("Step inserted.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    if action == "delete_step":
        wf = editor.delete_step(wid, int(args.get("index") or 0))
        return _ok_tool("Step deleted.", workflow=wf.summary()) if wf else _fail_tool("Bad index or id.")

    if action == "update_step":
        step = args.get("step")
        if not isinstance(step, dict):
            return _fail_tool("Need step dict")
        wf = editor.update_step(wid, int(args.get("index") or 0), step)
        return _ok_tool("Step updated.", workflow=wf.summary()) if wf else _fail_tool("Bad index or id.")

    if action == "add_loop":
        body = args.get("steps") if isinstance(args.get("steps"), list) else []
        wf = editor.add_loop(
            wid,
            index=int(args.get("index") or 0),
            count=int(args.get("count") or 2),
            body=body,
            while_expr=str(args.get("while") or "") or None,
            as_var=str(args.get("as") or "i"),
        )
        return _ok_tool("Loop added.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    if action == "add_condition":
        wf = editor.add_condition(
            wid,
            index=int(args.get("index") or 0),
            when=str(args.get("when") or args.get("condition") or "true"),
            then_steps=args.get("steps") if isinstance(args.get("steps"), list) else [],
            else_steps=args.get("else_steps") if isinstance(args.get("else_steps"), list) else [],
        )
        return _ok_tool("Condition added.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    if action == "meta":
        wf = editor.update_meta(
            wid,
            name=args.get("new_name"),
            description=args.get("description"),
            tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
        )
        return _ok_tool("Updated.", workflow=wf.summary()) if wf else _fail_tool("Not found.")

    return _fail_tool(
        "action: get|create|delete|set_variables|replace_steps|insert_step|"
        "delete_step|update_step|add_loop|add_condition|meta|list"
    )
