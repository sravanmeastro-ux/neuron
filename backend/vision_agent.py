"""General computer-use + multi-screen vision for N.E.U.R.O.N.

Hybrid, accuracy-first design:
1) PRIMARY: Windows accessibility controls (precise rectangles) across monitors.
2) FALLBACK / grounding: vision model looks at ALL monitors and returns
   absolute virtual-desktop coordinates.
3) GLANCE: before most voice commands, attach a live screen map so the brain
   understands "that / this / on my other screen" without Windows Search.
"""

from __future__ import annotations

import base64
import ctypes
import io
import json
import re
import time
from pathlib import Path

import pyautogui

import screen_capture as sc
import vision  # UIA element capture

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_client = None
_cfg = None
_glance_cache = {"t": 0.0, "structural": "", "vlm": "", "request": ""}


def _write_text(text: str):
    """Type text; temporarily disable Caps Lock so casing comes out right."""
    caps_was_on = bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    if caps_was_on:
        pyautogui.press("capslock")
    try:
        pyautogui.write(text, interval=0.02)
    finally:
        if caps_was_on:
            pyautogui.press("capslock")


def _load_config():
    global _cfg
    if _cfg is None:
        _cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _cfg


def _vision_cfg() -> dict:
    return _load_config().get("vision") or {}


def is_enabled() -> bool:
    llm = _load_config().get("llm", {})
    vis = _vision_cfg()
    if vis.get("enabled") is False:
        return False
    return bool(llm.get("enabled") and llm.get("api_key"))


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        llm = _load_config()["llm"]
        _client = OpenAI(
            base_url=llm["base_url"],
            api_key=llm["api_key"],
            timeout=90.0,
            max_retries=0,
        )
    return _client


