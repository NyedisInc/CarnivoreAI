"""The REAPER: the only thing that moves a stored session to ``stopped``.

WHY THIS FILE EXISTS. Until now nothing in this app transitioned a
``sessions`` row from ``running`` to ``stopped`` when its tmux instance
actually died. The one-shot first-run import was the sole writer of
``lifecycle``, so every row it stamped ``running`` stayed ``running``
forever. The RECENT group (``lifecycle='stopped' AND archived_at IS
NULL``) was therefore correct code sitting over data that could never
arrive: on a real install, nine rows at ``running`` and a permanently
empty RECENT.

THE ONE RULE THAT MATTERS, STATED BEFORE ANYTHING ELSE.

A FAILED PROBE IS NOT EVIDENCE OF DEATH. ``TmuxListing`` with
``ok=False`` carries no rows BY CONTRACT - not because tmux has none.
Reaping against one would mark every session on the machine ``stopped``
the first time tmux hiccuped, and unlike a wrong screen a wrong row is
DURABLE: it survives the restart, it looks like a measurement, and
nothing downstream can tell it from a real one. That is the false-green
class this repo keeps re-finding, in its most expensive form - the
verdict nobody measured, written to disk.

So the ``ok`` gate is the first statement of the public entry point and
it returns before any connection is touched, and every line of SQL in
this module lives in a private function the gated branch cannot reach.
That is not stylistic: ``tests/test_session_lifecycle_reconcile.py``
proves the shape by AST, because a behavioural test can only sample the
branches it thought to try.

OK IS NOT THE SAME QUESTION AS COMPLETE, and absence-based logic needs
the second one. ``list_attachable_sessions`` refuses any tmux row it
cannot fully validate and carries on with the rest, so ONE malformed row
produces ``ok=True`` with a live session silently missing from the list.
Presence-based callers are unharmed. This one would conclude that the
missing session is dead - about a session that is alive - and write it
down. So an incomplete listing is refused as well, via
``TmuxListing.complete``, and so is a listing carrying any row whose
identity we cannot read (see :func:`live_instance_keys`). Neither is a
death. Both are a third outcome.

WHAT IT DOES, EXACTLY, AND NOTHING ELSE.

  Candidates   rows on THIS socket, ``lifecycle='running'``, carrying
               BOTH a ``tmux_name`` and a ``tmux_created_epoch``.
  Verdict      a candidate whose ``(name, epoch)`` pair is absent from a
               complete listing is ``stopped``, ``lifecycle_source =
               'tmux_missing'``.
  Written      ``lifecycle``, ``lifecycle_source``,
               ``lifecycle_checked_at``, ``updated_at``. Four columns.

MATCHING IS ON THE INSTANCE, NEVER ON THE NAME. The pair is
``(tmux_name, tmux_created_epoch)`` because a tmux NAME is not an
identity - names are reusable and this app re-mints them itself. Match
on the name alone and a dead ``cloude_work`` whose name a new session
has taken reads as still alive, and never falls to ``stopped`` at all.
That is the S4 identity work and this module does not get to weaken it.

THREE THINGS IT DELIBERATELY DOES NOT DO.

  IT NEVER WRITES ``unknown``. Tempting - ``lifecycle_source`` even has
  a ``probe_failed`` token sitting unused - and wrong. Stamping rows
  ``unknown`` when a probe fails would destroy a ``running`` value we
  DO believe, replace it with a state S9 renders with no RESTART
  control, and drop the whole machine into NEEDS ATTENTION, all from a
  transient tmux hiccup. "We could not look just now" is a fact about
  the PROBE, so it lives with the probe: ``ProbeHealth`` in memory, and
  the row's own ``lifecycle_checked_at`` for age. ``probe_failed``
  therefore stays unused ON PURPOSE - see
  ``test_probe_failed_source_is_never_written``, which pins that.

  IT NEVER PROMOTES, with ONE exception: a row it stopped itself on a
  measured dead pane (``lifecycle_source = 'pane_dead'``) returns to
  running when the same instance's pane is measured alive (#1365). Otherwise
  only ``running -> stopped``. A row already
  ``unknown`` is not moved to ``stopped`` just because it is absent:
  ``unknown`` means the row's liveness was never established, it is
  surfaced by ``session_store.needs_attention``, and quietly draining
  that group with a verdict about a row we never saw running is the
  same defect in the other direction. And a ``stopped`` row absent
  from tmux is already correct, so it is not rewritten - which is what
  makes a second identical reconcile write nothing at all.

  IT NEVER DELETES, AND NEVER TOUCHES ``archived_at``. The reaper
  ``session_store``'s docstring anticipates is a DELETE keyed on a
  retention window; this is not that and does not open the door to it.
  Archived rows ARE reconciled - an archived row stuck at ``running``
  is a stale claim like any other, and the measurement applies to it
  the same - but ``archived_at`` is not in the UPDATE's column list, so
  a reconciled archived row stays archived and can never surface in
  RECENT. Un-archiving is a user action, never a side effect of a
  probe.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_pane_death import (
    LIFECYCLE_SOURCE_PANE_DEAD,
    pane_death,
)
from src.core.session_respawn import PANE_ALIVE
from src.core.session_store import sessions_table_ready
from src.core.tmux_listing import TmuxListing
from src.core.trail_entry import utc_now
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()


RECONCILE_EVALUATED = "evaluated"

# did not answer
# nothing was written
RECONCILE_PROBE_UNAVAILABLE = "probe_unavailable"

RECONCILE_LISTING_INCOMPLETE = "listing_incomplete"

RECONCILE_NO_TABLE = "no_sessions_table"


@dataclass(frozen=True)
class ReconcileOutcome:
    """What one reconcile pass concluded, including concluding nothing.

    Description: three outcomes, not two. ``evaluated=False`` is its own
      state and never a flavour of "no changes" - "I looked and nothing
      had died" and "I could not look" are different facts and a caller
      that renders them the same has invented a measurement. The UI
      already has the vocabulary for the second one
      (``probe_unavailable`` / ``never_probed`` from S9) and this reuses
      those tokens rather than minting a parallel set.

    Attributes:
        outcome: one of the ``RECONCILE_*`` tokens above.
        evaluated: True only when the table was actually compared
            against a complete listing.
        stopped_uuids: ``session_uuid`` of every row moved to
            ``stopped``. Empty tuple on every non-evaluated outcome, and
            also on a healthy pass where nothing died - read
            ``evaluated`` to tell those apart.
        examined: how many candidate rows were compared. 0 when not
            evaluated.
        pane_dead_stopped: how many of ``stopped_uuids`` were reaped by
            the MEASURED-DEAD-PANE rung rather than by absence. Purely
            for the summary log line: the two rungs write the same four
            columns and differ only in ``lifecycle_source``, so a reader
            that does not care can ignore this entirely.
        reason: the listing's own reason token, when there is one.
        detail: human-readable text for the log line.
    """

    outcome: str
    evaluated: bool
    stopped_uuids: Tuple[str, ...] = field(default_factory=tuple)
    examined: int = 0
    pane_dead_stopped: int = 0
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.stopped_uuids)


def _not_evaluated(
    outcome: str, reason: Optional[str], detail: Optional[str]
) -> ReconcileOutcome:
    """Build the COULD NOT EVALUATE result, the only shape that branch has.

    Description: a named constructor so the refusal branches cannot
      accidentally differ from one another, and so nothing on them can
      grow a row count or a uuid list that would read as a measurement.
    Inputs: outcome (str) - a ``RECONCILE_*`` token. reason (str | None)
      - the listing's reason. detail (str | None) - human text.
    Output: ReconcileOutcome with ``evaluated=False`` and no rows.
    Example: _not_evaluated(RECONCILE_PROBE_UNAVAILABLE, 'timeout', None)
    """
    return ReconcileOutcome(
        outcome=outcome,
        evaluated=False,
        stopped_uuids=tuple(),
        examined=0,
        reason=reason,
        detail=detail,
    )


def live_instance_keys(rows: Sequence[Any]) -> Optional[Set[Tuple[str, int]]]:
    keys: Set[Tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        name = row.get("name")
        epoch = row.get("created_at_epoch")
        if not isinstance(name, str) or not name:
            return None
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            return None
        keys.add((name, int(epoch)))
    return keys


def rename_map(rows: Sequence[Any]) -> Dict[Tuple[int, str], str]:
    seen: Dict[Tuple[int, str], str] = {}
    ambiguous: Set[Tuple[int, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        epoch = row.get("created_at_epoch")
        sid = row.get("session_id")
        if not isinstance(name, str) or not name:
            continue
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            continue
        if not isinstance(sid, str) or not sid:
            continue
        key = (int(epoch), sid)
        if key in seen:
            ambiguous.add(key)
            continue
        seen[key] = name
    for key in ambiguous:
        seen.pop(key, None)
    return seen


def _running_candidates(
    conn: sqlite3.Connection, *, socket: str, host_key: str = LOCAL_HOST_KEY
) -> List[Dict[str, Any]]:
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT id, session_uuid, tmux_name, tmux_created_epoch, "
        "tmux_session_id, archived_at "
        f"FROM sessions WHERE tmux_socket = ?{scope_sql} AND lifecycle = ? "
        "AND tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, SESSION_LIFECYCLE_RUNNING),
    ).fetchall()
    return [dict(row) for row in rows]


def _reap_absent_instances(
    conn: sqlite3.Connection,
    *,
    listing: TmuxListing,
    socket: str,
    pane_status: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> ReconcileOutcome:
    live = live_instance_keys(listing.sessions)
    if live is None:
        # could not
        logger.warning(
            "session_lifecycle_listing_row_unidentifiable",
            tmux_socket=socket,
            note=(
                "a listing row carried no usable (name, epoch); refusing "
                "to reap, because a stored row matching that instance "
                "would look absent and be stopped while alive"
            ),
        )
        return _not_evaluated(
            RECONCILE_LISTING_INCOMPLETE,
            listing.reason,
            "a listing row carried no usable (name, epoch) identity",
        )

    candidates = _running_candidates(conn, socket=socket, host_key=host_key)
    stamp = now or utc_now()
    stopped: List[str] = []
    renamed = 0
    pane_dead_stopped = 0

    live_names = rename_map(listing.sessions)
    stored_by_key: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for row in candidates:
        sid = row.get("tmux_session_id")
        if isinstance(sid, str) and sid:
            key = (int(row["tmux_created_epoch"]), sid)
            stored_by_key.setdefault(key, []).append(row)

    for key, rows_for_key in stored_by_key.items():
        if len(rows_for_key) != 1:
            logger.warning(
                "session_rename_ambiguous",
                tmux_socket=socket,
                tmux_created_epoch=key[0],
                tmux_session_id=key[1],
                stored_rows=len(rows_for_key),
                note=(
                    "more than one stored row carries this discriminator; "
                    "no rename applied, both rows reconcile normally"
                ),
            )
            continue
        row = rows_for_key[0]
        live_name = live_names.get(key)
        if live_name is None or live_name == str(row["tmux_name"]):
            continue
        if (live_name, key[0]) in {
            (str(other["tmux_name"]), int(other["tmux_created_epoch"]))
            for other in candidates
            if other["id"] != row["id"]
        }:
            continue
        conn.execute(
            "UPDATE sessions SET tmux_name = ?, lifecycle_checked_at = ?, "
            "updated_at = ? WHERE id = ? AND lifecycle = ?",
            (
                live_name,
                stamp,
                stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_RUNNING,
            ),
        )
        logger.info(
            "session_renamed_in_place",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_created_epoch=key[0],
            tmux_session_id=key[1],
            old_name=row["tmux_name"],
            new_name=live_name,
            note=(
                "same epoch and same tmux id under a new name: one "
                "session relabelled. session_uuid, origin, pins, unread "
                "and lineage all ride on the row and are untouched"
            ),
        )
        row["tmux_name"] = live_name
        renamed += 1

    for row in candidates:
        key = (str(row["tmux_name"]), int(row["tmux_created_epoch"]))
        if key in live:
            death = pane_death(
                pane_status,
                str(row["tmux_name"]),
                int(row["tmux_created_epoch"]),
                backend_socket=socket,
            )
            if not death.dead:
                continue
            conn.execute(
                "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
                "lifecycle_checked_at = ?, updated_at = ? "
                "WHERE id = ? AND lifecycle = ?",
                (
                    SESSION_LIFECYCLE_STOPPED,
                    LIFECYCLE_SOURCE_PANE_DEAD,
                    stamp,
                    stamp,
                    int(row["id"]),
                    SESSION_LIFECYCLE_RUNNING,
                ),
            )
            stopped.append(str(row["session_uuid"]))
            pane_dead_stopped += 1
            logger.info(
                "session_lifecycle_reaped_pane_dead",
                session_id=int(row["id"]),
                session_uuid=row["session_uuid"],
                tmux_socket=socket,
                tmux_name=row["tmux_name"],
                tmux_created_epoch=int(row["tmux_created_epoch"]),
                archived=row.get("archived_at") is not None,
                lifecycle_source=LIFECYCLE_SOURCE_PANE_DEAD,
                pane_dead=death.pane_dead_raw,
                evidence=death.detail,
                note=(
                    "tmux still lists this session (remain-on-exit) but "
                    "measured its pane dead; the row moves to RECENT. The "
                    "tmux session itself is NOT killed - the husk holds "
                    "the pane's final screen. archived_at not written"
                ),
            )
            continue
        conn.execute(
            "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
            "lifecycle_checked_at = ?, updated_at = ? "
            "WHERE id = ? AND lifecycle = ?",
            (
                SESSION_LIFECYCLE_STOPPED,
                SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
                stamp,
                stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_RUNNING,
            ),
        )
        stopped.append(str(row["session_uuid"]))
        logger.info(
            "session_lifecycle_reaped",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_name=row["tmux_name"],
            tmux_created_epoch=int(row["tmux_created_epoch"]),
            archived=row.get("archived_at") is not None,
            lifecycle_source=SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
            note=(
                "instance absent from a complete tmux listing; "
                "archived_at deliberately not written"
            ),
        )

    revived = 0
    for row in _revivable_pane_dead_rows(
        conn, live=live, socket=socket, pane_status=pane_status,
        host_key=host_key,
    ):
        conn.execute(
            "UPDATE sessions SET lifecycle = ?, lifecycle_source = ?, "
            "lifecycle_checked_at = ?, updated_at = ? "
            "WHERE id = ? AND lifecycle = ? AND lifecycle_source = ?",
            (
                SESSION_LIFECYCLE_RUNNING,
                SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
                stamp, stamp,
                int(row["id"]),
                SESSION_LIFECYCLE_STOPPED,
                LIFECYCLE_SOURCE_PANE_DEAD,
            ),
        )
        revived += 1
        logger.info(
            "session_lifecycle_revived_pane_alive",
            session_id=int(row["id"]),
            session_uuid=row["session_uuid"],
            tmux_socket=socket,
            tmux_name=row["tmux_name"],
            tmux_created_epoch=int(row["tmux_created_epoch"]),
            lifecycle_source=SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
            note=(
                "same instance, pane measured alive after a pane_dead "
                "stop; the row returns to running"
            ),
        )

    return ReconcileOutcome(
        outcome=RECONCILE_EVALUATED,
        evaluated=True,
        stopped_uuids=tuple(stopped),
        examined=len(candidates),
        pane_dead_stopped=pane_dead_stopped,
        reason=listing.reason,
        detail=(f"renamed {renamed} row(s) in place" if renamed else None)
        if not revived
        else f"revived {revived} pane_dead row(s) whose pane is alive again",
    )


def _revivable_pane_dead_rows(
    conn: sqlite3.Connection,
    *,
    live: Set[Tuple[str, int]],
    socket: str,
    pane_status: Optional[Dict[str, Any]],
    host_key: str = LOCAL_HOST_KEY,
) -> List[Dict[str, Any]]:
    scope_sql, scope_params = host_scope(conn, host_key)
    rows = conn.execute(
        "SELECT id, session_uuid, tmux_name, tmux_created_epoch "
        f"FROM sessions WHERE tmux_socket = ?{scope_sql} AND lifecycle = ? "
        "AND lifecycle_source = ? AND tmux_name IS NOT NULL "
        "AND tmux_created_epoch IS NOT NULL",
        (socket, *scope_params, SESSION_LIFECYCLE_STOPPED,
         LIFECYCLE_SOURCE_PANE_DEAD),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        name, epoch = str(row["tmux_name"]), int(row["tmux_created_epoch"])
        if (name, epoch) not in live:
            continue
        verdict = pane_death(pane_status, name, epoch, backend_socket=socket)
        if verdict.outcome == PANE_ALIVE:
            out.append(dict(row))
    return out



def reconcile_from_listing(
    conn: sqlite3.Connection,
    *,
    listing: TmuxListing,
    socket: str,
    pane_status: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> ReconcileOutcome:
    """Move rows whose tmux instance is gone to ``stopped``, or refuse to.

    Description: the public entry point, and a sequence of refusals
      before any work. THE FIRST STATEMENT IS THE ``ok`` GATE and it
      returns without touching ``conn``, because a probe that could not
      answer is not evidence that anything died, and a lifecycle written
      from one is a durable lie. The gates, in order:

        ``not listing.ok``          the probe did not answer.
        ``not listing.complete``    it answered, but rows were refused,
                                    so absence proves nothing.
        no ``sessions`` table       pre-v2 database, nothing to do.

      Only past all three does :func:`_reap_absent_instances` - the only
      writer here - get called.

      ``pane_status`` is OPTIONAL and its absence is not a failure: with
      no pane listing the dead-pane rung simply never answers, and this
      function behaves exactly as it did before that rung existed. It is
      gated INSIDE ``pane_death`` rather than here, on its own
      completeness and its own socket, because the two listings are
      different probes and one being whole says nothing about the other.
    """
    if not listing.ok:
        return _not_evaluated(
            RECONCILE_PROBE_UNAVAILABLE, listing.reason, listing.detail
        )
    if not listing.complete:
        return _not_evaluated(
            RECONCILE_LISTING_INCOMPLETE,
            listing.reason,
            f"{listing.refused_rows} tmux row(s) were refused by the parser",
        )
    if not sessions_table_ready(conn):
        return _not_evaluated(RECONCILE_NO_TABLE, listing.reason, None)
    return _reap_absent_instances(
        conn,
        listing=listing,
        socket=socket,
        pane_status=pane_status,
        now=now,
        host_key=host_key,
    )
