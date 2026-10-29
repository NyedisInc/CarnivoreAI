
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import structlog

from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_REGISTRY

logger = structlog.get_logger()

REBIND_MARGIN_SECONDS: int = 60


REASON_MATCH: str = "uuid_matches"

REASON_NO_REGISTRY_CONVERSATION: str = "registry_names_no_conversation"

REASON_NO_ROW_CONVERSATION: str = "row_carries_no_conversation"

REASON_REGISTRY_TRANSCRIPT_MISSING: str = "registry_transcript_missing"

REASON_ROW_TRANSCRIPT_MISSING: str = "row_transcript_missing"

REASON_REGISTRY_TRANSCRIPT_NEWER: str = "registry_transcript_newer"

REASON_WITHIN_MARGIN: str = "within_margin"

REASON_UNMEASURED: str = "unmeasured"


REBIND_WROTE: str = "wrote"

REBIND_DECLINED: str = "declined"

REBIND_UNRESOLVED: str = "unresolved"


@dataclass(frozen=True)
class RebindDecision:

    rebind: bool

    reason: str

    row_transcript_mtime: Optional[float] = None

    registry_transcript_mtime: Optional[float] = None


@dataclass(frozen=True)
class RebindResult:

    outcome: str

    detail: str


def _transcript_mtime(
    claude_uuid: Optional[str],
    working_dir: Optional[str],
    corpus_root: Optional[Path],
) -> tuple[bool, Optional[float]]:
    from src.core.session_transcript_presence import (
        CONVERSATION_PRESENT,
        CONVERSATION_UNCHECKED,
        conversation_presence,
    )

    presence = conversation_presence(
        claude_uuid, working_dir=working_dir, corpus_root=corpus_root
    )
    if presence.outcome == CONVERSATION_UNCHECKED:
        return (False, None)
    if presence.outcome != CONVERSATION_PRESENT or presence.path is None:
        return (True, None)
    try:
        return (True, os.stat(presence.path).st_mtime)
    except OSError as exc:
        logger.debug(
            "conversation_rebind_mtime_unreadable",
            path=str(presence.path),
            error=str(exc),
        )
        return (False, None)


def decide_conversation_rebind(
    *,
    row_uuid: Optional[str],
    registry_uuid: Optional[str],
    working_dir: Optional[str] = None,
    corpus_root: Optional[Path] = None,
    margin_seconds: int = REBIND_MARGIN_SECONDS,
) -> RebindDecision:
    if not registry_uuid:
        return RebindDecision(False, REASON_NO_REGISTRY_CONVERSATION)
    if not row_uuid:
        return RebindDecision(False, REASON_NO_ROW_CONVERSATION)
    if row_uuid == registry_uuid:
        return RebindDecision(False, REASON_MATCH)

    registry_measured, registry_mtime = _transcript_mtime(
        registry_uuid, working_dir, corpus_root
    )
    if not registry_measured:
        return RebindDecision(False, REASON_UNMEASURED)
    if registry_mtime is None:
        return RebindDecision(False, REASON_REGISTRY_TRANSCRIPT_MISSING)

    row_measured, row_mtime = _transcript_mtime(row_uuid, working_dir, corpus_root)
    if not row_measured:
        return RebindDecision(
            False, REASON_UNMEASURED, registry_transcript_mtime=registry_mtime
        )
    if row_mtime is None:
        return RebindDecision(
            True,
            REASON_ROW_TRANSCRIPT_MISSING,
            registry_transcript_mtime=registry_mtime,
        )
    if registry_mtime - row_mtime > margin_seconds:
        return RebindDecision(
            True,
            REASON_REGISTRY_TRANSCRIPT_NEWER,
            row_transcript_mtime=row_mtime,
            registry_transcript_mtime=registry_mtime,
        )
    return RebindDecision(
        False,
        REASON_WITHIN_MARGIN,
        row_transcript_mtime=row_mtime,
        registry_transcript_mtime=registry_mtime,
    )