def _encode_legacy(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------- glance
_SKIP_GLANCE = re.compile(
    r"^(what time|what(?:'s| is) the time|what date|what(?:'s| is) the date|"
    r"volume (?:up|down|mute)|mute|unmute|lock (?:the )?(?:pc|computer|screen)|"
    r"battery|cpu|ram|system (?:status|report)|hello|hi|hey|thanks|thank you|"
    r"good (?:morning|evening|night)|who are you|your name|"
    r"open |close |stop talking|be quiet)\b",
    re.I,
)

# VLM is expensive — when user asks to look / count / describe on-screen content.
_NEED_VLM = re.compile(
    r"\b(what(?:'s| is|s) on|describe|look at|see (?:my |the )?(?:screen|monitor)|"
    r"watch (?:my |the )?(?:screen|monitor)|use your eyes|"
    r"how many|what(?:'s| is)? (?:that|this|the)|"
    r"can you see|do you see|tell me what|"
    r"click that|on (?:my |the )?(?:other|second|left|right) (?:screen|monitor))\b",
    re.I,
)

_SCREEN_QA = re.compile(
    r"\b(what(?:'s| is|s)|describe|look at|see|saw|seeing|how many|count|list|which|tell me)\b"
    r".*\b(screen|screens|monitor|monitors|display|desktop|window|app|there|here)\b"
    r"|\b(can you|do you) see\b"
    r"|\bwhat(?:'s| is) (?:that|this)\b"
    r"|\bhow many\b.+\b(on|in)\b",
    re.I,
)


def needs_glance(text: str) -> bool:
    t = (text or "").strip()
    if not t or _SKIP_GLANCE.search(t):
        return False
    return True


def needs_vlm_glance(text: str) -> bool:
    return bool(_NEED_VLM.search(text or "") or _SCREEN_QA.search(text or ""))


def answer_screen(request: str = "", monitor_id: int = None) -> str:
    """Answer any on-screen question for the ACTIVE APP (not whole OS dump).

    Uses: foreground window screenshot + UI Automation labels + VLM.
    YouTube video tile questions should be handled by browser.list_visible_videos first.
    """
    if not is_enabled():
        return "My vision system isn't enabled yet."

    req = (request or "").strip() or "what is on screen"
    # Grounding: readable controls in the foreground app
    uia_bit = ""
    try:
        elements = vision.capture_elements(
            all_monitors=False, max_elements=60, time_budget=3.0
        )
        if elements:
            uia_bit = vision.elements_as_text(elements)[:1800]
    except Exception as exc:
        print(f"[vision] UIA ground failed: {exc}", flush=True)

    fg = None
    try:
        fg = sc.capture_foreground()
    except Exception as exc:
        print(f"[vision] foreground capture failed: {exc}", flush=True)

    shots = []
    if fg and fg.get("image") is not None:
        shots = [{
            "label": fg["label"],
            "image": fg["image"],
            "monitor": type("M", (), {"id": fg.get("monitor_id", 1)})(),
        }]
    else:
        try:
            import monitor_focus
            if monitor_id is None:
                monitor_id = monitor_focus.get_focus()
        except Exception:
            pass
        shots = sc.capture_all_monitors()
        if monitor_id:
            shots = [s for s in shots if s["monitor"].id == int(monitor_id)] or shots[:1]

    if not shots and not uia_bit:
        try:
            return "Here's what I can see: " + sc.structural_overview().replace("\n", " ")
        except Exception:
            return "I couldn't capture the screen."

    max_w = int(_vision_cfg().get("glance_max_width", 1024))
    quality = int(_vision_cfg().get("glance_jpeg_quality", 55))
    prompt = (
        "You are NEURON's eyes for a Windows desktop voice assistant.\n"
        "Answer the user's question about what is ACTUALLY visible in the image(s).\n"
        "Be concrete: count items, read labels/titles, name buttons and panels.\n"
        "If counting tiles/cards/icons, give the number and list readable names.\n"
        "2–5 short spoken sentences. No markdown.\n"
        f"User asked: {req}\n"
    )
    if uia_bit:
        prompt += (
            "\nUI Automation labels from the foreground app (use to ground names):\n"
            + uia_bit
            + "\n"
        )

    content = [{"type": "text", "text": prompt}]
    for shot in shots[:2]:
        b64 = sc.encode_jpeg(shot["image"], quality=quality, max_w=max_w)
        content.append({"type": "text", "text": shot.get("label") or "Screen"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    model = _vision_cfg().get("model", "qwen2.5vl:7b")
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.15,
            max_tokens=220,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"[#*_`]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 420:
            text = text[:400].rsplit(" ", 1)[0] + "."
        if text:
            return text
    except Exception as exc:
        print(f"[vision] answer_screen failed: {exc}", flush=True)

    if uia_bit:
        # Fallback without VLM: speak control names
        names = []
        for ln in uia_bit.splitlines()[:12]:
            m = re.search(r':\s*"([^"]+)"', ln)
            if m:
                names.append(m.group(1)[:60])
        if names:
            return (
                f"I can read {len(names)} controls in the front window: "
                + "; ".join(names[:8])
                + ("." if len(names) <= 8 else f"; and {len(names) - 8} more.")
            )
    # Last resort: multi-monitor structural map
    try:
        return "Here's what I can see: " + sc.structural_overview().replace("\n", " ")
    except Exception:
        return "I couldn't read the screen clearly just now."


def structural_glance(force: bool = False) -> str:
    """Instant map of monitors + window titles (no GPU)."""
    now = time.time()
    ttl = float(_vision_cfg().get("glance_ttl_seconds", 2.5))
    if not force and _glance_cache["structural"] and now - _glance_cache["t"] < ttl:
        return _glance_cache["structural"]
    text = sc.structural_overview()
    _glance_cache["structural"] = text
    _glance_cache["t"] = now
    return text


def vlm_glance(request: str = "", force: bool = False) -> str:
    """Short VLM summary of every monitor. Cached briefly."""
    if not is_enabled():
        return ""
    now = time.time()
    ttl = float(_vision_cfg().get("glance_ttl_seconds", 2.5))
    if (
        not force
        and _glance_cache["vlm"]
        and now - _glance_cache["t"] < ttl
        and (_glance_cache["request"] == (request or "")[:80] or not request)
    ):
        return _glance_cache["vlm"]

    shots = sc.capture_all_monitors()
    if not shots:
        return ""
    max_w = int(_vision_cfg().get("glance_max_width", 1024))
    quality = int(_vision_cfg().get("glance_jpeg_quality", 50))
    content = [{
        "type": "text",
        "text": (
            "You are NEURON's eyes. Summarize what is visible on EACH monitor "
            "for a voice assistant that must act on the user's request.\n"
            f"User just said: {request or '(general glance)'}\n"
            "For each monitor: 2-4 short bullets — main apps/windows, key UI, "
            "anything the user might mean by 'that' / 'this' / 'the video'. "
            "Be concrete. No fluff."
        ),
    }]
    for shot in shots:
        mon = shot["monitor"]
        b64 = sc.encode_jpeg(shot["image"], quality=quality, max_w=max_w)
        content.append({"type": "text", "text": shot["label"]})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    model = _vision_cfg().get("model", "qwen2.5vl:7b")
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
            max_tokens=450,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[vision] vlm_glance failed: {exc}", flush=True)
        text = ""

    _glance_cache["vlm"] = text
    _glance_cache["request"] = (request or "")[:80]
    _glance_cache["t"] = time.time()
    return text


def quick_screen_context(request: str = "", *, force_vlm: bool = False) -> str:
    """Fast screen context. Structural (instant) by default.

    VLM only when explicitly needed — keeps voice commands snappy.
    """
    if not needs_glance(request) and not force_vlm:
        return ""
    parts = [structural_glance()]
    try:
        import monitor_focus
        focus = monitor_focus.status_line()
        if focus:
            parts.insert(0, focus)
    except Exception:
        pass
    # Config can disable auto-VLM entirely for speed.
    auto_vlm = bool(_vision_cfg().get("glance_vlm_auto", False))
    if force_vlm or (auto_vlm and needs_vlm_glance(request)):
        vlm = vlm_glance(request)
        if vlm:
            parts.append("Vision glance:\n" + vlm)
    return "\n".join(parts)


def describe_screens(request: str = "", monitor_id: int = None) -> str:
    """Spoken answer: what's on the screen(s). Prefer active-app vision for Q&A."""
    if not is_enabled():
        return "My vision system isn't enabled yet."
    # Specific questions → foreground app VLM + UIA (works for ANY app).
    if request and (_SCREEN_QA.search(request) or needs_vlm_glance(request)):
        return answer_screen(request, monitor_id=monitor_id)

    try:
        import monitor_focus
        if monitor_id is None:
            monitor_id = monitor_focus.get_focus()
    except Exception:
        pass

    structural = structural_glance(force=True)
    if monitor_id:
        chunk = []
        keep = False
        for ln in structural.splitlines():
            if ln.startswith("- Monitor"):
                keep = f"Monitor {monitor_id}" in ln
            if keep:
                chunk.append(ln)
        structural_bit = "\n".join(chunk) if chunk else structural
    else:
        structural_bit = structural

    if _vision_cfg().get("describe_structural_only"):
        return structural_bit.replace("\n", " ")

    shots = sc.capture_all_monitors()
    if monitor_id:
        shots = [s for s in shots if s["monitor"].id == int(monitor_id)] or shots[:1]

    if not shots:
        return "Here's what I can see: " + structural_bit.replace("\n", " ")

    max_w = int(_vision_cfg().get("glance_max_width", 896))
    quality = int(_vision_cfg().get("glance_jpeg_quality", 45))
    which = f"monitor {monitor_id}" if monitor_id else "all monitors"
    content = [{
        "type": "text",
        "text": (
            f"In 2 short spoken sentences, what is on {which}? "
            f"User said: {request or 'describe'}. Be concrete, no markdown."
        ),
    }]
    for shot in shots[:2]:
        b64 = sc.encode_jpeg(shot["image"], quality=quality, max_w=max_w)
        content.append({"type": "text", "text": shot["label"]})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    model = _vision_cfg().get("model", "qwen2.5vl:7b")
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
            max_tokens=120,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"[#*_`]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 280:
            text = text[:260].rsplit(" ", 1)[0] + "."
        return text or structural_bit.replace("\n", " ")
    except Exception as exc:
        print(f"[vision] describe failed: {exc}", flush=True)
        return "Here's what I can see: " + structural_bit.replace("\n", " ")


# ---------------------------------------------------------------- primary
CHOOSER_SYSTEM = """You operate a Windows app by choosing actions on labelled UI controls.
You are given the GOAL, optional multi-monitor context, and a numbered list of controls.
Controls may be tagged M1/M2 for which monitor they are on.
Reply STRICT JSON only, one action:
{"action":"click","index":<n>,"say":"<short>"}
 or {"action":"type","index":<n>,"text":"<text>"}   (clicks control n, then types)
 or {"action":"type","text":"<text>"}                (types into the focused field)
 or {"action":"key","keys":"enter"}                  (or e.g. "ctrl s")
 or {"action":"scroll","direction":"down"}
 or {"action":"done","say":"<what was accomplished>"}
Pick the control whose label best matches the goal.
If the goal refers to something on another monitor, prefer controls tagged for that monitor.
IMPORTANT: check "Done so far" and the (current text: ...) of inputs — if the goal
is already accomplished, you MUST reply with the done action instead of repeating."""


def _choose_from_elements(goal, elements, history, screen_ctx: str = ""):
    listing = vision.elements_as_text(elements)
    msgs = [{"role": "system", "content": CHOOSER_SYSTEM}]
    if screen_ctx:
        msgs.append({"role": "system", "content": "Live screens:\n" + screen_ctx[:2500]})
    if history:
        msgs.append({"role": "system", "content": "Done so far: " + "; ".join(history)})
    msgs.append({"role": "user", "content": f"GOAL: {goal}\n\nControls on screen:\n{listing}"})
    import brain_llm
    return json.loads(brain_llm.chat_json(msgs, timeout=90))


# --------------------------------------------------------------- fallback
VLM_SYSTEM = """You control Windows by looking at screenshot(s) of the user's monitor(s).
Coordinates are ABSOLUTE on the virtual desktop (multi-monitor). Top-left of the
primary may not be (0,0) if another monitor sits to the left/above.
Each image is labelled with its monitor id and origin (left,top) plus size.
Reply STRICT JSON only, one action:
{"action":"click","x":<int>,"y":<int>,"monitor":<id>,"say":"<short>"}
 or {"action":"type","text":"<text>"}
 or {"action":"key","keys":"enter"}
 or {"action":"scroll","direction":"down"}
 or {"action":"done","say":"<done>"}
x,y must be ABSOLUTE virtual-desktop pixels (origin of that monitor + local offset),
i.e. clickable by the OS mouse. Prefer the monitor that matches the user's request."""


def _choose_from_screenshot(goal, history, screen_ctx: str = ""):
    # Prefer the foreground APP window — not a blurry whole-desktop glance.
    fg = None
    try:
        fg = sc.capture_foreground()
    except Exception:
        fg = None

    shots = []
    scale_meta = []
    max_w = int(_vision_cfg().get("act_max_width", 1280))
    quality = int(_vision_cfg().get("act_jpeg_quality", 55))

    if fg and fg.get("image") is not None:
        img = fg["image"]
        scaled = sc.downscale(img, max_w=max_w)
        sx = fg["width"] / max(1, scaled.width)
        sy = fg["height"] / max(1, scaled.height)
        # Fake monitor origin = window top-left so clicks map to absolute coords
        mon = type("M", (), {
            "id": fg.get("monitor_id", 1),
            "left": fg["left"],
            "top": fg["top"],
            "width": fg["width"],
            "height": fg["height"],
        })()
        scale_meta.append((mon, sx, sy, scaled.size))
        b64 = sc.encode_jpeg(img, quality=quality, max_w=max_w)
        content = [{
            "type": "text",
            "text": (
                f"GOAL: {goal}\n"
                f"Image is the FOREGROUND app window: {fg.get('title')}\n"
                f"Window origin left={fg['left']}, top={fg['top']}, size {fg['width']}x{fg['height']}.\n"
                f"Image is {scaled.width}x{scaled.height} (scale *{sx:.3f},*{sy:.3f}).\n"
                "Click x,y must be ABSOLUTE virtual-desktop pixels "
                "(window origin + local offset in the image).\n"
                + (f"Context:\n{screen_ctx[:1200]}\n" if screen_ctx else "")
            ),
        }, {
            "type": "text",
            "text": fg.get("label") or "Foreground",
        }, {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        }]
        msgs = [{"role": "system", "content": VLM_SYSTEM}]
        if history:
            msgs.append({"role": "system", "content": "Done so far: " + "; ".join(history)})
        msgs.append({"role": "user", "content": content})
        model = _vision_cfg().get("model", "qwen2.5vl:7b")
        resp = _get_client().chat.completions.create(
            model=model, messages=msgs, temperature=0.2,
            response_format={"type": "json_object"},
        )
        act = json.loads(resp.choices[0].message.content)
        if act.get("action") == "click":
            act = _normalize_click(act, scale_meta)
        return act

    shots = sc.capture_all_monitors()
    # Prefer sticky monitor focus when set.
    try:
        import monitor_focus
        mid = monitor_focus.get_focus()
        if mid:
            focused = [s for s in shots if s["monitor"].id == mid]
            if focused:
                shots = focused
    except Exception:
        pass
    if not shots:
        # Legacy single grab
        img = pyautogui.screenshot()
        iw, ih = img.size
        msgs = [{"role": "system", "content": VLM_SYSTEM}]
        if history:
            msgs.append({"role": "system", "content": "Done so far: " + "; ".join(history)})
        msgs.append({"role": "user", "content": [
            {"type": "text", "text": f"GOAL: {goal}\nSingle screen {iw}x{ih}. Next action?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _encode_legacy(img)}},
        ]})
        model = _vision_cfg().get("model", "qwen2.5vl:7b")
        resp = _get_client().chat.completions.create(
            model=model, messages=msgs, temperature=0.2,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    content = [{
        "type": "text",
        "text": (
            f"GOAL: {goal}\n"
            "Images below are the live monitors. Next single action?\n"
            + (f"Context:\n{screen_ctx[:1200]}\n" if screen_ctx else "")
        ),
    }]
    for shot in shots:
        mon = shot["monitor"]
        img = shot["image"]
        scaled = sc.downscale(img, max_w=max_w)
        sx = mon.width / scaled.width
        sy = mon.height / scaled.height
        scale_meta.append((mon, sx, sy, scaled.size))
        b64 = sc.encode_jpeg(img, quality=quality, max_w=max_w)
        content.append({
            "type": "text",
            "text": (
                f"{shot['label']}. Image is {scaled.width}x{scaled.height} "
                f"(scale back to screen with *{sx:.3f},*{sy:.3f}). "
                f"Absolute origin left={mon.left}, top={mon.top}."
            ),
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    msgs = [{"role": "system", "content": VLM_SYSTEM}]
    if history:
        msgs.append({"role": "system", "content": "Done so far: " + "; ".join(history)})
    msgs.append({"role": "user", "content": content})

    model = _vision_cfg().get("model", "qwen2.5vl:7b")
    resp = _get_client().chat.completions.create(
        model=model, messages=msgs, temperature=0.2,
        response_format={"type": "json_object"},
    )
    act = json.loads(resp.choices[0].message.content)

    if act.get("action") == "click":
        act = _normalize_click(act, scale_meta)
    return act


def _normalize_click(act: dict, scale_meta: list) -> dict:
    """Map model click coords to absolute virtual-desktop pixels."""
    x = int(act.get("x", 0) or 0)
    y = int(act.get("y", 0) or 0)
    mid = act.get("monitor")
    try:
        mid = int(mid) if mid is not None else None
    except Exception:
        mid = None

    # Prefer declared monitor; else guess by which image-local box fits.
    chosen = None
    for mon, sx, sy, (iw, ih) in scale_meta:
        if mid and mon.id == mid:
            chosen = (mon, sx, sy, iw, ih)
            break
    if chosen is None and scale_meta:
        # Heuristic: if coords look image-local for one monitor, use that.
        for mon, sx, sy, (iw, ih) in scale_meta:
            if 0 <= x <= iw + 20 and 0 <= y <= ih + 20:
                chosen = (mon, sx, sy, iw, ih)
                break
        if chosen is None:
            mon, sx, sy, (iw, ih) = scale_meta[0]
            chosen = (mon, sx, sy, iw, ih)

    mon, sx, sy, iw, ih = chosen
    # If already absolute (near monitor origin scale), don't double-add.
    if mon.left <= x <= mon.left + mon.width and mon.top <= y <= mon.top + mon.height:
        abs_x, abs_y = x, y
    elif 0 <= x <= iw + 5 and 0 <= y <= ih + 5:
        abs_x = int(mon.left + x * sx)
        abs_y = int(mon.top + y * sy)
    else:
        # Might be full-virtual coords already
        abs_x, abs_y = x, y

    act["x"] = abs_x
    act["y"] = abs_y
    act["monitor"] = mon.id
    return act


# ------------------------------------------------------------------- loop
def computer_use(goal: str, max_steps: int = None) -> str:
    if not is_enabled():
        return "My vision system isn't enabled yet."
    cfg = _load_config()
    if max_steps is None:
        max_steps = int(cfg.get("vision", {}).get("max_steps", 6))

    # Include VLM when the goal is visual / deictic.
    prefer_vision = bool(_NEED_VLM.search(goal or "") or _SCREEN_QA.search(goal or ""))
    screen_ctx = quick_screen_context(goal, force_vlm=prefer_vision)
    try:
        import monitor_focus
        fl = monitor_focus.status_line()
        if fl:
            screen_ctx = (fl + "\n" + (screen_ctx or "")).strip()
            goal = f"{goal} (prefer monitor {monitor_focus.get_focus()})"
    except Exception:
        pass
    history = []
    last_say = ""
    prev_act = None

    for step in range(max_steps):
        print(f"[vision] step {step + 1}/{max_steps}: capturing elements...", flush=True)
        # Foreground app first — more accurate for "this window"
        elements = vision.capture_elements(
            all_monitors=False,
            max_elements=80,
            time_budget=3.5,
        )
        if len(elements) < 5:
            elements = vision.capture_elements(
                all_monitors=True,
                max_elements=100,
                time_budget=4.0,
            )
        # Prefer sticky monitor focus when set.
        try:
            import monitor_focus as mf
            mid = mf.get_focus()
            if mid:
                filtered = [e for e in elements if e.get("monitor_id") == mid]
                if filtered:
                    elements = filtered
        except Exception:
            pass
        used_vision = False
        try:
            # VLM when UIA is thin OR user is clearly referring to visuals.
            use_shot = (not elements) or prefer_vision or len(elements) < 6
            if elements and not use_shot:
                print(f"[vision] {len(elements)} controls found, asking model...", flush=True)
                Path(__file__).with_name("_last_elements.txt").write_text(
                    vision.elements_as_text(elements), encoding="utf-8")
                act = _choose_from_elements(goal, elements, history, screen_ctx)
            else:
                print("[vision] foreground/screenshot vision...", flush=True)
                used_vision = True
                act = _choose_from_screenshot(goal, history, screen_ctx)
        except Exception as exc:
            return f"My control core had a problem: {exc}"
        print(f"[vision] action: {act}", flush=True)

        action = act.get("action")
        last_say = act.get("say") or last_say
        if action == "done":
            return last_say or "Done."
        if act == prev_act:
            return last_say or "Done."
        prev_act = act

        def click_index(i):
            if 0 <= i < len(elements):
                e = elements[i]
                pyautogui.moveTo(e["x"], e["y"], duration=0.15)
                pyautogui.click()
                return e["name"]
            return None

        if action == "click":
            if not used_vision and "index" in act:
                name = click_index(int(act["index"]))
                history.append(f"clicked '{name}'")
            else:
                pyautogui.moveTo(act.get("x", 0), act.get("y", 0), duration=0.15)
                pyautogui.click()
                history.append(
                    f"clicked ({act.get('x')},{act.get('y')}) on M{act.get('monitor', '?')}"
                )
        elif action == "type":
            target = ""
            if not used_vision and "index" in act:
                target = click_index(int(act["index"])) or ""
                time.sleep(0.2)
            _write_text(act.get("text", ""))
            history.append(f"typed '{act.get('text', '')}' into '{target or 'focused field'}'")
            print(f"[vision] typed into: {target!r}", flush=True)
        elif action == "key":
            keys = act.get("keys", "").split()
            if len(keys) == 1:
                pyautogui.press(keys[0])
            elif keys:
                pyautogui.hotkey(*keys)
            history.append(f"pressed {act.get('keys')}")
        elif action == "scroll":
            pyautogui.scroll(600 if act.get("direction") == "up" else -600)
            history.append(f"scrolled {act.get('direction')}")
        else:
            break

        time.sleep(0.8)
        # Refresh structural map between steps (cheap)
        screen_ctx = structural_glance(force=True)

    return last_say or "I did what I could see to do."
