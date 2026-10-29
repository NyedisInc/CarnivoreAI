
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from src.core import tmux_stderr


REASON_LISTED: Optional[str] = None

REASON_NO_SERVER = "no_server"

REASON_TMUX_MISSING = "tmux_missing"

REASON_TIMEOUT = "timeout"

REASON_PROBE_ERROR = "probe_error"

REASON_NOT_APPLICABLE = "not_applicable"

REASON_HOST_UNREACHABLE = "host_unreachable"

REASON_VERSION_SKEW = "version_skew"

REASON_EXIT_PREFIX = "exit_"


def exit_reason(returncode: int) -> str:
    return f"{REASON_EXIT_PREFIX}{returncode}"


def classify_listing_failure(returncode: int, stderr_text: str) -> "TmuxListing":
    verdict = tmux_stderr.classify_tmux_stderr(stderr_text)
    detail = (stderr_text or "").strip() or None
    if verdict == tmux_stderr.STDERR_NO_SERVER:
        return TmuxListing.answered([], reason=REASON_NO_SERVER, detail=detail)
    if verdict == tmux_stderr.STDERR_CONNECT_FAILED:
        return TmuxListing.unavailable(tmux_stderr.REASON_CONNECT_FAILED, detail=detail)
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