def _socket_listing(socket_name: str, name: str) -> Any:
    from src.config import settings
    from src.core.tmux_backend import TmuxBackend
    from src.core.tmux_listing import TmuxListing

    try:
        probe = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path(settings.default_working_dir).expanduser(),
            on_output=None,
            socket_name=socket_name,
        )
        return probe.discover_existing()
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning(
            "conversation_takeover_unmeasured",
            socket=socket_name,
            error=str(exc),
        )
        return TmuxListing.unavailable("probe_error", detail=str(exc))


def _row_to_take_from(
    conn: Any,
    *,
    session_id: str,
    socket: str,
    tmux_name: str,
    epoch: Optional[int],
    registry_uuid: str,
    listing_reader: Optional[Callable[[], Any]],
    pane_probe: Optional[Callable[[str, str, Optional[int]], Optional[bool]]],
) -> Optional[int]:
    from src.core.session_conversation_takeover import (
        REASON_INCUMBENT_IS_THE_LIVE_ROW,
        REASON_INCUMBENT_RUNNING,
        REASON_NAME_PRESENT,
        decide_conversation_takeover,
        probe_dead_instance_panes,
    )
    from src.core.session_lineage import row_for_claude_uuid
    from src.core.session_store import get_instance
    from src.core.tmux_backend import SESSION_PREFIX

    holder = row_for_claude_uuid(conn, registry_uuid)
    if holder is None:
        return None
    anchor = get_instance(conn, socket=socket, name=tmux_name, epoch=epoch)

    facts = {
        "incumbent_row_id": holder.get("id"),
        "incumbent_lifecycle": holder.get("lifecycle"),
        "incumbent_tmux_name": holder.get("tmux_name"),
        "live_row_id": None if anchor is None else anchor.get("id"),
        "live_tmux_name": tmux_name,
        "namespace_prefix": SESSION_PREFIX,
    }
    settled = decide_conversation_takeover(
        listing_ok=False, listing_complete=False, names=None, **facts
    )
    if settled.reason in (
        REASON_INCUMBENT_IS_THE_LIVE_ROW,
        REASON_INCUMBENT_RUNNING,
    ):
        logger.debug(
            "conversation_takeover_declined",
            session_id=session_id,
            tmux_name=tmux_name,
            reason=settled.reason,
        )
        return None

    listing = listing_reader() if listing_reader is not None else _socket_listing(
        socket, tmux_name
    )
    decision = decide_conversation_takeover(
        listing_ok=bool(getattr(listing, "ok", False)),
        listing_complete=bool(getattr(listing, "complete", False)),
        names=list(getattr(listing, "sessions", None) or []),
        **facts,
    )
    if decision.reason == REASON_NAME_PRESENT and bool(getattr(listing, "complete", False)):
        probe = pane_probe or probe_dead_instance_panes
        dead = probe(socket, str(holder.get("tmux_name") or ""), holder.get("tmux_created_epoch"))
        decision = decide_conversation_takeover(
            listing_ok=True, listing_complete=True,
            names=list(getattr(listing, "sessions", None) or []),
            incumbent_panes_dead=dead, **facts,
        )
    if not decision.may_take:
        logger.info(
            "conversation_takeover_declined",
            session_id=session_id,
            tmux_name=tmux_name,
            holding_row_id=holder.get("id"),
            outcome=decision.outcome,
            reason=decision.reason,
            detail=decision.detail,
        )
        return None
    logger.info(
        "conversation_takeover_measured",
        session_id=session_id,
        tmux_name=tmux_name,
        holding_row_id=holder.get("id"),
        live_row_id=facts["live_row_id"],
        claude_session_uuid=registry_uuid,
        outcome=decision.outcome,
        reason=decision.reason,
        detail=decision.detail,
    )
    row_id = holder.get("id")
    return None if row_id is None else int(row_id)


