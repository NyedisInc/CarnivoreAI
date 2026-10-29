"""First-run import of sessions into cloude.db (design doc section 5.3).

THE MOST DANGEROUS CODE IN THIS SUBSYSTEM, AND WHY.

``meta.imported_from_json_at`` is a ONE-WAY LATCH over an input that
disappears. Once it is stamped, this import never runs again on that
install, ever. The live tmux session list it reads is not a file we can
go back to - it is a process table, and by tomorrow it is different.

So the failure mode is not "an error". It is SILENCE. If the tmux probe
fails and the latch is stamped anyway, the user boots to an empty RECENT
list, sees no error, and the import NEVER RETRIES. His session history is
permanently gone while every screen looks correct. The JSON files still
sit on disk and nothing ever reads them again.

THE RULE THAT PREVENTS IT, stated once so it can be checked:

    THE LATCH IS STAMPED ONLY ON THE ``listing.ok is True`` PATH.

THE LATCH IS TWO KEYS, NOT ONE, AND BOTH ARE GUARDED.

Both writes now live in :func:`_latch_sessions_stage`, which is called
from exactly one place: the last statement of the success path, textually
after the ``if not listing.ok`` guard returns. tests/test_session_import.py
walks this module's AST and asserts that neither key is written anywhere
outside that helper, that the helper has exactly one call site, and that
the call site is after the gate. A future edit that adds a second latch
write, or hoists this one above the guard, fails a test instead of
quietly costing a user his history.

WHAT A FAILED PROBE PRODUCES INSTEAD. Zero session rows, the latch left
unset, ``meta.session_import_pending_reason`` set to the probe's own
reason token, and a PENDING result the home screen renders as "session
import could not run because tmux could not be listed". The next start
retries. That is the third outcome: not pass, not fail, COULD NOT
EVALUATE - and it reaches the roll-up rather than being folded into
either neighbour.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

import structlog

from src.core.db import get_meta, set_meta
from src.core.db_models import (
    DEFAULT_TMUX_SOCKET,
    META_IMPORTED_FROM_JSON_AT,
    META_IMPORTED_FROM_JSON_RESULT,
    META_SESSION_IMPORT_PENDING_REASON,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_IMPORT,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.db_models import (
    META_SESSION_IMPORT_UNATTRIBUTED,
    SESSION_ORIGIN_CREATED,
)
from src.core.session_import_mapping import (
    attribute_working_dir,
    _merge_fields,
    _persisted_session_id,
    _project_roots,
    _row_fields,
    _stopped_epoch,
)
from src.core.session_identity import RECORD_INSERTED, record_instance
from src.core.session_import_evidence import gather, live_sessions_from
from src.core.session_import_ladder import (
    LADDER_OURS,
    REASON_COULD_NOT_EVALUATE,
    classify,
)
from src.core.session_import_promote import (
    PROMOTE_APPLIED,
    promote_to_created,
    reexaminable_instances,
)
from src.core.session_store import count_sessions, observed_origin_for
from src.core.tmux_listing import TmuxListing
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

IMPORT_COMPLETED = "completed"
IMPORT_ALREADY_DONE = "already_done"
IMPORT_PENDING_LISTING_UNAVAILABLE = "pending_listing_unavailable"
IMPORT_RERUN_COMPLETED = "rerun_completed"

RESULT_KEY_SESSIONS_STAGE = "sessions_imported_at"
RESULT_KEY_SESSIONS_DETAIL = "sessions_import_detail"

RESULT_KEY_SESSIONS_EVIDENCE_VERSION = "sessions_import_evidence_version"

EVIDENCE_LADDER_VERSION = 1


@dataclass(frozen=True)
class FirstRunImportResult:
    """What one :func:`run_first_run_import` call did, and what it could not.
    """

    outcome: str
    sessions_imported: int = 0
    listing_reason: Optional[str] = None
    refusals: List[Dict[str, Any]] = field(default_factory=list)
    unmatched: List[Dict[str, Any]] = field(default_factory=list)
    # could not
    unattributed: List[Dict[str, Any]] = field(default_factory=list)
    promoted: int = 0
    evidence_version: int = EVIDENCE_LADDER_VERSION

    @property
    def pending(self) -> bool:
        """True when the import could not run and MUST be retried.

        Inputs: none.
        Output: bool.
        """
        return self.outcome == IMPORT_PENDING_LISTING_UNAVAILABLE

    def home_screen_notice(self) -> Optional[str]:
        """The sentence the home screen shows when the import is pending.

        Description: names what could not be measured, per the
          three-outcome rule's fourth line. Returns None on every other
          outcome, so the presence of a notice means "act".
        Inputs: none.
        Output: str | None.
        Example:
          FirstRunImportResult(IMPORT_PENDING_LISTING_UNAVAILABLE,
                               listing_reason='timeout').home_screen_notice()
        """
        if not self.pending:
            return None
        reason = self.listing_reason or "unknown"
        return (
            "Session import is PENDING: tmux could not be listed "
            f"(reason: {reason}). No sessions were imported and none were "
            "lost. This retries automatically on the next start."
        )


class ImportLatchUnreadable(RuntimeError):
    pass


def _load_result_blob(conn: sqlite3.Connection) -> Dict[str, Any]:
    raw = get_meta(conn, META_IMPORTED_FROM_JSON_RESULT)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.error(
            "import_result_blob_unparseable",
            raw=raw[:200],
            error=str(exc),
            note=(
                "the once-only import latch record cannot be read, so "
                "whether the sessions stage has run CANNOT BE DETERMINED; "
                "refusing to proceed rather than re-running it and "
                "discarding the other stages' keys"
            ),
        )
        raise ImportLatchUnreadable(
            "meta.imported_from_json_result is present but unparseable; "
            "cannot determine whether the sessions import already ran"
        ) from exc
    if not isinstance(parsed, dict):
        logger.error(
            "import_result_blob_not_an_object",
            raw=raw[:200],
            parsed_type=type(parsed).__name__,
        )
        raise ImportLatchUnreadable(
            "meta.imported_from_json_result parsed to "
            f"{type(parsed).__name__}, expected a JSON object"
        )
    return parsed


def _merge_result_blob(conn: sqlite3.Connection, patch: Dict[str, Any]) -> None:
    blob = _load_result_blob(conn)
    blob.update(patch)
    set_meta(conn, META_IMPORTED_FROM_JSON_RESULT, json.dumps(blob, sort_keys=True))


def sessions_stage_done(conn: sqlite3.Connection) -> bool:
    return bool(_load_result_blob(conn).get(RESULT_KEY_SESSIONS_STAGE))


def sessions_stage_version(conn: sqlite3.Connection) -> Optional[int]:
    blob = _load_result_blob(conn)
    if not blob.get(RESULT_KEY_SESSIONS_STAGE):
        return None
    raw = blob.get(RESULT_KEY_SESSIONS_EVIDENCE_VERSION)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _latch_sessions_stage(
    conn: sqlite3.Connection, stamp: str, detail: Dict[str, Any]
) -> None:
    _merge_result_blob(
        conn,
        {
            RESULT_KEY_SESSIONS_STAGE: stamp,
            RESULT_KEY_SESSIONS_DETAIL: detail,
            RESULT_KEY_SESSIONS_EVIDENCE_VERSION: EVIDENCE_LADDER_VERSION,
        },
    )
    set_meta(conn, META_IMPORTED_FROM_JSON_AT, stamp)


def run_first_run_import(
    conn: sqlite3.Connection,
    *,
    listing: TmuxListing,
    owned_tmux_names: Optional[Set[str]] = None,
    persisted_sessions: Optional[Sequence[Dict[str, Any]]] = None,
    socket: str = DEFAULT_TMUX_SOCKET,
    now: Optional[str] = None,
    working_dir_probe: Optional[Callable[[str], Optional[str]]] = None,
    owned_set_readable: bool = True,
    log_dir: Optional[Path] = None,
    origin_probe: Optional[Callable[[str], Optional[str]]] = None,
) -> FirstRunImportResult:
    """Import live tmux sessions, once per install, ever.

    Description: design section 5.3, steps 2 through 8, with step 3 as the
      hard gate. Runs inside the caller's transaction, so a failure
      anywhere rolls the whole import back and - critically - leaves the
      latch unstamped, which is what makes the retry honest rather than a
      partial import wearing a completion badge.

      THE ORDER MATTERS AND IS NOT REARRANGEABLE:

        (there is no config-projects step any more. Projects are
                DB-only and any legacy config copy is retired once by
                ``projects_config_migration``, which main.py runs BEFORE
                this import so the projects table is settled before
                attribution in step 7 reads it.)
        step 3  THE GATE. ``listing.ok is False`` returns PENDING right
                here: zero session rows, latch untouched, reason
                recorded. Every statement below is unreachable on that
                path.
        step 4  one row per live tmux session, ``origin`` from
                :func:`session_store.observed_origin_for` - ``created``
                or ``observed``, never ``adopted``.
        step 5  persisted session metadata merged onto its live row by
                name, or imported ``stopped`` when nothing matches,
                which is what gives RECENT its first row.
        step 7  project attribution, deepest match, ``unknown`` when the
                cwd could not be probed.
        step 8  stamp the latch. The ONLY stamp site in this module.
    Inputs: conn (sqlite3.Connection) - caller owns the transaction.
      listing (TmuxListing) - ONE ``tmux list-sessions`` result; read
      ``ok`` before anything else. owned_tmux_names (set[str] | None) -
      the legacy ``SessionManager.owned_tmux_sessions``. persisted_sessions
      (Sequence[dict] | None) - entries from ``session_metadata.json``,
      each with at least ``tmux_session``. socket (str). now (str | None).
      working_dir_probe (callable | None) - name -> cwd, or None when it
      cannot answer; absent probe means every row without an inline
      ``working_dir`` gets attribution ``unknown``, never a guess.
    Output: FirstRunImportResult.
    Example: run_first_run_import(conn, listing=listing).outcome
    """
    stamp = now or utc_now()
    owned = set(owned_tmux_names or ())


    prior_version = sessions_stage_version(conn)
    if prior_version is not None and prior_version >= EVIDENCE_LADDER_VERSION:
        return FirstRunImportResult(
            outcome=IMPORT_ALREADY_DONE
        )

    # --- step 3: THE GATE ------------------------------------------------
    if not listing.ok:
        set_meta(
            conn,
            META_SESSION_IMPORT_PENDING_REASON,
            str(listing.reason or "unknown"),
        )
        logger.warning(
            "session_import_pending_listing_unavailable",
            listing_reason=listing.reason,
            listing_detail=listing.detail,
            sessions_imported=0,
            latch_stamped=False,
            note=(
                "imported_from_json_at deliberately left UNSET so the next "
                "start retries; importing an empty session list from a "
                "failed probe would destroy session history silently"
            ),
        )
        return FirstRunImportResult(
            outcome=IMPORT_PENDING_LISTING_UNAVAILABLE,
            sessions_imported=0,
                listing_reason=listing.reason,
        )

    roots = _project_roots(conn)
    live = live_sessions_from(_row_fields(raw) for raw in listing.sessions)
    evidence = gather(
        conn,
        live_names=[s.tmux_name for s in live],
        owned_tmux_names=(sorted(owned) if owned_set_readable else None),
        log_dir=log_dir,
        project_roots=tuple(roots),
        origin_probe=origin_probe,
    )
    ladder = classify(live, evidence)
    verdict_by_name = {v.tmux_name: v for v in ladder.verdicts}

    if prior_version is not None:
        return _rerun_promote_only(
            conn,
            ladder=ladder,
            socket=socket,
            stamp=stamp,
            prior_version=prior_version,
            listing=listing,
        )

    persisted_by_name = {
        str(entry.get("tmux_session")): entry
        for entry in (persisted_sessions or ())
        if entry.get("tmux_session")
    }
    matched_names: Set[str] = set()
    refusals: List[Dict[str, Any]] = []
    imported = 0

    for raw in listing.sessions:
        row = _row_fields(raw)
        name = row.get("name")
        if not name:
            continue
        epoch = row["tmux_created_epoch"]
        working_dir = row.get("working_dir")
        if working_dir is None and working_dir_probe is not None:
            working_dir = working_dir_probe(name)
        project_id, attribution = attribute_working_dir(working_dir, roots)

        extra = _merge_fields(persisted_by_name.get(name))
        if name in persisted_by_name:
            matched_names.add(name)

        verdict = verdict_by_name.get(name)
        if verdict is not None and verdict.verdict == LADDER_OURS:
            row_origin = SESSION_ORIGIN_CREATED
            row_source = f"{SESSION_LIFECYCLE_SOURCE_IMPORT}:{verdict.reason}"
        else:
            row_origin = observed_origin_for(name, owned)
            row_source = SESSION_LIFECYCLE_SOURCE_IMPORT

        result = record_instance(
            conn,
            socket=socket,
            name=name,
            epoch=epoch,
            origin=row_origin,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            lifecycle_source=row_source,
            session_id=row.get("tmux_session_id"),
            now=stamp,
            project_id=project_id,
            project_attribution=attribution,
            working_dir=working_dir,
            **extra,
        )
        if result.refused:
            refusals.append(
                {
                    "tmux_socket": socket,
                    "tmux_name": name,
                    "tmux_created_epoch": epoch,
                    "detail": result.detail,
                }
            )
        elif result.outcome == RECORD_INSERTED:
            imported += 1

    unmatched: List[Dict[str, Any]] = []
    for name, entry in persisted_by_name.items():
        if name in matched_names:
            continue
        unmatched.append({"tmux_session": name, "reason": "no_live_tmux_row"})
        result = record_instance(
            conn,
            socket=socket,
            name=name,
            epoch=_stopped_epoch(entry),
            origin=observed_origin_for(name, owned),
            lifecycle=SESSION_LIFECYCLE_STOPPED,
            lifecycle_source=SESSION_LIFECYCLE_SOURCE_IMPORT,
            session_id=_persisted_session_id(entry),
            now=stamp,
            project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
            **_merge_fields(entry),
        )
        if result.outcome == RECORD_INSERTED:
            imported += 1

    unattributed = ladder.unattributed_records()
    set_meta(
        conn,
        META_SESSION_IMPORT_UNATTRIBUTED,
        json.dumps(unattributed, sort_keys=True),
    )

    _latch_sessions_stage(
        conn,
        stamp,
        {
            "sessions_imported": imported,
            "epoch_collisions_refused": refusals,
            "persisted_without_live_tmux": unmatched,
            "listing_reason": listing.reason,
            "ladder_ours": len(ladder.ours),
            "ladder_unknown_no_evidence": len(ladder.unknown_no_evidence),
            "ladder_unknown_could_not_evaluate": len(ladder.unknown_unevaluated),
        },
    )
    logger.info(
        "session_import_completed",
        sessions_imported=imported,
        refusals=len(refusals),
        total_rows=count_sessions(conn),
    )
    return FirstRunImportResult(
        outcome=IMPORT_COMPLETED,
        sessions_imported=imported,
        listing_reason=listing.reason,
        refusals=refusals,
        unmatched=unmatched,
        unattributed=unattributed,
    )


def _rerun_promote_only(
    conn: sqlite3.Connection,
    *,
    ladder: Any,
    socket: str,
    stamp: str,
    prior_version: int,
    listing: TmuxListing,
) -> FirstRunImportResult:
    eligible = reexaminable_instances(conn, socket=socket)
    promoted = 0
    promoted_names = set()
    for verdict in ladder.ours:
        if verdict.epoch is None:
            continue
        if (verdict.tmux_name, int(verdict.epoch)) not in eligible:
            continue
        outcome = promote_to_created(
            conn,
            socket=socket,
            name=verdict.tmux_name,
            epoch=verdict.epoch,
            now=stamp,
            lifecycle_source=(
                f"{SESSION_LIFECYCLE_SOURCE_IMPORT}:rerun:{verdict.reason}"
            ),
        )
        if outcome == PROMOTE_APPLIED:
            promoted += 1
            promoted_names.add(verdict.tmux_name)

    still_eligible = reexaminable_instances(conn, socket=socket)
    unattributed = [
        rec
        for rec in ladder.unattributed_records()
        if rec["tmux_name"] not in promoted_names
        and rec.get("epoch") is not None
        and (rec["tmux_name"], int(rec["epoch"])) in still_eligible
    ]
    set_meta(
        conn,
        META_SESSION_IMPORT_UNATTRIBUTED,
        json.dumps(unattributed, sort_keys=True),
    )
    _latch_sessions_stage(
        conn,
        stamp,
        {
            "rerun_from_evidence_version": prior_version,
            "promoted": promoted,
            "still_unattributed": len(unattributed),
            "listing_reason": listing.reason,
        },
    )
    logger.info(
        "session_import_rerun_completed",
        from_version=prior_version,
        to_version=EVIDENCE_LADDER_VERSION,
        promoted=promoted,
        still_unattributed=len(unattributed),
    )
    return FirstRunImportResult(
        outcome=IMPORT_RERUN_COMPLETED,
        sessions_imported=0,
        listing_reason=listing.reason,
        unattributed=unattributed,
        promoted=promoted,
    )
