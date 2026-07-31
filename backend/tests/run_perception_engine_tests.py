"""V3.4 PerceptionEngine + ElementResolver — mocked unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neuron.v3.perception_types import Observation, PerceivedElement
from neuron.v3.perception_engine import (
    PerceptionEngine,
    reset_engine,
    ui_candidates_for,
    wants_ui_candidates,
)
from neuron.v3.element_resolver import ElementResolver, resolve_element
from neuron.v3.reference_resolver import resolve_reference
from neuron.v3.context_engine import reset_engine as reset_ctx


def _el(
    name: str,
    role: str,
    *,
    source: str = "uia",
    confidence: float = 0.9,
    index: int | None = None,
    color: str | None = None,
    application: str = "",
) -> PerceivedElement:
    return PerceivedElement(
        id=f"{source}:{name}",
        role=role,
        name=name,
        source=source,
        confidence=confidence,
        index=index,
        interactive=True,
        clickable=role != "text_field",
        application=application or name,
        meta={"color": color} if color else {},
    )


def test_observation_shape():
    obs = Observation(
        elements=[_el("Search", "text_field", source="dom")],
        application="Chrome",
        window="YouTube",
        sources_used=["dom"],
    )
    d = obs.to_dict()
    assert d["count"] == 1
    assert d["elements"][0]["role"] == "text_field"
    assert "Search" in obs.compact()
    cand = obs.ui_candidates()[0]
    assert cand["label"] == "Search"
    print("OK observation shape")


def test_hierarchy_skips_vision_when_dom_answers():
    vision_calls = []

    def api():
        return []

    def dom():
        return [
            _el("Intro to Blender", "video", source="dom", index=1),
            _el("Geometry Nodes", "video", source="dom", index=2),
            _el("Shading Tips", "video", source="dom", index=3),
        ]

    def uia():
        return [_el("Search", "text_field", source="uia")]

    def ocr():
        raise AssertionError("OCR should not run when videos answer request")

    def vision(req: str) -> str:
        vision_calls.append(req)
        return "SHOULD_NOT_RUN"

    eng = PerceptionEngine(
        api_provider=api,
        dom_provider=dom,
        uia_provider=uia,
        ocr_provider=ocr,
        vision_provider=vision,
    )
    obs = eng.observe(
        "play the first video",
        allow_ocr=True,
        allow_vision=True,
        prefer_roles={"video"},
    )
    assert "dom" in obs.sources_used
    assert not obs.vision_used
    assert vision_calls == []
    assert len(obs.by_role("video")) == 3
    print("OK skip vision when DOM answers", obs.sources_used)


def test_ocr_used_when_sparse():
    ocr_called = []

    eng = PerceptionEngine(
        api_provider=lambda: [],
        dom_provider=lambda: [],
        uia_provider=lambda: [],
        ocr_provider=lambda: (
            ocr_called.append(1)
            or [_el("Settings", "button", source="ocr", confidence=0.6)]
        ),
        vision_provider=lambda r: (_ for _ in ()).throw(AssertionError("no vision")),
    )
    obs = eng.observe("settings button", allow_ocr=True, allow_vision=False)
    assert ocr_called
    assert "ocr" in obs.sources_used
    assert obs.by_role("button")[0].name == "Settings"
    print("OK OCR when sparse")


def test_vision_only_when_forced_and_insufficient():
    eng = PerceptionEngine(
        api_provider=lambda: [],
        dom_provider=lambda: [],
        uia_provider=lambda: [],
        ocr_provider=lambda: [],
        vision_provider=lambda r: 'I see a "Mystery Panel"',
    )
    obs = eng.observe("describe the screen", allow_ocr=False, allow_vision=True)
    assert obs.vision_used
    assert any(e.name == "Mystery Panel" for e in obs.elements)
    print("OK vision when insufficient")


def test_element_first_video():
    obs = Observation(
        elements=[
            _el("Intro to Blender", "video", index=1, source="api"),
            _el("Geometry Nodes", "video", index=2, source="api"),
            _el("Shading Tips", "video", index=3, source="api"),
        ],
        sources_used=["api"],
    )
    hit = resolve_element("first video", observation=obs)
    assert hit.element is not None
    assert hit.element.name == "Intro to Blender"
    assert hit.action_hint == "play_result"
    assert hit.args_hint.get("index") == 1
    print("OK first video", hit.element.name)


def test_element_second_result():
    obs = Observation(
        elements=[
            _el("Result A", "browser_result", index=1, source="dom"),
            _el("Result B", "browser_result", index=2, source="dom"),
        ]
    )
    hit = resolve_element("second result", observation=obs)
    assert hit.element is not None
    assert hit.element.name == "Result B"
    print("OK second result")


def test_element_search_box():
    obs = Observation(
        elements=[
            _el("Home", "button", source="uia"),
            _el("Search", "text_field", source="dom"),
            _el("Settings", "button", source="uia"),
        ]
    )
    hit = resolve_element("search box", observation=obs)
    assert hit.element is not None
    assert hit.element.role == "text_field"
    assert hit.action_hint == "focus"
    print("OK search box")


def test_element_settings_button():
    obs = Observation(
        elements=[
            _el("Home", "button"),
            _el("Settings", "button"),
            _el("Help", "button"),
        ]
    )
    hit = resolve_element("settings button", observation=obs)
    assert hit.element is not None
    assert hit.element.name == "Settings"
    print("OK settings button")


def test_element_blue_button():
    obs = Observation(
        elements=[
            _el("Cancel", "button", color="gray"),
            _el("Continue", "button", color="blue"),
            _el("Delete", "button", color="red"),
        ]
    )
    hit = resolve_element("blue button", observation=obs)
    assert hit.element is not None
    assert hit.element.name == "Continue"
    print("OK blue button")


def test_element_blender_window():
    obs = Observation(
        elements=[
            _el("Google Chrome", "window", application="Chrome", source="api"),
            _el("Blender", "window", application="Blender", source="api"),
            _el("Discord", "window", application="Discord", source="api"),
        ]
    )
    hit = resolve_element("Blender window", observation=obs)
    assert hit.element is not None
    assert "Blender" in hit.element.name
    assert hit.action_hint == "activate_window"
    print("OK Blender window")


def test_ui_candidates_feed_reference_resolver():
    reset_ctx()
    eng = PerceptionEngine(
        api_provider=lambda: [
            _el("Intro to Blender", "video", index=1, source="api"),
            _el("Geometry Nodes", "video", index=2, source="api"),
            _el("Shading Tips", "video", index=3, source="api"),
        ],
        dom_provider=lambda: [],
        uia_provider=lambda: [],
        ocr_provider=lambda: [],
    )
    reset_engine(eng)
    cands = ui_candidates_for("play the second video", engine=eng)
    assert len(cands) >= 2
    r = resolve_reference("play the second one", ui_candidates=cands)
    assert not r.needs_clarification, r.to_dict()
    assert r.resolved_target == "Geometry Nodes"
    assert r.source == "ui_candidates"
    print("OK perception -> reference", r.resolved_target)


def test_wants_ui_candidates():
    assert wants_ui_candidates("play the first video")
    assert wants_ui_candidates("the second one")
    assert wants_ui_candidates("search box")
    assert not wants_ui_candidates("close it")
    assert not wants_ui_candidates("open notepad")
    print("OK wants_ui_candidates gates")


def test_semantics_before_coords():
    """Resolver picks by name/role without needing x,y."""
    obs = Observation(
        elements=[
            PerceivedElement(
                id="a",
                role="button",
                name="Settings",
                source="uia",
                confidence=0.9,
                # no bounds
            )
        ]
    )
    hit = ElementResolver().resolve_against("settings button", obs)
    assert hit.element is not None
    assert hit.element.bounds is None
    assert "x" not in hit.args_hint or hit.args_hint.get("x") is None
    assert hit.args_hint.get("name") == "Settings"
    print("OK semantics before coords")


if __name__ == "__main__":
    test_observation_shape()
    test_hierarchy_skips_vision_when_dom_answers()
    test_ocr_used_when_sparse()
    test_vision_only_when_forced_and_insufficient()
    test_element_first_video()
    test_element_second_result()
    test_element_search_box()
    test_element_settings_button()
    test_element_blue_button()
    test_element_blender_window()
    test_ui_candidates_feed_reference_resolver()
    test_wants_ui_candidates()
    test_semantics_before_coords()
    print("\nALL PerceptionEngine / ElementResolver tests passed")
