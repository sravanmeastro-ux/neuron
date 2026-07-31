"""V3 CapabilityRouter tests — routing only (no live desktop)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_skip_ad():
    from neuron.v3.capability_router import route
    r = route("skip the ad")
    assert r.ok, r.reason
    assert r.capability and r.capability.id == "youtube.skip_ad"
    assert r.steps and r.steps[0]["tool"] == "skip_ad"
    print("OK skip_ad", r.capability.id)


def test_skip_add_mishear():
    from neuron.v3.capability_router import route
    r = route("skip the add")
    assert r.ok and r.capability.id == "youtube.skip_ad"
    print("OK skip_add mishear")


def test_open_chrome():
    from neuron.v3.capability_router import route
    r = route("open chrome")
    assert r.ok and r.capability.id == "windows.open_app"
    assert r.steps[0]["arguments"]["name"] == "chrome"
    print("OK open chrome")


def test_open_youtube_site():
    from neuron.v3.capability_router import route
    r = route("open youtube")
    assert r.ok and r.capability.id == "browser.open"
    assert r.steps[0]["tool"] == "open_website"
    print("OK open youtube")


def test_focus_discord():
    from neuron.v3.capability_router import route
    r = route("switch to discord")
    assert r.ok and r.capability.id == "windows.focus_app"
    print("OK focus discord")


def test_youtube_search():
    from neuron.v3.capability_router import route
    r = route("search youtube for lo-fi beats")
    assert r.ok and r.capability.id == "youtube.search"
    assert "lo-fi" in (r.capability.args.get("query") or "")
    print("OK youtube search", r.capability.args)


def test_play_second():
    from neuron.v3.capability_router import route
    r = route("play the second video")
    assert r.ok
    assert r.steps[0]["tool"] == "play_result"
    assert r.steps[0]["arguments"]["index"] == 2
    print("OK play second")


def test_unsupported_falls_through():
    from neuron.v3.capability_router import route
    r = route("what is the meaning of life")
    assert not r.ok
    assert r.reason == "unsupported"
    print("OK unsupported")


def test_scroll_not_for_skip():
    from neuron.v3.capability_router import route
    r = route("skip the ad")
    assert r.ok
    tools = [s["tool"] for s in r.steps]
    assert "page_scroll" not in tools and "scroll" not in tools
    print("OK skip-ad never scrolls")


def test_list_capabilities():
    from neuron.v3.capability_router import list_capabilities
    caps = list_capabilities()
    assert "youtube.skip_ad" in caps
    assert "windows.open_app" in caps
    print("OK list", len(caps))


def test_intent_promotion():
    from neuron.brain.intent import understand
    from neuron.v3.capability_router import route
    intent = understand("open notepad")
    r = route("open notepad", intent=intent)
    assert r.ok
    assert r.capability.tool in ("open_app", "windows.open_app")
    print("OK intent promotion", r.capability.id, r.capability.source)


def test_as_plan():
    from neuron.v3.capability_router import route
    r = route("press escape")
    plan = r.as_plan("ok")
    assert plan and plan["steps"]
    print("OK as_plan")


def test_volume_up():
    from neuron.v3.capability_router import route
    r = route("volume up")
    assert r.ok and r.capability.id == "system.volume"
    assert r.steps[0]["arguments"]["action"] == "up"
    print("OK volume up")


def test_choose_control_method():
    from neuron.v3.capability_router import choose_control_method
    m, fb = choose_control_method("files")
    assert m == "filesystem"
    print("OK choose_control_method", m, fb[:2])


if __name__ == "__main__":
    test_skip_ad()
    test_skip_add_mishear()
    test_open_chrome()
    test_open_youtube_site()
    test_focus_discord()
    test_youtube_search()
    test_play_second()
    test_unsupported_falls_through()
    test_scroll_not_for_skip()
    test_list_capabilities()
    test_intent_promotion()
    test_as_plan()
    test_volume_up()
    test_choose_control_method()
    print("\nALL CapabilityRouter tests passed")
