"""Discord skill workflows."""

from __future__ import annotations

import os
import time

from neuron.skills._util import arg, as_result, handler
from neuron.skills import windows as win_skill
from neuron.windows.result import ToolResult, fail, ok


_SECTION_URIS = {
    "friends": "discord://-/channels/@me",
    "dms": "discord://-/channels/@me",
    "me": "discord://-/channels/@me",
    "activity": "discord://-/activity",
    "library": "discord://-/library",
}


def open() -> ToolResult:
    return win_skill.open_app("discord")


def friends() -> ToolResult:
    try:
        import actions
        return as_result(actions.discord_friends(), method="discord")
    except Exception as exc:
        return fail(str(exc))


def open_channel(channel: str = "friends", guild_id: str = "", channel_id: str = "") -> ToolResult:
    """Open Friends/DMs or a specific guild/channel via Discord deep link.

    channel: friends|dms|me|activity|library OR free text (best-effort friends)
    guild_id + channel_id: discord://-/channels/{guild}/{channel}
    """
    g = (guild_id or "").strip()
    c = (channel_id or "").strip()
    key = (channel or "friends").strip().lower()
    if g and c:
        uri = f"discord://-/channels/{g}/{c}"
    else:
        uri = _SECTION_URIS.get(key) or _SECTION_URIS["friends"]

    r = open()
    time.sleep(0.8)
    try:
        os.startfile(uri)
    except Exception as exc:
        if key in ("friends", "dms", "me") or not (g and c):
            return friends()
        return fail(f"Discord deep link failed: {exc}")
    time.sleep(0.5)
    win_skill.focus_app("discord")
    label = channel or (f"{g}/{c}" if g else "channel")
    return ok(f"Opened Discord {label}.", method="discord", state={"uri": uri})


open_tool = handler(lambda a: open())
friends_tool = handler(lambda a: friends())
open_channel_tool = handler(
    lambda a: open_channel(
        str(arg(a, "channel", "name", "section", default="friends")),
        str(arg(a, "guild_id", "guild", "server_id", default="")),
        str(arg(a, "channel_id", "id", default="")),
    )
)
