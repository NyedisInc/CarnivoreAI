"""Re-bind a row whose conversation died while its pane kept running.

  - ``registry_read.registry_for_session``'s conversation gate refuses the
    live record as :data:`~src.core.attention.registry_read.REG_STALE`, so
    the registry tier is discarded;
  - the transcript tier reads the file conversation A names, which stopped
    days ago or, for a phantom, never existed;
  - ``attention/side_effects._bind_conversation`` returned early on
    ``not record.known``, so the gate that broke the row was also what
    prevented the repair.

Four of fourteen live sessions were in exactly that state when it was
measured: row uuids 5.95, 7.44 and 16.4 days stale plus one with no
transcript at all, against registry conversations whose transcripts had
all been written that morning. Both readable tiers were blind, only
``unknown`` was reachable, and it could not self-heal.

THE RULE, AND WHY EVERY CLAUSE OF IT IS THERE. A rebind needs a POSITIVE,
MEASURED reading of the replacement, never an absence on the incumbent:

  1. The row's uuid and the registry's disagree. An agreement is the
     steady state and there is nothing to repair.
  2. The registry's conversation HAS A TRANSCRIPT ON DISK. This is the
     gotcha 5 guard and it is not optional: ``--fork-session`` mints a
     uuid whose transcript may never materialise, so a registry record
     naming a file that does not exist is a phantom and must never
     displace anything.
  3. AND EITHER the row's conversation has no transcript at all - a
     measured absence, which is the strongest form of this evidence
     because there is nothing to lose - OR the registry's transcript was
     appended to more recently than the row's by a CLEAR margin,
     :data:`REBIND_MARGIN_SECONDS`.

The margin exists because two files a single tick could have touched in
either order are not a dead conversation and a live one. Sixty seconds is
far longer than any interleaving of appends this app can cause and far
shorter than the multi-day gaps the live defect showed, so it separates the
case it is for without adjudicating the case it is not.

WHAT IT NEVER DOES. It never mints a hook token (``_mint_hook_token``
REPLACES what a running agent holds), never touches ``tmux_names``, never
changes the tmux name or the row id, and never deletes a row.

A conversation may now be taken from that row, and ONLY when
``session_conversation_takeover`` measures the row RETIRED: its stored
lifecycle is not ``running``, and its own tmux session is absent from a
COMPLETE listing of the socket. That gate speaks
``session_recreate_presence``'s three words and keeps its discipline -
only ``gone`` acts, ``present`` never does, ``unknown`` never does - and it
exists as its own module because the incumbent usually carries the LIVE
PANE'S OWN tmux name, where a name-scoped presence reading answers
``present`` for a row that has no pane. The release and the bind are TWO
STATEMENTS IN ONE TRANSACTION inside ``bind_correlated_uuid``, so no reader
ever sees two rows naming one conversation.

WHERE THE WRITE GOES. Through ``session_claude_correlate_bind``, the one
writer of this column outside the hook/lineage path, with ``replaces_uuid``
naming the exact incumbent this module measured. That writer owns the
unique-index check, the never-resurrect property and the anchor-only rule;
re-spelling any of them here would give the project two of each.

TRANSCRIPT PATHS ARE RESOLVED THE WAY THE RESOLVER RESOLVES THEM, through
``session_transcript_presence.conversation_presence``, which is the single
source of truth for how a uuid maps to a file: the working directory's own
LITERAL spelling for the fast path (gotcha 6) and a corpus scan as the
authority. No slug is re-derived here.

WHAT IT COSTS ON A TICK, STATED BECAUSE IT WAS WEIGHED. A mismatched row
pays one row read and up to two transcript lookups per pass. Both lookups
hit ``conversation_presence``'s single-stat fast path whenever the file is
in the row's own project directory, which is the case for every conversation
that exists; a uuid with NO file anywhere costs one scan of the corpus
root's immediate subdirectories, about 200 stats. That is bounded, and it
only persists while the row is in the broken state a rebind exists to end:
a successful rebind removes the mismatch on the next pass, and the one
lasting decline is a phantom registry uuid, which is rare. No throttle was
added, because a throttle would need a clock and would delay the repair for
the case the whole module is for.

NOTHING HERE RAISES. It runs on the attention tick, so every failure is a
named outcome the caller may log and ignore.
"""

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

# could not be read
# could not
REASON_UNMEASURED: str = "unmeasured"


REBIND_WROTE: str = "wrote"

REBIND_DECLINED: str = "declined"

# COULD NOT EVALUATE could not
REBIND_UNRESOLVED: str = "unresolved"


@dataclass(frozen=True)
class RebindDecision:

    rebind: bool

    reason: str

    # could not be read
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
    """Locate one conversation's transcript and read its mtime.

    Description: the location is
      ``session_transcript_presence.conversation_presence``, the single
      source of truth for how a uuid maps to a file, so no slug is
      re-derived here (gotcha 6). THREE ANSWERS, NOT TWO: a measured
      absence and a file whose mtime could not be read are different
      facts, and only the first may be acted on.
    Inputs:
      claude_uuid (str | None) - the conversation to look for.
      working_dir (str | None) - the row's directory, for the fast path.
      corpus_root (Path | None) - the transcript corpus; None uses the
        production default.
    Output: tuple[bool, float | None] - (measured, mtime). ``measured`` is
      False only when the corpus could not be searched or a located file
      could not be stat-ed; a measured absence is ``(True, None)``.
    Example: _transcript_mtime('abc', '/x', None) -> (True, 1789000000.0)
    """
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
    """List this socket's ``cloude_*`` sessions. NEVER RAISES.

    Description: the production reader behind ``listing_reader``, and the
      same throwaway-probe read ``recreate_routes._measure_presence``
      takes - ``discover_existing()``, which reports both ``ok`` (the
      probe RAN) and ``complete`` (its rows are the WHOLE answer). Nothing
      is spawned, adopted, attached or written.

      A handle that could not be built at all answers an UNAVAILABLE
      listing rather than raising, because this runs on the attention tick
      and ``unknown`` already refuses.
    Inputs: socket_name (str) - the tmux socket to list. name (str) - any
      session name; ``for_external`` needs one to build a handle and this
      call reads the whole socket regardless of it.
    Output: TmuxListing.
    Example: _socket_listing('cloude', 'cloude_a').ok  # True
    """
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
    socket = manager._tmux_socket_name()
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
