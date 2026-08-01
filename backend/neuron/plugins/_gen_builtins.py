"""Generate builtin example plugins (one-shot)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "builtin"
ROOT.mkdir(parents=True, exist_ok=True)

PLUGINS = {
    "chrome": {
        "name": "Chrome",
        "description": "Google Chrome browser plugin",
        "app": "Chrome",
        "actions": [
            ("chrome.open", "Open Google Chrome", "open"),
            ("chrome.new_tab", "Open a URL in Chrome", "new_tab", {"url": "str"}),
            ("chrome.focus", "Focus Chrome", "focus"),
        ],
        "intents": [("chrome.open", ["open chrome", "launch chrome"], ["chrome.open"])],
    },
    "blender": {
        "name": "Blender",
        "description": "Blender 3D plugin",
        "app": "Blender",
        "actions": [
            ("blender.open", "Open Blender", "open"),
            ("blender.download_page", "Open Blender download page", "download_page"),
            ("blender.focus", "Focus Blender", "focus"),
        ],
        "intents": [("blender.open", ["open blender"], ["blender.open"])],
    },
    "photoshop": {
        "name": "Photoshop",
        "description": "Adobe Photoshop plugin",
        "app": "Photoshop",
        "actions": [
            ("photoshop.open", "Open Photoshop", "open"),
            ("photoshop.focus", "Focus Photoshop", "focus"),
        ],
        "intents": [("photoshop.open", ["open photoshop"], ["photoshop.open"])],
    },
    "discord": {
        "name": "Discord",
        "description": "Discord chat plugin",
        "app": "Discord",
        "actions": [
            ("discord.open", "Open Discord", "open"),
            ("discord.focus", "Focus Discord", "focus"),
        ],
        "intents": [("discord.open", ["open discord"], ["discord.open"])],
    },
    "steam": {
        "name": "Steam",
        "description": "Steam gaming plugin",
        "app": "Steam",
        "actions": [
            ("steam.open", "Open Steam", "open"),
            ("steam.focus", "Focus Steam", "focus"),
        ],
        "intents": [("steam.open", ["open steam"], ["steam.open"])],
    },
    "obs": {
        "name": "OBS Studio",
        "description": "OBS Studio streaming plugin",
        "app": "OBS Studio",
        "actions": [
            ("obs.open", "Open OBS Studio", "open"),
            ("obs.focus", "Focus OBS", "focus"),
        ],
        "intents": [("obs.open", ["open obs", "open obs studio"], ["obs.open"])],
    },
    "spotify": {
        "name": "Spotify",
        "description": "Spotify music plugin",
        "app": "Spotify",
        "actions": [
            ("spotify.open", "Open Spotify", "open"),
            ("spotify.focus", "Focus Spotify", "focus"),
        ],
        "intents": [("spotify.open", ["open spotify"], ["spotify.open"])],
    },
    "office": {
        "name": "Microsoft Office",
        "description": "Office suite plugin (Word/Excel/PowerPoint)",
        "app": "WINWORD",
        "actions": [
            ("office.word", "Open Microsoft Word", "word"),
            ("office.excel", "Open Microsoft Excel", "excel"),
            ("office.powerpoint", "Open PowerPoint", "powerpoint"),
        ],
        "intents": [("office.word", ["open word"], ["office.word"])],
    },
    "vscode": {
        "name": "VS Code",
        "description": "Visual Studio Code plugin",
        "app": "Code",
        "actions": [
            ("vscode.open", "Open Visual Studio Code", "open"),
            ("vscode.focus", "Focus VS Code", "focus"),
        ],
        "intents": [("vscode.open", ["open vscode", "open code"], ["vscode.open"])],
    },
    "cursor": {
        "name": "Cursor",
        "description": "Cursor IDE plugin",
        "app": "Cursor",
        "actions": [
            ("cursor.open", "Open Cursor IDE", "open"),
            ("cursor.focus", "Focus Cursor", "focus"),
        ],
        "intents": [("cursor.open", ["open cursor"], ["cursor.open"])],
    },
}


def _actions_py(pid: str, meta: dict) -> str:
    lines = [f'"""Builtin plugin actions: {meta["name"]}."""', ""]
    app = meta["app"]
    for act in meta["actions"]:
        name, _desc, handler = act[0], act[1], act[2]
        if handler == "open":
            lines.append(
                f"def open(args=None):\n"
                f"    from neuron.plugins._util import open_app\n"
                f"    return open_app({app!r})\n"
            )
        elif handler == "focus":
            lines.append(
                f"def focus(args=None):\n"
                f"    from neuron.plugins._util import focus\n"
                f"    return focus({app!r})\n"
            )
        elif handler == "new_tab":
            lines.append(
                "def new_tab(args=None):\n"
                "    args = args or {}\n"
                "    url = str(args.get('url') or 'https://www.google.com')\n"
                "    from neuron.plugins._util import open_app, open_website\n"
                "    open_app('Chrome')\n"
                "    return open_website(url)\n"
            )
        elif handler == "download_page":
            lines.append(
                "def download_page(args=None):\n"
                "    from neuron.plugins._util import open_website\n"
                "    return open_website('https://www.blender.org/download/')\n"
            )
        elif handler == "word":
            lines.append(
                "def word(args=None):\n"
                "    from neuron.plugins._util import open_app\n"
                "    return open_app('WINWORD')\n"
            )
        elif handler == "excel":
            lines.append(
                "def excel(args=None):\n"
                "    from neuron.plugins._util import open_app\n"
                "    return open_app('EXCEL')\n"
            )
        elif handler == "powerpoint":
            lines.append(
                "def powerpoint(args=None):\n"
                "    from neuron.plugins._util import open_app\n"
                "    return open_app('POWERPNT')\n"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    for pid, meta in PLUGINS.items():
        d = ROOT / pid
        d.mkdir(parents=True, exist_ok=True)
        actions = []
        for act in meta["actions"]:
            name, desc, handler = act[0], act[1], act[2]
            args_schema = act[3] if len(act) > 3 else {}
            actions.append(
                {
                    "name": name,
                    "description": desc,
                    "handler": f"actions:{handler}",
                    "args_schema": args_schema,
                    "risk": "safe",
                    "control_methods": ["api"],
                }
            )
        manifest = {
            "id": pid,
            "version": "1.0.0",
            "name": meta["name"],
            "description": meta["description"],
            "docs": "README.md",
            "author": "NEURON",
            "permissions": {
                "risk_ceiling": "confirm",
                "control_methods": ["api", "uia"],
                "planner_visible": True,
                "allow_shell": False,
            },
            "config": {"schema": {}, "defaults": {"app": meta.get("app", "")}},
            "dependencies": {
                "neuron": ">=4.0",
                "tools": ["open_app"],
                "python": [],
                "plugins": [],
            },
            "intents": [
                {"id": i[0], "aliases": i[1], "prefer": i[2]} for i in meta["intents"]
            ],
            "actions": actions,
        }
        (d / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (d / "actions.py").write_text(_actions_py(pid, meta), encoding="utf-8")
        readme = [
            f"# {meta['name']} Plugin",
            "",
            meta["description"],
            "",
            "Version 1.0.0",
            "",
            "## Actions",
            "",
        ]
        for a in actions:
            readme.append(f"- `{a['name']}` — {a['description']}")
        readme.append("")
        (d / "README.md").write_text("\n".join(readme), encoding="utf-8")
        print("wrote", pid)


if __name__ == "__main__":
    main()
