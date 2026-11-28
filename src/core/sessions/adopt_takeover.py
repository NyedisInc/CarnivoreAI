
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional, Tuple

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.claude_session_correlate_ladder import LADDER_METHOD_PANE_ARGV
from src.core.session_conversation_takeover import decide_conversation_takeover
from src.core.session_lineage import row_for_claude_uuid
from src.core.session_restart import rebind_instance
from src.core.session_store import get_instance
from src.core.product_identity import TMUX_SESSION_PREFIX
from src.core.sessions.adopt_confirm import CONFIRM_ERRORS, NOT_CONFIRMED
from src.core.tmux_listing import TmuxListing

if TYPE_CHECKING:
    from src.core.claude_session_correlate_ladder import LadderResult

logger = structlog.get_logger()


@dataclass(frozen=True)
class AdoptTakeover:

    row_id: Optional[int]
    session_uuid: Optional[str]
    reason: str
    previous_tmux_name: Optional[str] = None

    @property
    def took_over(self) -> bool:
        return self.row_id is not None


def measure_before_claim(
    listing: TmuxListing,
    *,
    socket: str,
    name: str,
    working_dir: Optional[str],
    pane_pid: Optional[int],
) -> Optional["LadderResult"]:
    from src.core.session_adopt_persist import find_live_instance, measure_claude_correlation

    if not listing.ok:
        return None
    live = find_live_instance(listing, name)
    if live is None:
        return None
    try:
        epoch = int(live.get("created_at_epoch"))
    except (TypeError, ValueError):
        return None
    return measure_claude_correlation(
        name=name, socket=socket, epoch=epoch, working_dir=live.get("working_dir") or working_dir, pane_pid=pane_pid
    )


def _refusal(owner: Mapping[str, Any], socket: str) -> Optional[str]:
    if owner.get("archived_at"):
        return "the row owning this conversation is archived, and an adoption never un-archives"
    if (owner.get("host_key") or LOCAL_HOST_KEY) != LOCAL_HOST_KEY:
        return "the row owning this conversation lives on another machine"
    if (owner.get("tmux_socket") or "") != socket:
        return "the row owning this conversation is on another tmux socket, which this listing does not describe"
    return None


def recreate_in_flight(owner: Mapping[str, Any]) -> Optional[str]:
    from src.core import restart_inflight

    if restart_inflight.in_flight(str(owner.get("session_uuid") or "")):
        return "a restart or recreate of the row owning this conversation is in flight, so the adoption steps aside"
    return None


def _ambiguity(conn: sqlite3.Connection, claude_uuid: str) -> Optional[str]:
    held = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE claude_session_uuid = ? AND archived_at IS NULL", (claude_uuid,)
    ).fetchone()[0]
    return "more than one unarchived row records this conversation, so no single owner is certain" if held > 1 else None


