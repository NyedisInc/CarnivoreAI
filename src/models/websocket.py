
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from .notifications import Toast
from .sessions import SessionStatus



class WSMessageType(str, Enum):
    LOG = "log"
    # Plan v3.2
    LOCAL_SERVER_DETECTED = "local_server_detected"
    LOCAL_SERVER_LOST = "local_server_lost"
    SESSION_STATUS = "session_status"
    COMMAND = "command"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    PTY_DATA = "pty_data"
    PTY_RESIZE = "pty_resize"
    REQUEST_DIMS = "request_dims"
    TOAST_NEW = "toast.new"
    TOAST_ACK = "toast.ack"
    SESSION_RENAMED = "session.renamed"
    TERMINAL_SIZE = "terminal_size"
    REPAINT = "repaint"
    SIZE_MASTER = "size_master"
    EVENTS_HELLO = "events.hello"
    SESSION_STATUS_CHANGED = "session.status"
    SESSIONS_CHANGED = "sessions.changed"
    LISTING_DELTA = "listing.delta"
    RESOURCES_CHANGED = "resources.changed"
    CPLUG_DATA = "cplug.data"
    APPROVALS = "approvals"
    PREFERENCES_CHANGED = "preferences.changed"
    SKILLS_CHANGED = "skills.changed"
    SESSION_NOTE_CHANGED = "session.note.changed"
    CROSSTALK_CARD = "crosstalk.card"
    PROVIDER_LEDGER_UPDATED = "provider_ledger.updated"
    # active account
    PROVIDER_ACCOUNT_SWITCHED = "provider_account.switched"
    SESSION_AUTO_SLEPT = "session.auto_slept"
    RESTORE_OFFER_PROGRESS = "restore_offer.progress"
    AUTO_SLEEP_CHANGED = "auto_sleep.changed"
    DEV_SHAPE_UNRECOGNIZED = "dev.shape_unrecognized"
    APP_ALERT_RAISED = "app_alert.raised"
    APP_ALERT_UPDATED = "app_alert.updated"
    APP_ALERT_RESOLVED = "app_alert.resolved"
    ACCOUNT_SESSION = "account.session"
    PERF_SAMPLE = "perf.sample"
    ITEM_SETTINGS_CHANGED = "item_settings.changed"
    AI_CONFIG_CHANGED = "ai.config.changed"
    TERMINAL_READY = "terminal.ready"
    TERMINAL_RESYNC = "terminal.resync"


class ToastNewMessage(BaseModel):
    """WS server -> client: a new toast was recorded for this session."""
    type: WSMessageType = WSMessageType.TOAST_NEW
    toast: Toast


class ToastAckMessage(BaseModel):
    """WS server -> client: a toast was acked; other tabs should dismiss it."""
    type: WSMessageType = WSMessageType.TOAST_ACK
    toast_id: str


class SessionRenamedMessage(BaseModel):
    """WS server -> client: a session was renamed; clients should update
    their displayed name, the launchpad row label, and ``document.title``.

    Broadcast by ``PATCH /sessions/{session_id}/name`` after the underlying
    ``tmux rename-session`` succeeds and in-memory state has been re-keyed.
    """
    type: WSMessageType = WSMessageType.SESSION_RENAMED
    session_id: str = Field(..., description="Session id whose name changed")
    new_name: str = Field(..., description="New tmux session name")


class WSLogMessage(BaseModel):
    """WebSocket log message."""
    type: WSMessageType = WSMessageType.LOG
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    content: str
    log_type: str = "stdout"

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class WSLocalServerDetectedMessage(BaseModel):
    """Server -> client event when a new local dev server is detected."""
    type: WSMessageType = WSMessageType.LOCAL_SERVER_DETECTED
    session: str
    port: int
    url: str


class WSLocalServerLostMessage(BaseModel):
    """Server -> client event when a tracked local server stops responding."""
    type: WSMessageType = WSMessageType.LOCAL_SERVER_LOST
    session: str
    port: int


class WSSessionStatusMessage(BaseModel):
    """WebSocket session status message."""
    type: WSMessageType = WSMessageType.SESSION_STATUS
    status: SessionStatus
    uptime: int = 0


class WSCommandMessage(BaseModel):
    """WebSocket command message (client -> server)."""
    type: WSMessageType = WSMessageType.COMMAND
    command: str


class WSErrorMessage(BaseModel):
    """WebSocket error message."""
    type: WSMessageType = WSMessageType.ERROR
    error: str
    message: str


class WSPTYDataMessage(BaseModel):
    """WebSocket PTY data message (server -> client)."""
    type: WSMessageType = WSMessageType.PTY_DATA
    data: str


class WSPTYInputMessage(BaseModel):
    """WebSocket PTY input message (client -> server)."""
    type: WSMessageType = WSMessageType.PTY_DATA
    data: str


class WSPTYResizeMessage(BaseModel):
    """WebSocket PTY resize message (client -> server).

    ``hidden`` is True when the sending tab is in the background: its size
    is recorded but it WITHDRAWS its vote in the smallest-wins negotiation
    (src/core/terminal_size.py). Absent means False, so a client older
    than the field keeps voting exactly as before.
    """
    type: WSMessageType = WSMessageType.PTY_RESIZE
    cols: int
    rows: int
    hidden: bool = False


class WSTerminalReadyMessage(BaseModel):
    """The pane can take input now (server -> client), sent once.

    ``startup_command`` says which ready case this is, in four words that
    are deliberately not collapsible to two. ``issued`` - a configured
    terminal command's bytes were written into the pane just before this
    message, so the first thing the user sees is that command's output.
    ``none`` - nothing was configured, and the pane is at a bare prompt.
    ``failed`` - a command WAS configured and every write attempt failed,
    so the pane is at a prompt the user did not ask for. ``unknown`` - the
    flush could not be run or raised, so what reached the pane was never
    established. A reading that did not happen is not a reading of
    nothing, which is why the last two are separate from ``none``.

    The message is sent in all four cases: readiness is about the pane
    being able to take input, and a startup command that failed does not
    make the pane unable to take input. Never withhold it.

    Example:
        WSTerminalReadyMessage(startup_command="none").model_dump()
    """
    type: WSMessageType = WSMessageType.TERMINAL_READY
    startup_command: str = Field(
        "unknown",
        description="'issued' | 'none' | 'failed' | 'unknown' - what the "
                    "startup command flush did, not what it was",
    )


class WSTerminalResyncMessage(BaseModel):
    """WS server -> client: queued output was dropped; a fresh capture follows.

    Sent by the viewer's one writer (``ws_viewer_drain``) right before the
    capture, in order with every other frame. The client aborts any escape
    sequence the cut may have left half-parsed and carries on; the counts
    are for logs. It is never a reason to show a reconnect banner.

    Example:
        WSTerminalResyncMessage(dropped_chunks=255, dropped_bytes=2_785_000).model_dump(mode="json")
    """
    type: WSMessageType = WSMessageType.TERMINAL_RESYNC
    dropped_chunks: int = Field(0, description="pty and paint frames dropped from the queue")
    dropped_bytes: int = Field(0, description="their queued size, base64 characters")
