
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import structlog

from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_adopt_dead_gate import PERSIST_PANE_DEAD, check_dead_husk
from src.core.session_identity import (
    ADOPT_CLAIMED,
    claim_instance,
)
from src.core.session_project_binding import (
    columns_to_write,
    resolve_project_binding,
)
from src.core.session_store import get_instance
from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()

ADOPT_LIFECYCLE_SOURCE = "adopt"

# the session is gone
PERSIST_SESSION_GONE = "session_gone"

# could not
PERSIST_LISTING_UNAVAILABLE = "listing_unavailable"

PERSIST_REFUSED = "refused"


class AdoptTargetGoneError(RuntimeError):
    """The target of an adopt was MEASURED gone, not merely un-probed.

    Description: raised so the route can answer "that session is no
      longer there" with a refresh instead of the 500 a genuine server
      fault produces. It is deliberately a distinct type and not a bare
      RuntimeError, because ``adopt_external_session`` also raises plain
      RuntimeError for a probe that could not RUN (tmux timed out or
      errored on the listing, or on the later ``#{pane_dead}`` check) and
      for a failed pipe-pane setup, and those are genuine server faults
      while this is a stale client view of a normal, expected race.
    """


@dataclass(frozen=True)
class AdoptPersistResult:
    """What the persistence half of one adoption did.

    Description: carries the outcome vocabulary of
      :func:`src.core.session_identity.claim_instance` plus the three
      failures that can happen before the UPDATE is even reachable. A
      caller must test :attr:`persisted` rather than assuming, because
      four of the possible outcomes look like success from a distance.
    Inputs (constructor): outcome (str) - ``claimed`` or one of the
      failure tokens. session_uuid (str | None) - the claimed row's
      external identity. working_dir (str | None) - the directory probed
      during this adoption, None when it could not be read.
      project_id (int | None) and project_attribution (str | None) - the
      attribution applied. epoch (int | None) - the instance's
      ``#{session_created}``, present whenever the listing actually
      located the live instance (i.e. whenever ``PERSIST_SESSION_GONE``
      and ``PERSIST_LISTING_UNAVAILABLE`` do NOT apply), so a caller can
      key a durable, instance-scoped write (e.g. ``activity_persist.
      write_state``) off this adoption without a second tmux probe.
      detail (str | None) - human-readable reason.
    Output: an AdoptPersistResult instance.
    """

    outcome: str
    session_uuid: Optional[str] = None
    working_dir: Optional[str] = None
    project_id: Optional[int] = None
    project_attribution: Optional[str] = None
    epoch: Optional[int] = None
    detail: Optional[str] = None

    @property
    def persisted(self) -> bool:
        return self.outcome == ADOPT_CLAIMED


def find_live_instance(
    listing: TmuxListing, name: str
) -> Optional[Dict[str, Any]]:
    for row in listing.sessions:
        if isinstance(row, dict) and row.get("name") == name:
            return row
    return None


