
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import structlog

logger = structlog.get_logger()

OBSERVER_QUERY_PARAM = "observer"

OBSERVER_QUERY_VALUE = "1"

INTERACTIVE_QUERY_PARAM = "interactive"

INTERACTIVE_QUERY_VALUE = "1"

OBSERVER_REFUSAL_EVENT = "ws_observer_frame_refused"

REASON_BINARY_INPUT = "binary_input"
REASON_PTY_RESIZE = "pty_resize"


@dataclass(frozen=True)
class TerminalSocketRole:

    negotiates_size: bool
    awaits_handshake: bool
    marks_viewed: bool
    accepts_input: bool


PRIMARY_ROLE: TerminalSocketRole = TerminalSocketRole(
    negotiates_size=True,
    awaits_handshake=True,
    marks_viewed=True,
    accepts_input=True,
)

OBSERVER_ROLE: TerminalSocketRole = TerminalSocketRole(
    negotiates_size=False,
    awaits_handshake=False,
    marks_viewed=False,
    accepts_input=False,
)

INTERACTIVE_VIEWER_ROLE: TerminalSocketRole = TerminalSocketRole(
    negotiates_size=False,
    awaits_handshake=False,
    marks_viewed=False,
    accepts_input=True,
)


def role_for_query(query_params: Optional[Mapping[str, Any]]) -> TerminalSocketRole:
    if query_params is None:
        return PRIMARY_ROLE
    raw = query_params.get(OBSERVER_QUERY_PARAM)
    if raw != OBSERVER_QUERY_VALUE:
        return PRIMARY_ROLE
    if query_params.get(INTERACTIVE_QUERY_PARAM) == INTERACTIVE_QUERY_VALUE:
        return INTERACTIVE_VIEWER_ROLE
    return OBSERVER_ROLE


def refuse_frame(session_id: Optional[str], reason: str) -> None:
    logger.warning(
        OBSERVER_REFUSAL_EVENT,
        session_id=session_id,
        reason=reason,
    )
