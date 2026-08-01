"""Variable substitution and condition/loop expression eval (safe subset)."""

from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def substitute(value: Any, variables: dict[str, Any]) -> Any:
    """Replace {{name}} in strings; recurse into dict/list."""
    if isinstance(value, str):
        def _repl(m: re.Match) -> str:
            key = m.group(1)
            if key in variables:
                return str(variables[key])
            return m.group(0)

        return _VAR_RE.sub(_repl, value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def eval_condition(expr: Any, variables: dict[str, Any]) -> bool:
    """
    Safe conditions:
      true/false
      {{var}} / bare var name (truthy)
      {{a}} == value | != | > | < | >= | <=
      empty / not empty for {{var}}
    """
    if expr is True or expr is False:
        return bool(expr)
    if expr is None:
        return False
    text = str(substitute(expr, variables)).strip()
    if not text:
        return False
    low = text.lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False

    # empty / not empty
    m = re.match(r"(?:not\s+)?empty\s*\(?\s*\{\{?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}?\}\s*\)?", low)
    if m:
        val = variables.get(m.group(1))
        empty = val is None or val == "" or val == [] or val == {}
        return (not empty) if low.startswith("not") else empty

    # comparisons
    m = re.match(
        r"(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$",
        text,
    )
    if m:
        left = m.group(1).strip().strip("'\"")
        op = m.group(2)
        right = m.group(3).strip().strip("'\"")
        # resolve bare var on left
        if left in variables:
            left_v: Any = variables[left]
        else:
            left_v = left
        try:
            lf = float(left_v)
            rf = float(right)
            left_v, right_v = lf, rf
        except Exception:
            left_v, right_v = str(left_v), str(right)
        if op == "==":
            return left_v == right_v
        if op == "!=":
            return left_v != right_v
        if op == ">":
            return left_v > right_v  # type: ignore[operator]
        if op == "<":
            return left_v < right_v  # type: ignore[operator]
        if op == ">=":
            return left_v >= right_v  # type: ignore[operator]
        if op == "<=":
            return left_v <= right_v  # type: ignore[operator]

    # bare {{var}} already substituted — truthy string
    if text in variables:
        return bool(variables[text])
    return bool(text)


def loop_count(args: dict[str, Any], variables: dict[str, Any]) -> int:
    """Resolve loop iterations from count / times / {{n}}."""
    raw = args.get("count", args.get("times", 1))
    raw = substitute(raw, variables)
    try:
        n = int(float(raw))
    except Exception:
        n = 1
    return max(0, min(n, int(args.get("max") or 100)))
