"""The result type for every tmux enumeration in this app.

That is the false-green class this repo's THREE-OUTCOME RULE exists to
kill: pass, fail, and COULD NOT EVALUATE, where the third is never a
flavour of the other two. An empty list is an ANSWER. A failed probe is
the ABSENCE of an answer. They need different values, so they get
different fields.

THE SHAPE.

    ok        True  -> the probe RAN and ``sessions`` is the complete,
                      trustworthy answer. ``sessions == []`` with
                      ``ok=True`` means genuinely zero sessions.
              False -> the probe did not produce an answer. ``sessions``
                      is always ``[]`` and carries NO information.
                      Callers MUST NOT transition, prune, or reconcile
                      any state against it.
    sessions  The rows. Element type is the producer's business:
              ``discover_existing`` yields ``str`` names,
              ``list_attachable_sessions`` and ``list_pane_status_all``
              yield ``dict`` rows.
    reason    A short machine-readable token, present on BOTH outcomes.
              On ``ok=True`` it explains why the answer is what it is
              (``no_server`` = tmux told us there is no server, which is
              a real, complete answer of zero). On ``ok=False`` it names
              what stopped us. ``None`` means "listed normally".
    detail    Optional human string (trimmed stderr, exception text) for
              the log line and the UI tooltip. Never parsed.

WHY ``no_server`` IS ``ok=True``. This is the whole crux of the type. A
tmux server exits when its last session ends, so "no server running" is
the NORMAL steady state of a machine with zero sessions - it is tmux
answering the question, not failing to. Collapsing it into ``ok=False``
would make the home screen shout CANNOT DETERMINE at every user who has
simply closed all their sessions, the alert would lose its credibility
within a day, and the type would be worthless. Collapsing the other way
- treating every rc=1 as ``no_server`` - is the original bug. The split
is made by :func:`classify_listing_failure` on the stderr text, and it
is the single place that decision is made.

DELIBERATELY NOT A COLLECTION. This class defines no ``__iter__``, no
``__len__`` and no ``__bool__``. That is on purpose: a call site that
was not updated fails loudly with a ``TypeError`` instead of silently
iterating, or silently testing truthy, and reintroducing the exact bug
this type was written to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence


REASON_LISTED: Optional[str] = None

REASON_NO_SERVER = "no_server"

REASON_TMUX_MISSING = "tmux_missing"

REASON_TIMEOUT = "timeout"

REASON_PROBE_ERROR = "probe_error"

REASON_NOT_APPLICABLE = "not_applicable"

# could not
REASON_HOST_UNREACHABLE = "host_unreachable"

REASON_VERSION_SKEW = "version_skew"

# could not
REASON_EXIT_PREFIX = "exit_"


def exit_reason(returncode: int) -> str:
    return f"{REASON_EXIT_PREFIX}{returncode}"


from src.core.tmux_stderr import (  # noqa: E402,F401
    LISTING_ENV_OVERRIDES,
    REASON_CONNECT_FAILED,
    STDERR_CONNECT_FAILED,
    STDERR_NO_SERVER,
    STDERR_UNRECOGNISED,
    classify_tmux_stderr,
    listing_env,
    looks_like_no_server,
)

from src.core.tmux_stderr import (  # noqa: E402,F401
    _CONNECT_ERROR_MARKER,
    _CONNECT_ERRNO_RE,
    _NO_SERVER_CONNECT_ERRNOS,
    _NO_SERVER_MARKERS,
)


def classify_listing_failure(returncode: int, stderr_text: str) -> "TmuxListing":
    """Turn a non-zero tmux exit into the right one of the three outcomes.

    The single place the ``no_server`` / real-error split is decided, so
    all three enumeration methods cannot drift apart on it.

    Inputs:
        returncode (int): tmux's exit status (already known non-zero).
        stderr_text (str): decoded stderr.

    Output:
        TmuxListing: ``ok=True, sessions=[], reason='no_server'`` ONLY
            when tmux reported an absent server (a complete answer of
            zero). ``ok=False, reason='connect_failed'`` when the socket
            could not be reached for any other cause, and
            ``ok=False, reason='exit_<rc>'`` for anything unrecognised.

    Example:
        >>> classify_listing_failure(1, "no server running on /tmp/x").ok
        True
        >>> classify_listing_failure(1, "error connecting to /x (Permission denied)").ok
        False
    """
    verdict = classify_tmux_stderr(stderr_text)
    detail = (stderr_text or "").strip() or None
    if verdict == STDERR_NO_SERVER:
        return TmuxListing.answered([], reason=REASON_NO_SERVER, detail=detail)
    if verdict == STDERR_CONNECT_FAILED:
        return TmuxListing.unavailable(REASON_CONNECT_FAILED, detail=detail)
    return TmuxListing.unavailable(exit_reason(returncode), detail=detail)


@dataclass(frozen=True)
class TmuxListing:

    ok: bool
    sessions: List[Any] = field(default_factory=list)
    reason: Optional[str] = None
    detail: Optional[str] = None
    refused_rows: int = 0

    @classmethod
    def answered(
        cls,
        sessions: Sequence[Any],
        reason: Optional[str] = REASON_LISTED,
        detail: Optional[str] = None,
        refused_rows: int = 0,
    ) -> "TmuxListing":
        return cls(
            ok=True,
            sessions=list(sessions),
            reason=reason,
            detail=detail,
            refused_rows=int(refused_rows),
        )

    @property
    def complete(self) -> bool:
        return self.ok and self.refused_rows == 0

    @classmethod
    def unavailable(cls, reason: str, detail: Optional[str] = None) -> "TmuxListing":
        """Build a "could not evaluate" result. Never carries rows.

        Inputs:
            reason (str): why we could not answer (``tmux_missing``,
                ``timeout``, ``exit_2``, ``probe_error``).
            detail (Optional[str]): human-readable text for the log.

        Output:
            TmuxListing: with ``ok=False`` and ``sessions=[]``.

        Example:
            >>> TmuxListing.unavailable('timeout').ok
            False
        """
        return cls(ok=False, sessions=[], reason=reason, detail=detail)

    @property
    def names(self) -> List[str]:
        out: List[str] = []
        for row in self.sessions:
            if isinstance(row, str):
                out.append(row)
            elif isinstance(row, dict):
                name = row.get("name")
                if isinstance(name, str) and name:
                    out.append(name)
        return out

    def status_payload(self) -> dict:
        return {
            "listing_ok": self.ok,
            "listing_reason": self.reason,
            "listing_detail": self.detail,
        }


    def row_status_payload(self) -> dict:
        return {"listing_ok": self.ok, "listing_reason": self.reason}


def coerce_listing(value: Any) -> TmuxListing:
    if isinstance(value, TmuxListing):
        return value
    if value is None:
        return TmuxListing.unavailable(
            REASON_PROBE_ERROR, detail="listing source returned None"
        )
    if isinstance(value, (list, tuple)):
        return TmuxListing.answered(list(value))
    return TmuxListing.unavailable(
        REASON_PROBE_ERROR, detail=f"unusable listing type {type(value).__name__}"
    )