def _session_key(manager: Any, row_id: Optional[int]) -> Optional[str]:
    if row_id is None:
        return None
    conn = manager._writable_datastore_connection()
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (int(row_id),)).fetchone()
    except sqlite3.Error as exc:
        logger.warning("conversation_rebind_key_unreadable", row_id=row_id, error=str(exc), error_type=type(exc).__name__)
        return None
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def rebind_conversation_uuid(
    manager: Any,
    *,
    session_id: str,
    tmux_name: str,
    epoch: Optional[int],
    registry_uuid: Optional[str],
    corpus_root: Optional[Path] = None,
    listing_reader: Optional[Callable[[], Any]] = None,
    pane_probe: Optional[Callable[[str, str, Optional[int]], Optional[bool]]] = None,
) -> RebindResult:
    from src.core.db import transaction
    from src.cplugs.sdk import conversation_events
    from src.core.session_claude_correlate_bind import (
        BIND_REBOUND,
        bind_correlated_uuid,
    )
    from src.core.session_conversations import flip as conversation_flip
    from src.core.session_status_seed_read import read_instance_row

    if not tmux_name or epoch is None or not registry_uuid:
        return RebindResult(
            outcome=REBIND_UNRESOLVED,
            detail=(
                "a rebind needs a pane, an instance epoch and a conversation "
                "to bind, and one of the three was not known"
            ),
        )

    row = read_instance_row(manager, tmux_name, epoch, session_id=session_id)
    if row is None:
        return RebindResult(
            outcome=REBIND_UNRESOLVED,
            detail=(
                "no readable sessions row carries this tmux instance, so "
                "there is no conversation to replace"
            ),
        )

    row_uuid = row.get("claude_session_uuid")
    decision = decide_conversation_rebind(
        row_uuid=row_uuid,
        registry_uuid=registry_uuid,
        working_dir=row.get("working_dir"),
        corpus_root=corpus_root,
    )
    if not decision.rebind:
        logger.debug(
            "conversation_rebind_declined",
            session_id=session_id,
            tmux_name=tmux_name,
            reason=decision.reason,
        )
        return RebindResult(outcome=REBIND_DECLINED, detail=decision.reason)

    conn = manager._writable_datastore_connection()
    if conn is None:
        return RebindResult(
            outcome=REBIND_UNRESOLVED,
            detail="the datastore could not be opened to rebind the conversation",
        )
    socket = manager.tmux_socket_name()
    pending = conversation_flip.begin_flip(
        conn, socket=socket, tmux_name=tmux_name, epoch=epoch, previous_id=row_uuid,
        new_id=registry_uuid, working_dir=row.get("working_dir"), corpus_root=corpus_root,
    )
    try:
        takes_from = _row_to_take_from(
            conn,
            session_id=session_id,
            socket=socket,
            tmux_name=tmux_name,
            epoch=epoch,
            registry_uuid=registry_uuid,
            listing_reader=listing_reader,
            pane_probe=pane_probe,
        )
        with transaction(conn):
            bind = bind_correlated_uuid(
                conn,
                socket=socket,
                name=tmux_name,
                epoch=epoch,
                claude_uuid=registry_uuid,
                source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
                replaces_uuid=row_uuid,
                takes_from_row_id=takes_from,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "conversation_rebind_failed",
            session_id=session_id,
            tmux_name=tmux_name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return RebindResult(
            outcome=REBIND_UNRESOLVED,
            detail="the rebind write failed: %s" % exc,
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if bind.outcome != BIND_REBOUND:
        logger.info(
            "conversation_rebind_refused_by_writer",
            session_id=session_id,
            tmux_name=tmux_name,
            outcome=bind.outcome,
            detail=bind.detail,
        )
        return RebindResult(
            outcome=REBIND_UNRESOLVED,
            detail=bind.detail or bind.outcome,
        )

    conversation_flip.finish_flip(pending)
    session_key = _session_key(manager, bind.row_id)
    if session_key:
        conversation_events.publish_changed(session_key)
    logger.info(
        "conversation_rebound",
        session_id=session_id,
        tmux_name=tmux_name,
        row_id=bind.row_id,
        took_from_row_id=bind.took_from_row_id,
        previous_claude_session_uuid=row_uuid,
        claude_session_uuid=registry_uuid,
        previous_transcript_mtime=decision.row_transcript_mtime,
        registry_transcript_mtime=decision.registry_transcript_mtime,
        reason=decision.reason,
    )
    return RebindResult(outcome=REBIND_WROTE, detail=decision.reason)
