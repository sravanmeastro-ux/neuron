"""Walk and snapshot the Windows UI Automation tree."""

from __future__ import annotations

import time
from typing import Any

from neuron.uia.types import ElementInfo


def _log(msg: str) -> None:
    print(f"[uia-inspect] {msg}", flush=True)


def _safe(ctrl, attr: str, default=""):
    try:
        v = getattr(ctrl, attr, default)
        return v if v is not None else default
    except Exception:
        return default


def _rect(ctrl) -> tuple[int, int, int, int, int, int, int, int]:
    try:
        r = ctrl.BoundingRectangle
        left = int(getattr(r, "left", 0) or 0)
        top = int(getattr(r, "top", 0) or 0)
        right = int(getattr(r, "right", 0) or 0)
        bottom = int(getattr(r, "bottom", 0) or 0)
        w = max(0, right - left)
        h = max(0, bottom - top)
        cx = left + w // 2
        cy = top + h // 2
        return left, top, right, bottom, w, h, cx, cy
    except Exception:
        return 0, 0, 0, 0, 0, 0, 0, 0


def _value(ctrl) -> str:
    try:
        pat = ctrl.GetValuePattern()
        if pat:
            return (pat.Value or "").strip()[:200]
    except Exception:
        pass
    try:
        return (_safe(ctrl, "Name") or "")[:200]
    except Exception:
        return ""


def _is_offscreen(ctrl) -> bool:
    try:
        return bool(ctrl.IsOffscreen)
    except Exception:
        return False


def _is_enabled(ctrl) -> bool:
    try:
        return bool(ctrl.IsEnabled)
    except Exception:
        return True


def foreground_root():
    from neuron.windows.com import com_uia
    import uiautomation as auto
    with com_uia():
        return auto.GetForegroundControl()


def snapshot_control(ctrl, *, depth: int = 0, path: str = "") -> ElementInfo | None:
    try:
        name = (_safe(ctrl, "Name") or "").strip()
        ctype = (_safe(ctrl, "ControlTypeName") or "").strip()
        left, top, right, bottom, w, h, cx, cy = _rect(ctrl)
        aid = (_safe(ctrl, "AutomationId") or "").strip()
        cls = (_safe(ctrl, "ClassName") or "").strip()
        help_text = (_safe(ctrl, "HelpText") or "").strip()[:120]
        hwnd = int(_safe(ctrl, "NativeWindowHandle", 0) or 0)
        return ElementInfo(
            name=name[:120],
            control_type=ctype,
            automation_id=aid[:80],
            class_name=cls[:80],
            value=_value(ctrl),
            help_text=help_text,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            width=w,
            height=h,
            center_x=cx,
            center_y=cy,
            depth=depth,
            path=path[:200],
            enabled=_is_enabled(ctrl),
            offscreen=_is_offscreen(ctrl),
            hwnd=hwnd,
        )
    except Exception:
        return None


def walk_elements(
    root=None,
    *,
    max_depth: int = 6,
    max_elements: int = 120,
    node_budget: int = 2500,
    time_budget: float = 4.0,
    named_only: bool = False,
    interesting_only: bool = False,
) -> tuple[ElementInfo | None, list[ElementInfo]]:
    """Return (window_info, elements) for the foreground app (or given root)."""
    from neuron.windows.com import com_uia
    import uiautomation as auto

    interesting = {
        "ButtonControl", "SplitButtonControl", "HyperlinkControl",
        "EditControl", "DocumentControl", "TextControl",
        "MenuItemControl", "MenuControl", "MenuBarControl",
        "TabItemControl", "TabControl",
        "ListItemControl", "ListControl",
        "CheckBoxControl", "RadioButtonControl",
        "TreeItemControl", "TreeControl",
        "ComboBoxControl", "WindowControl", "PaneControl",
        "ToolBarControl", "DataItemControl",
    }

    with com_uia():
        if root is None:
            root = auto.GetForegroundControl()
        if not root:
            return None, []

        win = snapshot_control(root, depth=0, path="")
        out: list[ElementInfo] = []
        seen: set[tuple] = set()
        start = time.time()
        visited = 0
        # DFS stack: (ctrl, depth, path)
        stack: list[tuple[Any, int, str]] = [(root, 0, "")]

        while stack and visited < node_budget and len(out) < max_elements:
            if time.time() - start > time_budget:
                break
            ctrl, depth, path = stack.pop()
            visited += 1
            if depth > max_depth:
                continue

            info = snapshot_control(ctrl, depth=depth, path=path)
            if info and depth > 0:
                ctype = info.control_type
                include = True
                if interesting_only and ctype not in interesting and not info.name:
                    include = False
                if named_only and not info.name and not info.automation_id:
                    include = False
                if info.width <= 1 and info.height <= 1 and not info.name and not info.automation_id:
                    include = False
                if include:
                    key = (
                        info.name[:40],
                        info.control_type,
                        info.automation_id,
                        info.center_x // 8,
                        info.center_y // 8,
                    )
                    if key not in seen:
                        seen.add(key)
                        out.append(info)

            try:
                children = ctrl.GetChildren()
            except Exception:
                children = []
            # Push children in reverse so left-to-right order is preserved roughly
            child_path = path
            if info and info.name:
                child_path = (path + "/" + info.name) if path else info.name
            for ch in reversed(list(children)[:80]):
                stack.append((ch, depth + 1, child_path[:200]))

        _log(f"walked visited={visited} elements={len(out)} window={(win.name if win else '')[:40]}")
        return win, out


def format_tree(win: ElementInfo | None, elements: list[ElementInfo], limit: int = 50) -> str:
    lines = []
    if win:
        lines.append(f"WINDOW: {win.name[:80]} [{win.control_type}]")
    for el in elements[:limit]:
        indent = "  " * min(el.depth, 6)
        bits = [f"{el.control_type or '?'}: {el.name[:50] or '(unnamed)'}"]
        if el.automation_id:
            bits.append(f"id={el.automation_id[:30]}")
        bits.append(f"@{el.center_x},{el.center_y}")
        lines.append(f"{indent}{' '.join(bits)}")
    if not lines:
        return "Empty UI tree."
    return "\n".join(lines)
