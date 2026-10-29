"""Build the compact change notices that travel on `/ws/events`.

WHY ITS OWN FILE. The two places that know a session changed are
`src/api/routes.py` and `src/core/session_manager.py`, and both are far
past this project's line budget and must not grow. More to the point, the
RULE for what a notice may claim does not belong in either of them: it
belongs somewhere a reader can find it in one piece.

A NOTICE CARRIES FACTS THAT WERE MEASURED, AND NOTHING ELSE. `build_status_notice`
is PURE - it takes values already in hand and shapes them. It does not
resolve a status, read a pane, open a database or invent a default. A
field the caller could not measure is simply absent from the frame, and
the client leaves what it holds alone: absent is not a default, and a
fabricated `ready` or a fabricated `idle` is exactly the false-green
failure this project keeps paying for.

THE STATUS NOTICE IS NOT AN ALERT, SO THE MUTE DOES NOT GATE IT. That
looks like a hole and is not. Muting a session suppresses the
INTERRUPTION - the toast, the push - and changes nothing about what the
session's row is allowed to say; a muted session's light updates on the
five second poll today and would be visibly stale if this channel refused
to say so. The TOAST notice is gated, and it is gated by construction
rather than by a second copy of the rule: it is published from the one
place in `claude_event_hook` that a suppressed toast never reaches, past
both the notification-policy gate and the sub-agent gate, beside the
existing per-session broadcast.

A NOTICE IS AN OPTIMISATION AND MAY BE LOST. Hook events are unordered,
duplicated and droppable, so notices derived from them are too. Every
frame here is therefore a statement of current fact rather than a delta,
which is what makes the same notice twice a no-op on the client and a
dropped one recoverable by the next notice or the next poll.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from src.core.event_hub import EventHub, get_hub
from src.models import WSMessageType

logger = structlog.get_logger()


def build_status_notice(
    *,
    session_id: str,
    tmux_session: Optional[str] = None,
    epoch: Optional[int] = None,
    activity_status: Optional[str] = None,
    unread: Optional[bool] = None,
    startup_gate: Optional[str] = None,
) -> Dict[str, Any]:
    frame: Dict[str, Any] = {
        "type": WSMessageType.SESSION_STATUS_CHANGED,
        "session_id": session_id,
    }
    if tmux_session:
        frame["tmux_session"] = tmux_session
    if epoch is not None:
        frame["epoch"] = epoch
    if activity_status is not None:
        frame["activity_status"] = activity_status
    if unread is not None:
        frame["unread"] = unread
    if startup_gate is not None:
        frame["startup_gate"] = startup_gate
    return frame


def build_structural_notice(reason: str) -> Dict[str, Any]:
    return {"type": WSMessageType.SESSIONS_CHANGED, "reason": reason}


def build_rename_notice(*, session_id: str, new_name: str) -> Dict[str, Any]:
    """Shape the "this session is called something else now" notice. Pure.

    Description: THE SAME FRAME THE PER-SESSION SOCKET ALREADY SENDS, so
      a client keeps one handler rather than two. It is the same posture
      the toast notice takes: the rename goes out on the terminal socket
      for the browsers attached to that session AND on the per-browser
      channel, because a browser can be showing a session's name without
      holding a terminal socket for it - the compiled front end's
      terminal cells read their name out of the `/sessions/list` listing,
      and that listing's poll is PAUSED while the terminal screen is the
      screen on show (`client/js/launchpad-host.js`). Without this notice
      those cells keep the name the last poll happened to return.

      The field names are `SessionRenamedMessage`'s own, and
      `tests/test_session_renamed_broadcast_is_live.py` fails if the
      two shapes ever drift apart.
    Inputs: session_id (str) - the id the rest of the app routes on;
      new_name (str) - the label the row now carries.
    Output: dict - a JSON-encodable frame.
    Example: build_rename_notice(session_id="ses_1", new_name="triage")
    """
    return {
        "type": WSMessageType.SESSION_RENAMED,
        "session_id": session_id,
        "new_name": new_name,
    }


def publish(app_state: Any, frame: Dict[str, Any]) -> int:
    """Put one frame on the hub, tolerating an app that has none.

    Description: FAIL-SOFT at every publish site. An app built without
      the channel behaves exactly as it did before this existed, and a
      publish that could not happen costs the client only its five second
      poll. It never awaits, so a publish cannot delay the hook route it
      is called from.
    Inputs: app_state (Any) - typically `request.app.state`; frame (dict).
    Output: int - clients the frame was accepted by; 0 when there is no
      hub or nobody is connected.
    Example: publish(request.app.state, build_structural_notice("created"))
    """
    hub: Optional[EventHub] = get_hub(app_state)
    if hub is None:
        return 0
    return hub.publish(frame)


def publish_attention_status(
    app_state: Any,
    session_manager: Any,
    session_id: str,
    *,
    activity_status: Optional[str] = None,
) -> int:
    hub = get_hub(app_state)
    if hub is None or hub.client_count == 0:
        return 0

    unread: Optional[bool] = None
    tmux_session: Optional[str] = None
    epoch: Optional[int] = None

    registry = getattr(getattr(app_state, "services", None), "registry", None)
    backend = None
    getter = getattr(registry, "get_backend", None)
    if callable(getter):
        backend = getter(session_id)
    tmux_session = getattr(backend, "tmux_session", None)
    if tmux_session is None:
        authority = getattr(session_manager, "hook_tokens", None)
        tmux_session = (getattr(authority, "tmux_names", None) or {}).get(session_id)
    epoch = getattr(session_manager, "_instance_epochs", {}).get(session_id)

    if tmux_session:
        reader = getattr(session_manager, "_is_unread", None)
        if callable(reader):
            try:
                unread = bool(reader(tmux_session, epoch))
            except OSError as exc:
                # did not answer
                logger.debug("event_notice_unread_unreadable",
                             session_id=session_id, error=str(exc))

    if activity_status is not None:
        from src.core.session_status import derive_read_state

        activity_status = derive_read_state(
            activity_status, unread=bool(unread)
        )

    return hub.publish(
        build_status_notice(
            session_id=session_id,
            tmux_session=tmux_session,
            epoch=epoch,
            activity_status=activity_status,
            unread=unread,
        )
    )
