"""Developer SDK — scaffold a new plugin package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neuron.plugin_market.api import api_docs, HOST_API_VERSION
from neuron.plugin_market.paths import scaffold_root


_TEMPLATE_ACTIONS = '''\
"""Actions for {plugin_id} plugin."""

from __future__ import annotations


def hello(args: dict | None = None):
    from neuron.windows.result import ok
    name = (args or {{}}).get("name") or "world"
    return ok(f"Hello {{name}} from {plugin_id}!", state={{"plugin": "{plugin_id}"}})


def default(args: dict | None = None):
    return hello(args)
'''

_TEMPLATE_README = """# {name}

{description}

## Host API

```
{api_docs}
```

## Develop

1. Edit `actions.py` and `plugin.json`
2. Enable hot reload: ask NEURON to "start plugin hot reload"
3. Or run `plugin_reload` with id `{plugin_id}`

## Install

```
Install plugin from folder: {root}
```
"""


def scaffold(
    plugin_id: str,
    *,
    name: str = "",
    description: str = "",
    author: str = "developer",
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    pid = (plugin_id or "").strip().lower().replace(" ", "-")
    if not pid or not pid[0].isalpha():
        return {"ok": False, "error": "plugin_id must start with a letter (a-z0-9_.-)"}
    root = Path(out_dir).expanduser().resolve() if out_dir else (scaffold_root() / pid)
    root.mkdir(parents=True, exist_ok=True)
    display = name or pid.replace("-", " ").title()
    desc = description or f"{display} plugin for NEURON"
    manifest = {
        "id": pid,
        "version": "0.1.0",
        "name": display,
        "description": desc,
        "author": author,
        "api_version": "1",
        "docs": "README.md",
        "homepage": "",
        "permissions": {
            "risk_ceiling": "confirm",
            "control_methods": ["api"],
            "planner_visible": True,
            "allow_shell": False,
        },
        "config": {"schema": {}, "defaults": {}},
        "dependencies": {
            "neuron": ">=4.0",
            "tools": [],
            "python": [],
            "plugins": [],
        },
        "intents": [
            {
                "id": f"{pid}.hello",
                "aliases": [f"{pid} hello", f"hello {pid}"],
                "prefer": [f"{pid}.hello"],
            }
        ],
        "actions": [
            {
                "name": f"{pid}.hello",
                "description": f"Hello from {display}",
                "args_schema": {"name": "str"},
                "risk": "safe",
                "handler": "actions:hello",
                "aliases": [],
                "control_methods": ["api"],
            }
        ],
    }
    (root / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "actions.py").write_text(
        _TEMPLATE_ACTIONS.format(plugin_id=pid),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        _TEMPLATE_README.format(
            name=display,
            description=desc,
            api_docs=api_docs(),
            plugin_id=pid,
            root=str(root),
        ),
        encoding="utf-8",
    )
    (root / "SDK.md").write_text(
        f"# Developer SDK notes\n\nHost API {HOST_API_VERSION}\n\n{api_docs()}\n",
        encoding="utf-8",
    )
    return {"ok": True, "path": str(root), "manifest": manifest}
