"""Screen perception for N.E.U.R.O.N.

Uses Windows UI Automation to 'see' the interactive controls on screen
(buttons, links, video tiles, text boxes...) with their exact positions,
so the assistant can click the right thing instead of guessing pixels.
"""

import time

import uiautomation as auto

CLICKABLE_TYPES = {
    auto.ControlType.ButtonControl,
    auto.ControlType.HyperlinkControl,
    auto.ControlType.ListItemControl,
    auto.ControlType.MenuItemControl,
    auto.ControlType.TabItemControl,
    auto.ControlType.CheckBoxControl,
    auto.ControlType.RadioButtonControl,
    auto.ControlType.TreeItemControl,
    auto.ControlType.SplitButtonControl,
}
TEXT_TYPES = {
    auto.ControlType.EditControl,
    auto.ControlType.ComboBoxControl,
    auto.ControlType.DocumentControl,
}


def _screen_size():
    return auto.GetScreenSize()


def _virtual_bounds():
    """Virtual desktop bounds (supports multi-monitor negative coords)."""
    try:
        import screen_capture as sc
        left, top, width, height = sc.virtual_desktop_bounds()
        return left, top, left + width, top + height
    except Exception:
        sw, sh = _screen_size()
        return 0, 0, sw, sh


def _walk_controls(root, out, seen, start, max_elements, node_budget, time_budget,
                   vx0, vy0, vx1, vy1):
    stack = [(root, 0)]
    visited = 0
    while stack and visited < node_budget and len(out) < max_elements:
        if time.time() - start > time_budget:
            break
        ctrl, depth = stack.pop()
        visited += 1
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for ch in children:
            stack.append((ch, depth + 1))

        try:
            ctype = ctrl.ControlType
            name = (ctrl.Name or "").strip()
            rect = ctrl.BoundingRectangle
        except Exception:
            continue

        clickable = ctype in CLICKABLE_TYPES
        editable = ctype in TEXT_TYPES
        if not (clickable or editable):
            continue
        if not name and not editable:
            continue

        w, h = rect.width(), rect.height()
        if w <= 1 or h <= 1:
            continue
        cx, cy = rect.xcenter(), rect.ycenter()
        # Must be somewhere on the virtual desktop (any monitor)
        if cx < vx0 or cy < vy0 or cx > vx1 or cy > vy1:
            continue

        key = (name[:60], cx // 5, cy // 5)
        if key in seen:
            continue
        seen.add(key)

        value = ""
        if editable:
            try:
                value = (ctrl.GetValuePattern().Value or "").strip()
            except Exception:
                pass

        mon_id = 1
        try:
            import screen_capture as sc
            mon = sc.monitor_for_point(cx, cy)
            if mon:
                mon_id = mon.id
        except Exception:
            pass

        out.append({
            "index": len(out),
            "name": name[:80],
            "role": ctrl.ControlTypeName.replace("Control", ""),
            "x": cx,
            "y": cy,
            "w": w,
            "h": h,
            "clickable": clickable,
            "editable": editable,
            "value": value[:120],
            "monitor_id": mon_id,
        })


def capture_elements(max_elements=70, node_budget=2500, time_budget=5.0,
                     all_monitors: bool = False):
    """Return visible interactable elements.

    Default: foreground window (fast).
    all_monitors=True: also scan other top-level windows across displays.
    Each item: {index, name, role, x, y, w, h, clickable, editable, monitor_id}
    """
    out = []
    seen = set()
    start = time.time()
    vx0, vy0, vx1, vy1 = _virtual_bounds()

    try:
        root = auto.GetForegroundControl()
    except Exception:
        root = None
    if root:
        _walk_controls(
            root, out, seen, start, max_elements, node_budget, time_budget,
            vx0, vy0, vx1, vy1,
        )

    if all_monitors and len(out) < max_elements and time.time() - start < time_budget:
        try:
            desktop = auto.GetRootControl()
            tops = desktop.GetChildren() if desktop else []
        except Exception:
            tops = []
        # Prefer larger windows; skip NEURON itself.
        for win in tops:
            if time.time() - start > time_budget or len(out) >= max_elements:
                break
            try:
                name = (win.Name or "").strip()
                if name.startswith("N.E.U.R.O.N"):
                    continue
                rect = win.BoundingRectangle
                if rect.width() < 120 or rect.height() < 120:
                    continue
            except Exception:
                continue
            _walk_controls(
                win, out, seen, start, max_elements,
                max(400, node_budget // 4), time_budget,
                vx0, vy0, vx1, vy1,
            )

    # Re-index after multi-window merge
    for i, e in enumerate(out):
        e["index"] = i
    return out


def elements_as_text(elements):
    """Compact numbered list for the language model."""
    lines = []
    for e in elements:
        tag = "input" if e["editable"] else e["role"].lower()
        mon = e.get("monitor_id")
        mon_bit = f" M{mon}" if mon else ""
        line = f'[{e["index"]}]{mon_bit} {tag}: "{e["name"]}"'
        if e.get("value"):
            line += f' (current text: "{e["value"]}")'
        lines.append(line)
    return "\n".join(lines) if lines else "(no readable elements found)"