def take_over_retired_owner(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: int,
    claude_uuid: Optional[str],
    listing: TmuxListing,
    tmux_session_id: Optional[str],
    working_dir: Optional[str],
    lifecycle_source: str,
    now: Optional[str] = None,
    method: Optional[str] = None,
) -> AdoptTakeover:
    owner = row_for_claude_uuid(conn, claude_uuid or "")
    if owner is None:
        return AdoptTakeover(None, None, "no row records this conversation")
    refusal = recreate_in_flight(owner) or _refusal(owner, socket) or _ambiguity(conn, claude_uuid or "")
    if refusal is None:
        decision = decide_conversation_takeover(
            incumbent_row_id=owner.get("id"),
            incumbent_lifecycle=owner.get("lifecycle"),
            incumbent_tmux_name=owner.get("tmux_name"),
            live_row_id=None,
            live_instance_unrecorded=True,
            live_tmux_name=name,
            listing_ok=listing.ok,
            listing_complete=listing.complete,
            names=[row.get("name") for row in listing.sessions if isinstance(row, dict)],
            namespace_prefix=TMUX_SESSION_PREFIX,
        )
        refusal = None if decision.may_take else decision.detail
    if refusal is not None:
        logger.info("adopt_takeover_declined", tmux_name=name, owner_row_id=owner.get("id"),
                    claude_session_uuid=claude_uuid, method=method, reason=refusal)
        return AdoptTakeover(None, None, refusal)
    rebound = rebind_instance(
        conn, row_id=int(owner["id"]), socket=socket, name=name, epoch=epoch, tmux_session_id=tmux_session_id,
        working_dir=working_dir, lifecycle_source=lifecycle_source, now=now,
    )
    if not rebound.rebound:
        return AdoptTakeover(None, None, rebound.detail or rebound.outcome)
    logger.info("adopt_took_over_retired_row", tmux_name=name, tmux_created_epoch=epoch, row_id=int(owner["id"]),
                session_uuid=rebound.session_uuid, claude_session_uuid=claude_uuid,
                note="the adopted pane resumed a stopped row's conversation, so that row moved onto it; none minted")
    return AdoptTakeover(int(owner["id"]), rebound.session_uuid, "retired owner moved onto the live instance",
                         previous_tmux_name=owner.get("tmux_name"))


def take_over_for_adoption(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    epoch: int,
    live: Mapping[str, Any],
    listing: TmuxListing,
    correlation: "LadderResult",
    working_dir: Optional[str],
    lifecycle_source: str,
    confirm_refusal: Optional[str] = NOT_CONFIRMED,
    now: Optional[str] = None,
) -> Tuple[Mapping[str, Any], Optional[str]]:
    if correlation.method != LADDER_METHOD_PANE_ARGV or confirm_refusal is not None:
        logger.info("adopt_takeover_declined", tmux_name=name, claude_session_uuid=correlation.claude_session_uuid,
                    method=correlation.method,
                    reason=confirm_refusal if correlation.method == LADDER_METHOD_PANE_ARGV
                    else "only a conversation named by the pane's own argv may move a row")
        return {}, None
    try:
        taken = take_over_retired_owner(
            conn, socket=socket, name=name, epoch=epoch, claude_uuid=correlation.claude_session_uuid,
            listing=listing, tmux_session_id=live.get("tmux_session_id"), working_dir=working_dir,
            lifecycle_source=lifecycle_source, now=now, method=correlation.method,
        )
    except sqlite3.Error as exc:
        logger.warning("adopt_takeover_failed", tmux_name=name, tmux_socket=socket, error=str(exc))
        return {}, None
    if not taken.took_over:
        return {}, None
    return get_instance(conn, socket=socket, name=name, epoch=epoch) or {}, taken.previous_tmux_name


def confirm_for_takeover(
    listing: Optional[TmuxListing],
    *,
    name: str,
    correlation: Optional["LadderResult"],
    working_dir: Optional[str],
    pane_pid: Optional[int],
) -> Optional[str]:
    from src.core.session_adopt_persist import find_live_instance
    from src.core.sessions.adopt_confirm import confirm_pane_conversation

    if listing is None or not listing.ok or correlation is None or correlation.method != LADDER_METHOD_PANE_ARGV:
        return NOT_CONFIRMED
    live = find_live_instance(listing, name)
    try:
        epoch = int((live or {}).get("created_at_epoch"))
    except (TypeError, ValueError):
        return NOT_CONFIRMED
    try:
        return confirm_pane_conversation(
            name=name, epoch=epoch, claude_uuid=correlation.claude_session_uuid or "",
            working_dir=(live or {}).get("working_dir") or working_dir, pane_pid=pane_pid,
        )
    except CONFIRM_ERRORS as exc:
        logger.warning("adopt_confirm_failed", tmux_name=name, error=str(exc), error_type=type(exc).__name__)
        return "the pane's conversation could not be confirmed (%s)" % type(exc).__name__
