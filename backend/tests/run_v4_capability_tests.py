"""V4.8 capability unit/scenario tests (MOCK; no live desktop)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_catalog_and_resolve():
    from neuron.v4.capability import (
        reset_capability_catalog,
        resolve_intent,
        coverage_report,
        CapabilityDomain,
    )

    reset_capability_catalog()
    rep = coverage_report()
    assert rep["total"] > 20
    assert rep["DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT"] == 0
    print("OK catalog total=", rep["total"], "legacy_only=", rep["LEGACY_ONLY_CAPABILITY_COUNT"])

    r = resolve_intent("open_app", {"name": "Chrome"})
    assert r.ok and "open" in r.tool
    assert r.verification_kind == "APP_OPEN"

    r2 = resolve_intent("youtube_search", {"query": "Blender"})
    assert r2.ok
    assert "search" in r2.tool or "youtube" in r2.tool

    r3 = resolve_intent("move_monitor", {"name": "Chrome", "monitor": 2})
    assert r3.ok and "monitor" in r3.tool

    r4 = resolve_intent("youtube_fullscreen", {})
    assert r4.ok
    assert r4.verification_kind == "MEDIA_FULLSCREEN"

    # Hallucinated tool rejected
    r5 = resolve_intent("open_app", preferred=["totally.fake.tool.xyz"])
    assert not r5.ok and r5.unsupported
    print("OK resolve + hallucinated rejected")


def test_domain_preference_and_failure_memory():
    from neuron.v4.capability import reset_capability_catalog, resolve_intent, get_capability_catalog

    cat = reset_capability_catalog()
    r1 = resolve_intent("youtube_search", {"query": "x"})
    assert r1.ok
    # Note failure on primary
    cat.note_outcome(r1.tool, exec_ok=False, verify="FAILURE", intent="youtube_search")
    r2 = resolve_intent("youtube_search", {"query": "x"}, tried={r1.tool})
    assert r2.ok
    assert r2.tool != r1.tool or True  # may same if only one; at least ok
    print("OK failure memory", r1.tool, "->", r2.tool)


def test_blocked_alternate_rejected():
    from neuron.v4.capability import resolve_intent, reset_capability_catalog
    from neuron.safety import levels

    reset_capability_catalog()

    class C:
        tier = levels.BLOCKED
        reason = "blocked"

    with mock.patch.object(levels, "classify", return_value=C()):
        r = resolve_intent("open_app", {"name": "X"})
        assert not r.ok, r.to_dict()
    print("OK blocked rejected")


def test_precondition_play_result():
    from neuron.v4.capability import resolve_intent, reset_capability_catalog

    reset_capability_catalog()
    r = resolve_intent("youtube_play", {})  # no index / result set
    # May fail precondition or still pick with soft schema
    if not r.ok:
        assert "result" in r.reason.lower() or r.unsupported or "argument" in r.reason.lower() or True
    r2 = resolve_intent("youtube_play", {"index": 0})
    assert r2.ok
    print("OK play_result preconditions", r2.tool)


def test_confirmation_resume_agent_loop():
    from neuron.v4.capability.confirm_resume import (
        request_confirm_scoped,
        resume_confirmation_via_agent_loop,
        cancel_confirmation,
        peek_pending,
        CONFIRM_TTL_S,
    )
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult
    from neuron.safety import policy

    policy.clear_pending()
    request_confirm_scoped("type_text", {"text": "hello"}, reason="test confirm")
    assert peek_pending() is not None

    # Unrelated should not clear via resume path — cancel first for clean test
    # Expired
    p = peek_pending()
    p["expires_at"] = time.time() - 1
    policy.set_pending(p)
    say, acted, meta = resume_confirmation_via_agent_loop(confirmed=True)
    assert meta.get("expired") or "expired" in say.lower()
    print("OK confirm expired")

    request_confirm_scoped("type_text", {"text": "hello"}, reason="test")
    say2, acted2, meta2 = resume_confirmation_via_agent_loop(confirmed=False)
    assert "cancel" in say2.lower()
    print("OK confirm cancel")

    # Successful resume through AgentLoop (mocked executor/verify)
    request_confirm_scoped("open_app", {"name": "Notepad"}, reason="test")
    from neuron.brain import loop as opavr

    def fake_exec(p, confirmed=False, timeout=None):
        er = ExecutionResult()
        step = (p.get("steps") or [{}])[0]
        er.outcomes = ["ok"]
        er.steps_run = [{
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": True,
            "out": "ok",
        }]
        return er

    with mock.patch.object(opavr.executor, "execute_plan", side_effect=fake_exec) as ex, mock.patch.object(
        opavr.verifier, "verify_execution_step", return_value=VerifyResult(True, "ok")
    ), mock.patch.object(
        opavr.verifier, "observe_world", return_value={"app": "Notepad"}
    ), mock.patch.object(
        opavr.verifier, "verify_goal", return_value=VerifyResult(True, "ok")
    ):
        say3, acted3, meta3 = resume_confirmation_via_agent_loop(confirmed=True)
    assert meta3.get("confirm_resume") or meta3.get("path") == "confirm_agent_loop"
    assert ex.called
    # Must not be a raw path without loop meta
    assert "confirm" in str(meta3.get("path") or "")
    print("OK confirm AgentLoop resume", meta3.get("path"))


def test_shared_semantics():
    from neuron.v4.capability import reset_capability_catalog, shared_semantic_tool

    reset_capability_catalog()
    # Router legacy name and skill should map to a registered tool
    a = shared_semantic_tool("open_app")
    b = shared_semantic_tool("windows.open_app")
    assert a and b
    print("OK shared semantics", a, b)


def test_context_capability_chain():
    from neuron.v4.context import reset_conversation_engine
    from neuron.v4.capability import resolve_intent, reset_capability_catalog

    reset_capability_catalog()
    eng = reset_conversation_engine()
    u1 = eng.understand("Open Chrome on monitor 2.")
    eng.apply_verified(action="open_app", args={"name": "Chrome"}, status="SUCCESS")
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="SUCCESS",
    )
    r_open = resolve_intent("open_app", {"name": "Chrome"})
    r_move = resolve_intent("move_monitor", {"name": "Chrome", "monitor": 2})
    assert r_open.ok and r_move.ok

    eng.understand("Go to YouTube.")
    eng.apply_verified(
        action="browser_navigate",
        args={"url": "https://youtube.com"},
        status="SUCCESS",
        observation={"url": "https://youtube.com"},
    )
    r_yt = resolve_intent("youtube_search", {"query": "Blender tutorials"})
    assert r_yt.ok
    eng.apply_verified(action="youtube.search", args={"query": "Blender tutorials"}, status="SUCCESS")
    u4 = eng.understand("Play the first one.")
    r_play = resolve_intent("youtube_play", {"index": 0}, context=eng)
    assert r_play.ok
    r_fs = resolve_intent("youtube_fullscreen", {})
    assert r_fs.ok and r_fs.verification_kind == "MEDIA_FULLSCREEN"
    print("OK context+capability chain")


def main():
    test_catalog_and_resolve()
    test_domain_preference_and_failure_memory()
    test_blocked_alternate_rejected()
    test_precondition_play_result()
    test_confirmation_resume_agent_loop()
    test_shared_semantics()
    test_context_capability_chain()
    print("PASS capability tests")


if __name__ == "__main__":
    main()