def persist_adoption(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    listing: TmuxListing,
    working_dir_probe: Optional[Callable[[str], Optional[str]]] = None,
    pane_pid_probe: Optional[Callable[[str], Optional[int]]] = None,
    pane_dead_probe: Optional[Callable[[str], Optional[bool]]] = None,
    now: Optional[str] = None,
) -> AdoptPersistResult:
    from src.core.session_identity import record_instance

    if not listing.ok:
        logger.warning(
            "adopt_persist_listing_unavailable",
            tmux_name=name,
            listing_reason=listing.reason,
            note=(
                "CANNOT DETERMINE whether this instance is live, so "
                "nothing is recorded and nothing is claimed. This is not "
                "the same as the session being gone"
            ),
        )
        return AdoptPersistResult(
            outcome=PERSIST_LISTING_UNAVAILABLE,
            detail=(
                "could not ask tmux whether that session is still there "
                f"({listing.reason or 'probe_error'})"
            ),
        )

    live = find_live_instance(listing, name)
    if live is None:
        logger.warning(
            "adopt_persist_session_gone",
            tmux_name=name,
            tmux_socket=socket,
            note=(
                "the listing RAN and does not contain this name, so the "
                "session died between the client's listing and its "
                "adopt. No row is marked adopted"
            ),
        )
        return AdoptPersistResult(
            outcome=PERSIST_SESSION_GONE,
            detail="that session is no longer there",
        )

    try:
        epoch = int(live.get("created_at_epoch"))
    except (TypeError, ValueError):
        logger.warning(
            "adopt_persist_epoch_unreadable",
            tmux_name=name,
            raw_epoch=live.get("created_at_epoch"),
        )
        return AdoptPersistResult(
            outcome=PERSIST_LISTING_UNAVAILABLE,
            detail="that session reported no usable creation time",
        )

    working_dir = live.get("working_dir")
    if working_dir is None and working_dir_probe is not None:
        working_dir = working_dir_probe(name)
    stored = get_instance(conn, socket=socket, name=name, epoch=epoch) or {}
    if check_dead_husk(
        name=name,
        socket=socket,
        epoch=epoch,
        stored_row=stored,
        pane_dead_probe=pane_dead_probe,
    ):
        return AdoptPersistResult(
            outcome=PERSIST_PANE_DEAD,
            epoch=epoch,
            detail="that session's process has exited",
        )
    stored_project_id = stored.get("project_id")
    binding = resolve_project_binding(
        conn,
        working_dir,
        stored_project_id=stored_project_id,
        allow_create=False,
        now=now,
    )
    project_id, attribution = columns_to_write(binding, stored_project_id)

    sighting = record_instance(
        conn,
        socket=socket,
        name=name,
        epoch=epoch,
        origin=SESSION_ORIGIN_OBSERVED,
        lifecycle=SESSION_LIFECYCLE_RUNNING,
        lifecycle_source=ADOPT_LIFECYCLE_SOURCE,
        session_id=live.get("tmux_session_id"),
        now=now,
        working_dir=working_dir,
        project_id=project_id,
        project_attribution=attribution,
    )
    if sighting.refused:
        logger.warning(
            "adopt_persist_sighting_refused",
            tmux_name=name,
            tmux_socket=socket,
            tmux_created_epoch=epoch,
            outcome=sighting.outcome,
            detail=sighting.detail,
        )
        return AdoptPersistResult(
            outcome=PERSIST_REFUSED,
            epoch=epoch,
            detail=sighting.detail or "that tmux name refers to a different session",
        )

    claim = claim_instance(
        conn,
        socket=socket,
        name=name,
        epoch=epoch,
        now=now,
        project_id=project_id,
        project_attribution=attribution,
        working_dir=working_dir,
    )
    if not claim.claimed:
        return AdoptPersistResult(
            outcome=claim.outcome,
            session_uuid=claim.session_uuid,
            epoch=epoch,
            detail=claim.detail,
        )

    pane_pid = pane_pid_probe(name) if pane_pid_probe is not None else None
    _try_correlate_claude_session(
        conn,
        socket=socket,
        name=name,
        epoch=epoch,
        working_dir=working_dir,
        pane_pid=pane_pid,
        now=now,
    )

    logger.info(
        "adopt_persisted",
        tmux_name=name,
        tmux_socket=socket,
        tmux_created_epoch=epoch,
        session_uuid=claim.session_uuid,
        project_attribution=attribution,
        project_binding_rule=binding.rule,
        note="origin='adopted' is written once and never recomputed",
    )
    return AdoptPersistResult(
        outcome=ADOPT_CLAIMED,
        session_uuid=claim.session_uuid,
        working_dir=working_dir,
        project_id=binding.project_id,
        project_attribution=binding.attribution,
        epoch=epoch,
    )


def _try_correlate_claude_session(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: int,
    working_dir: Optional[str],
    pane_pid: Optional[int],
    now: Optional[str],
) -> None:
    try:
        from src.core.claude_session_correlate_ladder import (
            LADDER_METHOD_PANE_ARGV,
            correlate_adopted_session_ladder,
        )
        from src.core.db_models import (
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
        )
        from src.core.session_claude_correlate_bind import bind_correlated_uuid

        ladder = correlate_adopted_session_ladder(
            pane_pid=pane_pid, working_dir=working_dir, tmux_created_epoch=epoch
        )
        if not ladder.matched:
            logger.info(
                "adopt_claude_uuid_not_correlated",
                tmux_name=name,
                outcome=ladder.outcome,
                detail=ladder.detail,
            )
            return

        source = (
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV
            if ladder.method == LADDER_METHOD_PANE_ARGV
            else SESSION_CLAUDE_UUID_SOURCE_CORRELATED
        )
        bind = bind_correlated_uuid(
            conn,
            socket=socket,
            name=name,
            epoch=epoch,
            claude_uuid=ladder.claude_session_uuid or "",
            source=source,
            now=now,
        )
        if bind.wrote:
            logger.info(
                "adopt_claude_uuid_correlated",
                tmux_name=name,
                claude_session_uuid=ladder.claude_session_uuid,
                method=ladder.method,
                transcript_path=ladder.transcript_path,
            )
        else:
            logger.info(
                "adopt_claude_uuid_bind_skipped",
                tmux_name=name,
                outcome=bind.outcome,
                detail=bind.detail,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "adopt_claude_uuid_correlate_failed",
            tmux_name=name,
            tmux_socket=socket,
            error=str(exc),
        )
