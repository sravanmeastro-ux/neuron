"""Phase 5 perception pipeline: UIA → OCR → local Ollama VLM → ScreenContext."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from neuron.perception.screen_context import ScreenContext
from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[perceive] {msg}", flush=True)


def _vision_cfg() -> dict:
    try:
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return cfg.get("vision") or {}
    except Exception:
        return {}


def _app_and_title() -> tuple[str, str, int]:
    title = ""
    app = ""
    mon = 1
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground()
        title = (fg.get("title") or "").strip()
        if fg.get("left") is not None:
            try:
                import screen_capture as sc
                m = sc.monitor_for_point(
                    int((fg.get("left") + fg.get("right", 0)) / 2),
                    int((fg.get("top") + fg.get("bottom", 0)) / 2),
                )
                if m:
                    mon = int(getattr(m, "id", 1) or 1)
            except Exception:
                pass
    except Exception:
        pass
    try:
        import app_context
        app = (app_context.current_app() or "").strip()
    except Exception:
        pass
    if not app and title:
        # Heuristic: last segment after " - " often is app name
        parts = [p.strip() for p in title.split(" - ") if p.strip()]
        app = parts[-1][:60] if parts else title[:40]
    return app, title, mon


def _uia_elements(limit: int = 40) -> list[dict[str, Any]]:
    try:
        from neuron.uia import inspect as ui_inspect
        win, elements = ui_inspect.walk_elements(
            max_depth=5, max_elements=limit, interesting_only=True
        )
        out = []
        for e in elements[:limit]:
            out.append({
                "name": e.name,
                "control_type": e.control_type,
                "automation_id": e.automation_id,
                "center_x": e.center_x,
                "center_y": e.center_y,
                "role": e.role,
            })
        return out
    except Exception as exc:
        _log(f"UIA walk failed: {exc}")
        return []


def _local_vlm(image, request: str = "") -> str:
    """Call local Ollama vision model only — never paid cloud."""
    vcfg = _vision_cfg()
    if vcfg.get("enabled") is False:
        return ""
    try:
        import brain_llm
        if not brain_llm.is_enabled():
            return ""
    except Exception:
        return ""

    try:
        import screen_capture as sc
        max_w = int(vcfg.get("glance_max_width", 1024) or 1024)
        quality = int(vcfg.get("glance_jpeg_quality", 55) or 55)
        img = sc.downscale(image, max_w=max_w)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        llm = cfg.get("llm") or {}
        model = (vcfg.get("model") or "qwen2.5vl:7b").strip()
        from openai import OpenAI
        client = OpenAI(base_url=llm.get("base_url"), api_key=llm.get("api_key") or "ollama", timeout=60.0, max_retries=0)
        prompt = (request or "Describe what is visible on screen. Be concise.").strip()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt + " Reply in under 60 words."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            max_tokens=160,
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()[:800]
    except Exception as exc:
        _log(f"local VLM failed: {exc}")
        return ""


def build_screen_context(
    *,
    request: str = "",
    monitor: int | None = None,
    use_ocr: bool = True,
    use_vlm: bool | None = None,
    force_vlm: bool = False,
) -> ScreenContext:
    """UIA first → OCR if needed → local VLM if still insufficient."""
    ctx = ScreenContext()
    app, title, mon = _app_and_title()
    if monitor is not None:
        mon = int(monitor)
    ctx.application = app
    ctx.title = title
    ctx.monitor = mon

    # Cursor
    try:
        from neuron.perception.capture_ops import get_cursor_position
        cur = get_cursor_position({})
        if cur.success:
            ctx.cursor = {
                "x": int((cur.state or {}).get("x") or 0),
                "y": int((cur.state or {}).get("y") or 0),
            }
    except Exception:
        pass

    # 1) UI Automation
    ui = _uia_elements(40)
    if ui:
        ctx.ui_elements = ui
        ctx.sources.append("uia")
        # Promote named UIA labels into visible_text
        for e in ui:
            n = (e.get("name") or "").strip()
            if n and n not in ctx.visible_text:
                ctx.visible_text.append(n)
                if len(ctx.visible_text) >= 30:
                    break

    uia_rich = len(ctx.ui_elements) >= 4 or len(ctx.visible_text) >= 6

    # Capture image (active window preferred, else monitor)
    img = None
    path = ""
    try:
        from neuron.perception import capture_ops
        if monitor is not None:
            cap = capture_ops.capture_monitor({"monitor": monitor})
        else:
            cap = capture_ops.get_active_window_screenshot({})
            if not cap.success:
                cap = capture_ops.capture_monitor({"monitor": mon})
        if cap.success:
            path = (cap.state or {}).get("path") or ""
            ctx.screenshot_path = path
            ctx.bounds = (cap.state or {}).get("bounds") or {}
            if (cap.state or {}).get("title") and not ctx.title:
                ctx.title = cap.state["title"]
            ctx.sources.append("capture")
            if path:
                from PIL import Image
                img = Image.open(path)
    except Exception as exc:
        _log(f"capture failed: {exc}")

    # 2) OCR when UIA is sparse or user asks about text
    need_ocr = use_ocr and (
        not uia_rich
        or force_vlm
        or bool(request and any(w in request.lower() for w in ("text", "read", "say", "written", "ocr")))
    )
    if need_ocr and path:
        try:
            from neuron.perception.ocr import ocr_image
            ocr = ocr_image({"path": path})
            if ocr.success:
                texts = (ocr.state or {}).get("visible_text") or (ocr.state or {}).get("text") or []
                for t in texts:
                    if t and t not in ctx.visible_text:
                        ctx.visible_text.append(t)
                if texts:
                    ctx.sources.append("ocr")
        except Exception as exc:
            _log(f"ocr failed: {exc}")

    still_sparse = len(ctx.visible_text) < 3 and len(ctx.ui_elements) < 3

    # 3) Local VLM only if still insufficient / forced / descriptive request
    vcfg = _vision_cfg()
    auto_vlm = bool(vcfg.get("glance_vlm_auto"))
    if use_vlm is None:
        use_vlm = force_vlm or auto_vlm or still_sparse or bool(
            request and any(
                w in request.lower()
                for w in ("describe", "what is on", "what's on", "look at", "see", "how many", "vision")
            )
        )
    if use_vlm and img is not None:
        desc = _local_vlm(img, request or f"Describe the active window: {ctx.title}")
        if desc:
            ctx.vision_description = desc
            ctx.sources.append("vlm")

    if not ctx.sources:
        ctx.error = "No perception sources available."
    return ctx


def analyze_screen(args: dict | None = None) -> ToolResult:
    args = args or {}
    request = (args.get("request") or args.get("goal") or args.get("query") or "what is on screen").strip()
    monitor = args.get("monitor") or args.get("monitor_id")
    force_vlm = bool(args.get("force_vlm") or args.get("vision"))
    try:
        ctx = build_screen_context(
            request=request,
            monitor=int(monitor) if monitor not in (None, "") else None,
            use_ocr=bool(args.get("use_ocr", True)),
            force_vlm=force_vlm,
        )
        # Prefer spoken answer: vision desc, else compact
        say = ctx.vision_description or ctx.compact(900)
        if ctx.error and not say:
            return fail(ctx.error, state=ctx.to_dict(), method="+".join(ctx.sources) or "none")
        return ok(
            say,
            state=ctx.to_dict(),
            method="+".join(ctx.sources) or "perceive",
        )
    except Exception as exc:
        # Fall back to existing vision_agent
        try:
            import vision_agent
            if vision_agent.is_enabled():
                msg = vision_agent.answer_screen(request)
                return ok(str(msg), state={"fallback": "vision_agent"}, method="vision_agent")
        except Exception:
            pass
        return fail(str(exc))


def get_screen_context(args: dict | None = None) -> ToolResult:
    """Return structured ScreenContext without requiring a spoken question."""
    args = args or {}
    ctx = build_screen_context(
        request=args.get("request") or "",
        monitor=int(args["monitor"]) if args.get("monitor") not in (None, "") else None,
        use_ocr=bool(args.get("use_ocr", True)),
        force_vlm=bool(args.get("force_vlm")),
        use_vlm=args.get("use_vlm"),
    )
    return ok(ctx.compact(), state=ctx.to_dict(), method="+".join(ctx.sources) or "perceive")
