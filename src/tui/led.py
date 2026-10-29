
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.tui.strings import t

INNER_STATES = (
    "working", "waiting-permission", "waiting-input", "notice", "idle", "done", "dead", "disconnected", "limit",
    "unknown",
)
OUTER_STATES = ("active", "steady", "unread", "off", "dim")

HUE = {
    "working": "green", "waiting-permission": "yellow", "waiting-input": "yellow", "notice": "light-blue",
    "idle": "gray", "done": "green", "dead": "dark-gray", "disconnected": "red", "limit": "red", "unknown": "gray",
}
HUE_STYLE = {
    "green": "ansi_green", "yellow": "ansi_yellow", "light-blue": "ansi_bright_blue", "gray": "ansi_white",
    "dark-gray": "ansi_bright_black", "red": "ansi_red",
}
DOT = {
    "working": ("●", "@"), "waiting-permission": ("▲", "!"), "waiting-input": ("▲", "!"), "notice": ("◆", "*"),
    "idle": ("●", "o"), "done": ("○", "O"), "dead": ("✕", "x"), "disconnected": ("⊘", "-"), "limit": ("☠", "%"),
    "unknown": ("○", "?"),
}
RING = {
    "active": (("‹", "›"), ("<", ">")), "steady": (("(", ")"), ("(", ")")), "unread": (("[", "]"), ("[", "]")),
    "off": ((" ", " "), (" ", " ")), "dim": ((" ", " "), (" ", " ")),
}
_STATUS_KEY = {"working_subagent": "session.status.working_subagent", "running": "session.status.working"}
_INNER_KEY = {
    "waiting-permission": "session.status.question", "waiting-input": "tui.led.awaiting_startup",
    "notice": "session.status.notice", "working": "session.status.working", "done": "session.status.finished_unread",
    "idle": "session.status.idle", "dead": "session.status.dead", "disconnected": "tui.led.disconnected",
    "limit": "session.status.usage_limit", "unknown": "session.status.unknown",
}


@dataclass(frozen=True)
class Led:

    inner: str
    outer: str
    hue: str
    label: str
    source: Optional[str]

    def glyph(self, ascii_only: bool = False) -> str:
        i = 1 if ascii_only else 0
        left, right = RING[self.outer][i]
        return f"{left}{DOT[self.inner][i]}{right}"

    @property
    def style(self) -> str:
        return HUE_STYLE[self.hue]


def host_offline(row: Mapping[str, Any]) -> Optional[str]:
    key = row.get("host_key")
    if not key or key == "local":
        return None
    return None if (row.get("host_state") or "up") == "up" else (row.get("host_label") or key)


def led_states(
    status: Optional[str], *, unread: bool = False, startup_gate: Optional[str] = None,
    transport: Optional[str] = None, host_offline_label: Optional[str] = None, usage_limit: bool = False,
) -> tuple[str, str]:
    if transport == "disconnected" or host_offline_label:
        return "disconnected", "off"
    if status in ("dead", "stopped"):
        return "dead", "off"
    if usage_limit:
        return "limit", "off"
    if startup_gate == "awaiting_startup_prompt":
        return "waiting-input", "active"
    if status == "question":
        return "waiting-permission", "active"
    if status == "notice":
        return "notice", "active"
    if status in ("working", "working_subagent", "running"):
        return "working", "active"
    if status == "finished_unread" or (status == "idle" and unread):
        return "done", "unread"
    if status == "idle":
        return "idle", "steady"
    return "unknown", "dim"


def led_for(row: Mapping[str, Any], *, transport: Optional[str] = None) -> Led:
    status = row.get("activity_status")
    offline = host_offline(row)
    inner, outer = led_states(
        status, unread=bool(row.get("unread")), startup_gate=row.get("startup_gate"),
        transport=transport, host_offline_label=offline,
        usage_limit=bool(row.get("usage_limit")),
    )
    if offline:
        label = t("session.status.host_offline").replace("{host}", offline)
    elif inner == "working" and status in _STATUS_KEY:
        label = t(_STATUS_KEY[status])
    else:
        label = t(_INNER_KEY[inner])
    return Led(inner, outer, HUE[inner], label, row.get("status_source"))


def use_ascii() -> bool:
    return not (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "").startswith("utf")
