
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from .sessions import Session


# already exists
class AttachableSession(BaseModel):
    """A tmux session on our socket that the UI may adopt.

    ``created_by_cloude`` is True iff this session is OURS, resolved from
    ``sessions.origin`` on the tmux INSTANCE triple (socket, name,
    creation epoch) - both ``created`` and ``adopted`` count, per design
    section 4.6. False means ``observed``: a session on our socket we have
    never claimed, which is the intended adopt target. Resolving on the
    instance rather than the name is what stops a reused tmux name from
    inheriting a dead session's badge.
    """
    name: str = Field(..., description="Literal tmux session name")
    label: Optional[str] = Field(
        default=None,
        description="User-facing session label; falls back to name when None",
    )
    created_by_cloude: bool = Field(
        ..., description="True if Cloude Code created this session"
    )
    created_by_us: bool = Field(
        default=False,
        description=(
            "True if this app created this session. Same value as "
            "created_by_cloude, which is kept for the transition window "
            "(docs/rename-carnivore.md)."
        ),
    )
    created_at_epoch: int = Field(
        ..., description="tmux session creation time (Unix epoch seconds)"
    )
    window_count: int = Field(..., description="Number of windows in the session")
    agent_type: Optional[str] = Field(
        default=None,
        description="Detected agent CLI type for this tmux session (None = not yet fingerprinted)",
    )
    agent_family: Optional[str] = Field(
        default=None,
        description="Resolved family name for display, or None if it could not be determined",
    )
    agent_family_source: Optional[str] = Field(
        default=None,
        description=(
            "Provenance of agent_family: 'wrapper' | 'reserved_name' | "
            "'fingerprint' | 'derived_deepest' | 'unknown'."
        ),
    )
    agent_wrapper_label: Optional[str] = Field(
        default=None,
        description="Configured label of the launch wrapper, or None if none can be named",
    )
    pinned_theme: Optional[str] = Field(
        default=None,
        description="Theme id pinned to this session (None = no pin)",
    )
    session_row_id: Optional[int] = Field(
        None,
        description="sessions.id for this instance; None when we have no row",
    )
    parent_session_id: Optional[int] = Field(
        None,
        description="sessions.id this one was forked from; None = not a fork",
    )
    status: str = Field(
        default="unknown",
        description=(
            "Activity status (tmux-fallback subset): 'dead' | 'working' | "
            "'finished_unread' | 'idle' | 'unknown'"
        ),
    )
    unread: bool = Field(
        default=False,
        description="True if this tmux session has an unread Stop or a manual unread pin",
    )
    listing_ok: bool = Field(
        default=True,
        description="True when the tmux probe that produced this row actually ran",
    )
    listing_reason: Optional[str] = Field(
        default=None,
        description=(
            "Why the listing turned out the way it did: null = listed "
            "normally, 'no_server' = tmux reported no server (a real zero), "
            "'not_applicable' = non-tmux backend"
        ),
    )

    @model_validator(mode="after")
    def _mirror_created_by_us(self) -> "AttachableSession":
        self.created_by_us = self.created_by_cloude
        return self


class AttachableListingStatus(BaseModel):
    """
    Returned as the ``detail`` of an HTTP 503 from
    ``GET /sessions/attachable`` when the tmux probe did not produce an
    answer. It deliberately carries no ``sessions`` array: the whole
    point is that we do not know what the sessions are, and shipping an
    empty one alongside a failure flag invites a client to read the
    array and ignore the flag - which is how this bug shipped the first
    time.

    ``listing_ok`` is always False here. A successful listing is the
    plain ``List[AttachableSession]`` 200 response instead.
    """
    listing_ok: bool = Field(
        default=False,
        description="Always False - this model exists only for the unknown case",
    )
    listing_reason: str = Field(
        ...,
        description=(
            "Machine-readable cause: 'tmux_missing' | 'timeout' | "
            "'probe_error' | 'exit_<returncode>'"
        ),
    )
    listing_detail: Optional[str] = Field(
        default=None,
        description="Human-readable detail (trimmed tmux stderr or exception text)",
    )
    message: str = Field(
        default="tmux session listing could not be determined",
        description="Display string for a client that has no reason mapping",
    )


class AdoptSessionRequest(BaseModel):
    """Request body for ``POST /sessions/adopt``."""
    session_name: str = Field(
        ..., description="Literal tmux session name to adopt"
    )
    confirm_detach: bool = Field(
        False,
        description=(
            "Explicit consent to detach from an already-active session "
            "before adopting. The prior session's tmux pane stays alive "
            "on the socket and can be re-adopted later. Required (must "
            "be True) when a session is live; the server returns 409 "
            "otherwise."
        ),
    )
    cols: Optional[int] = Field(
        None,
        description="Client-measured terminal columns (xterm cell grid width)"
    )
    rows: Optional[int] = Field(
        None,
        description="Client-measured terminal rows (xterm cell grid height)"
    )


class AdoptSessionResponse(BaseModel):
    """Response body for ``POST /sessions/adopt``.

    ``initial_scrollback_b64`` is base64-encoded raw pane bytes captured at
    adopt time - the client decodes and paints into xterm BEFORE opening
    the WebSocket. ``fifo_start_offset`` is the byte offset the server's
    WS tailer seeks to on first read, so post-adopt live bytes resume
    exactly where the painted scrollback ended (no duplicate, no gap).
    """
    session: Session = Field(..., description="The adopted session record")
    initial_scrollback_b64: str = Field(
        ...,
        description=(
            "Base64-encoded scrollback bytes captured from the tmux pane at "
            "adopt time. May be empty if capture returned nothing."
        ),
    )
    fifo_start_offset: int = Field(
        ...,
        description=(
            "Byte offset into the pipe-pane FIFO recorded immediately after "
            "pipe-pane became active. WS tailer seeks here on first read."
        ),
    )
