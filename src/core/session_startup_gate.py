
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Pattern, Union



GATE_READY: str = "ready"

GATE_AWAITING: str = "awaiting_startup_prompt"

GATE_UNKNOWN: str = "unknown"

ALL_STARTUP_GATES: tuple[str, ...] = (GATE_READY, GATE_AWAITING, GATE_UNKNOWN)


STARTUP_HOOK_GRACE_SECONDS: int = 20

STARTUP_TAIL_LINES: int = 200

STARTUP_TAIL_RECHECK_SECONDS: int = 30



Marker = Union[str, Pattern[str]]

SCREEN_TRUST: str = "trust"
SCREEN_OAUTH: str = "oauth_login"
SCREEN_CODEX_TRUST: str = "codex_trust"
SCREEN_EXTERNAL_IMPORTS: str = "external_imports"
SCREEN_MCP_SERVER: str = "mcp_server"
SCREEN_BYPASS_PERMISSIONS: str = "bypass_permissions"
SCREEN_RESUME_PICKER: str = "resume_picker"
SCREEN_ONBOARDING_THEME: str = "onboarding_theme"
SCREEN_LOGIN_METHOD: str = "login_method"
SCREEN_DEV_CHANNELS: str = "dev_channels"
SCREEN_CHROME: str = "chrome_extension"
SCREEN_UNRECOGNIZED: str = "unrecognized"

SHARED_FOOTER_MARKER: str = "Enter to confirm · Esc to cancel"

STARTUP_SCREEN_MARKERS: tuple[tuple[str, Marker], ...] = (
    (SCREEN_TRUST, "Quick safety check: Is this a project you created or one you trust?"),
    (SCREEN_TRUST, "Claude Code'll be able to read, edit, and execute files here."),
    (SCREEN_TRUST, re.compile(r"Yes, I trust this folder", re.M)),
    (SCREEN_OAUTH, re.compile(r"claude\.com/cai/oauth/authorize")),
    (SCREEN_CODEX_TRUST, "Do you trust the contents of this directory?"),
    (SCREEN_EXTERNAL_IMPORTS, re.compile(r"Allow\s+external\s+CLAUDE\.md\s+file\s+imports\?")),
    (SCREEN_EXTERNAL_IMPORTS, re.compile(r"Yes,\s+allow\s+external\s+imports")),
    (SCREEN_MCP_SERVER, re.compile(r"New\s+MCP\s+server\s+found\s+in\s+this\s+project")),
    (SCREEN_MCP_SERVER, re.compile(r"Continue\s+without\s+using\s+this\s+MCP\s+server")),
    (SCREEN_BYPASS_PERMISSIONS, re.compile(r"WARNING:\s+Claude\s+Code\s+running\s+in\s+Bypass\s+Permissions\s+mode")),
    (SCREEN_RESUME_PICKER, re.compile(r"Ctrl\+A\s+to\s+show\s+all\s+projects")),
    (SCREEN_ONBOARDING_THEME, re.compile(r"Choose\s+the\s+text\s+style\s+that\s+looks\s+best\s+with\s+your\s+terminal")),
    (SCREEN_LOGIN_METHOD, re.compile(r"Select\s+login\s+method:")),
    (SCREEN_DEV_CHANNELS, re.compile(r"WARNING:\s+Loading\s+development\s+channels")),
    (SCREEN_CHROME, re.compile(r"Claude\s+in\s+Chrome\s+extension\s+detected")),
    (SCREEN_TRUST, SHARED_FOOTER_MARKER),
)

STARTUP_PROMPT_MARKERS: tuple[Marker, ...] = tuple(marker for _, marker in STARTUP_SCREEN_MARKERS)


def _marker_hits(marker: Marker, text: str) -> bool:
    if isinstance(marker, str):
        return marker in text
    return marker.search(text) is not None


def startup_screen_kind(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for kind, marker in STARTUP_SCREEN_MARKERS:
        if _marker_hits(marker, text):
            return kind
    return None


def named_startup_marker_spans(text: Optional[str]) -> list[tuple[str, int, int]]:
    if not text:
        return []
    spans: list[tuple[str, int, int]] = []
    for kind, marker in STARTUP_SCREEN_MARKERS:
        if marker == SHARED_FOOTER_MARKER:
            continue
        if isinstance(marker, str):
            at = text.find(marker)
            if at >= 0:
                spans.append((kind, at, at + len(marker)))
        else:
            found = marker.search(text)
            if found is not None:
                spans.append((kind, found.start(), found.end()))
    return spans


def detect_startup_prompt(tail: Optional[str]) -> Optional[bool]:
    if tail is None:
        return None
    return any(_marker_hits(marker, tail) for marker in STARTUP_PROMPT_MARKERS)


def should_capture_tail(
    *,
    pane_alive: Optional[bool],
    first_hook_at: Optional[datetime],
    instance_age_seconds: Optional[float],
    grace_seconds: int = STARTUP_HOOK_GRACE_SECONDS,
    tail_age_seconds: Optional[float] = None,
    recheck_seconds: int = STARTUP_TAIL_RECHECK_SECONDS,
) -> bool:
    if pane_alive is not True:
        return False
    if first_hook_at is not None:
        return False
    if instance_age_seconds is None:
        return False
    if instance_age_seconds < grace_seconds:
        return False
    if tail_age_seconds is not None and tail_age_seconds < recheck_seconds:
        return False
    return True


def resolve_startup_gate(
    *,
    pane_alive: Optional[bool],
    first_hook_at: Optional[datetime],
    instance_age_seconds: Optional[float],
    tail: Optional[str],
    grace_seconds: int = STARTUP_HOOK_GRACE_SECONDS,
    remembered_match: Optional[bool] = None,
) -> str:
    if first_hook_at is not None:
        return GATE_READY
    if pane_alive is None:
        return GATE_UNKNOWN
    if pane_alive is False:
        return GATE_READY
    if instance_age_seconds is None:
        return GATE_UNKNOWN
    if instance_age_seconds < grace_seconds:
        return GATE_UNKNOWN
    matched = detect_startup_prompt(tail)
    if matched is None:
        matched = remembered_match
    if matched is None:
        return GATE_UNKNOWN
    return GATE_AWAITING if matched else GATE_READY
