
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ToastDetail(BaseModel):
    """What a toast knows about WHY its session wants the user (issue #750).

    Facts, never a sentence: the client builds the card's descriptive title
    from the one string catalog. Read from the SAME watcher observation that
    raised the toast (``src/core/attention/toast_detail.py``), and every
    string is redacted before it is stored. Only the detailed toast mode
    renders it; the compact mode and the external channels read ``title``
    and ``body`` exactly as before.
    """
    reason: Optional[str] = Field(
        None, description="The edge's attention reason, e.g. 'permission' or 'turn_ended'"
    )
    tool: Optional[str] = Field(None, description="The tool the session is blocked on, if any")
    target: Optional[str] = Field(
        None, description="What that tool acts on (a command, a path), redacted and bounded"
    )
    snippet: Optional[str] = Field(
        None, description="What claude last said, or the question it asks, redacted and bounded"
    )


class Toast(BaseModel):
    """A toast notification recorded for a session.

    Storage shape: each session keeps a list of these, newest-first, capped
    at ``unacked + last 50 acked``. Created via
    ``SessionManager.record_toast``; acked via ``SessionManager.ack_toast``.
    The ``color`` field is precomputed at record time from the session's
    project theme (``--color-accent`` in the theme manifest's ``cssVars``)
    so the client can paint a per-session-colored left border without an
    extra theme lookup.
    """
    id: str = Field(..., description="UUID4 string")
    session_id: str = Field(..., description="Session this toast belongs to")
    kind: str = Field(
        ...,
        description="Toast kind: 'Stop' | 'PermissionRequest' | 'Notification'",
    )
    title: str = Field(..., description="Short bold headline")
    body: Optional[str] = Field(None, description="Optional longer body text")
    color: Optional[str] = Field(
        None,
        description="Hex accent color resolved from the session's project theme",
    )
    session_label: Optional[str] = Field(
        None,
        description=(
            "The session's user-facing label at record time; None when it "
            "had none. NOT a display string - the client applies the "
            "fallback."
        ),
    )
    session_name: Optional[str] = Field(
        None,
        description=(
            "The session's tmux name at record time; None for a non-tmux "
            "session. The fallback the client renders when there is no label."
        ),
    )
    notify_type: Optional[str] = Field(
        None, description="Registered notification type id, e.g. 'session.finished'; None on older records"
    )
    detail: Optional[ToastDetail] = Field(
        None, description="Reason, tool, target and snippet for the detailed toast mode"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(
        1,
        description=(
            "Monotonic version of this record, starting at 1. Bumped only "
            "on a real content change (supersession with different body, "
            "or an ack transition), never on a duplicate or reorder of "
            "the same fact. A client compares this, not the id alone, "
            "before replacing a held record: higher replaces, equal is a "
            "no-op, lower is discarded as an out-of-order delivery."
        ),
    )
    acknowledged: bool = Field(
        False, description="True once the toast has been dismissed"
    )
    ack_reason: Optional[str] = Field(
        None,
        description=(
            "Why this toast was acknowledged: 'dismissed' (a human "
            "cleared it) or 'answered' (a hook said the user turned "
            "up). None while the toast is still open."
        ),
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class CreateToastRequest(BaseModel):
    """Request body for ``POST /api/v1/sessions/{session_id}/toasts``.

    Synthetic creation endpoint used by v0.7.0 Part 2 testing. Part 3 will
    add a hook-driven endpoint with different auth semantics; this surface
    is INTENTIONALLY kept around so the client and the storage layer have a
    way to be exercised end-to-end without a real Claude Code hook.
    """
    kind: str = Field(
        ...,
        description="Toast kind: 'Stop' | 'PermissionRequest' | 'Notification'",
    )
    title: str = Field(..., description="Short bold headline")
    body: Optional[str] = Field(None, description="Optional longer body text")
    detail: Optional[ToastDetail] = Field(
        None, description="Reason, tool, target and snippet, as the watcher stamps them (issue #750)"
    )


class MuteNotificationsRequest(BaseModel):
    """Body of ``PATCH /sessions/records/{session_uuid}/notifications``.
    """

    muted: bool = Field(
        ...,
        description="The state being requested. Idempotent: not a toggle",
    )
    expected_tmux_name: Optional[str] = Field(
        default=None,
        description=(
            "The tmux session name the caller believes this row carries. "
            "Checked only when sent together with the epoch"
        ),
    )
    expected_tmux_created_epoch: Optional[int] = Field(
        default=None,
        description=(
            "tmux #{session_created} for the instance the caller means. "
            "With the name this is the INSTANCE identity"
        ),
    )


class NotificationPolicyResponse(BaseModel):
    """What ``PATCH .../notifications`` committed.

    Both fields are the COMMITTED values read back from the row, never the
    values that were requested. A response that echoed the request would be
    unable to report an idempotent no-op honestly, and the generation is
    the one number a caller must not be allowed to guess: it orders every
    queued notification against this change.
    """

    muted: bool = Field(
        ..., description="The committed mute state on the row"
    )
    policy_generation: int = Field(
        ...,
        description=(
            "The committed policy generation. Steps by one on every real "
            "change, in both directions; unchanged by a no-op"
        ),
    )
