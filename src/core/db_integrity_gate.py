"""The boot gate: may this start trust the cached integrity verdict?

This is the same move ``src/core/db_health.py`` already made when the
pragma came off ``GET /api/v1/version``, and it is made the same way: the
expensive walk stays a MAINTENANCE OPERATION on a schedule, and the
cheap path reads the verdict it produced.

THE ONE RULE. ONLY A POSITIVE, FRESH, ``ok`` VERDICT TAKEN ON THIS
DATABASE MAY SKIP THE PRAGMA. Everything else runs it. There is no rung
that trades a little safety for a little speed, because the two sides of
that trade are not comparable: skipping wrongly means migrating a corrupt
database or telling the user a corrupt one is sound, and running
needlessly costs 20 to 50 seconds of a startup that already happened.
Every refusal is therefore free, and the ladder is written to refuse on
anything it cannot positively establish.

THAT WAS A ONE-TIME COST AND IT WAS MEASURED SETTLING. The artifact it
wrote carries archive coverage, so the next boot skipped the pragma and
bound in 7 s, back to baseline. What remains is the DAILY check walking
the archive, roughly 20 s of disk once a day.

WHICH DATABASE THE VERDICT DESCRIBES. The artifact used to record only
``db_path``, which is derived from the state directory on both sides and
therefore always matches and proves nearly nothing: a restored file lands
at the same path. It now also records ``meta.install_id`` and the file's
size, following ``src/core/corpus_ingest_scan.py``, which already
invalidates its own cache on a changed ``install_id`` ("this is a
different or restored database") and on a counter going backwards. So the
gate checks three identity facts, and refuses on any of them:

  * ``db_path``       - the verdict is for the file being opened
  * ``install_id``    - the same logical install, not a different one
                        dropped in at that path. An artifact written
                        before this field existed carries None and is
                        REFUSED, which is why the first boot after this
                        ships still runs the pragma.
  * ``db_size_bytes`` - the file is not SMALLER than when it was
                        verified. SQLite does not shrink in normal
                        operation, so a smaller file has been replaced,
                        restored from an older backup, truncated or
                        VACUUMed. A VACUUM is the one false positive and
                        it costs exactly one slow boot.

A RECORDED FAILURE RUNS THE LIVE PRAGMA; IT DOES NOT SHORT-CIRCUIT. The
alternative - returning the degraded state straight from the cached
complaint - looks stricter and is worse: it makes a stale failure
permanent, so a user who restored a verified backup after a corruption
would boot read-only forever, with a cached verdict outranking a live
one. Running the pragma cannot be softer than today's behaviour, because
it IS today's behaviour: a genuinely corrupt file produces exactly the
same DatastoreState it always did.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional

import structlog

from src.core.corpus_ingest_state import (
    FRESHNESS_CANNOT_DETERMINE,
    FRESHNESS_NEVER_RAN,
    FRESHNESS_STALE,
)
from src.core.db import db_path_for, get_meta, integrity_check
from src.core.db_integrity import (
    RUN_FAILED,
    RUN_OK,
    SOURCE_BOOT,
    db_size_bytes,
    integrity_check_enabled,
    publish_run,
    read_verdict,
)
from src.core.db_integrity_pair import (
    VERDICT_OK as PAIR_OK,
    check_every_database,
    expected_databases,
    fold_pair,
)
from src.core.db_integrity_status import (
    VERDICT_FAILED,
    VERDICT_OK,
    VerdictReading,
    classify_record,
)
from src.core.db_models import META_INSTALL_ID

logger = structlog.get_logger()

PRAGMA_OK = "ok"

RUN_CHECKER_DISABLED = "checker_disabled"
RUN_NEVER_RAN = "never_ran"
RUN_FRESHNESS_CANNOT_DETERMINE = "freshness_cannot_determine"
RUN_STALE = "stale"
RUN_VERDICT_FAILED = "verdict_failed"
RUN_VERDICT_CANNOT_DETERMINE = "verdict_cannot_determine"
RUN_DB_PATH_MISMATCH = "db_path_mismatch"
RUN_INSTALL_ID_UNRECORDED = "install_id_unrecorded"
RUN_INSTALL_ID_MISMATCH = "install_id_mismatch"
RUN_DB_SHRANK = "db_smaller_than_verified"
RUN_PAIR_NOT_COVERED = "pair_not_covered"

SKIP_CACHED_OK = "cached_ok_current"

RUN_RUNGS = (
    RUN_CHECKER_DISABLED,
    RUN_NEVER_RAN,
    RUN_FRESHNESS_CANNOT_DETERMINE,
    RUN_STALE,
    RUN_VERDICT_FAILED,
    RUN_VERDICT_CANNOT_DETERMINE,
    RUN_DB_PATH_MISMATCH,
    RUN_INSTALL_ID_UNRECORDED,
    RUN_INSTALL_ID_MISMATCH,
    RUN_DB_SHRANK,
    RUN_PAIR_NOT_COVERED,
)


class BootIntegrityDecision(NamedTuple):

    skip_pragma: bool
    rung: str
    reason: str


class BootIntegrityResult(NamedTuple):

    verdict: str
    skipped: bool
    rung: str
    reason: str
    duration_seconds: float


def resolve_boot_integrity(
    *,
    enabled: bool,
    record: Optional[Dict[str, Any]],
    reading: VerdictReading,
    pair_verdict: str,
    pair_reason: str,
    db_path: Path,
    live_install_id: Optional[str],
    live_size_bytes: Optional[int],
) -> BootIntegrityDecision:
    if not enabled:
        return BootIntegrityDecision(
            False, RUN_CHECKER_DISABLED,
            "the background integrity checker is switched off, so nothing "
            "refreshes the cached verdict and it may not stand in for a "
            "live check",
        )
    if reading.verdict == VERDICT_FAILED:
        return BootIntegrityDecision(
            False, RUN_VERDICT_FAILED,
            "the last recorded integrity check FAILED, so this start "
            "re-measures rather than trusting either the failure or its age",
        )
    if record is None or reading.freshness == FRESHNESS_NEVER_RAN:
        return BootIntegrityDecision(
            False, RUN_NEVER_RAN,
            "no readable integrity verdict has ever been published in this "
            "state directory; never having looked is not evidence of "
            "soundness",
        )
    if reading.freshness == FRESHNESS_CANNOT_DETERMINE:
        return BootIntegrityDecision(
            False, RUN_FRESHNESS_CANNOT_DETERMINE,
            f"the cached verdict's age could not be measured: {reading.reason}",
        )
    if reading.freshness == FRESHNESS_STALE:
        return BootIntegrityDecision(
            False, RUN_STALE,
            f"the cached verdict is outside its freshness window: "
            f"{reading.reason}",
        )
    if reading.verdict != VERDICT_OK:
        return BootIntegrityDecision(
            False, RUN_VERDICT_CANNOT_DETERMINE,
            f"the cached record is not a verdict on the database: "
            f"{reading.reason}",
        )

    if pair_verdict != PAIR_OK:
        return BootIntegrityDecision(
            False, RUN_PAIR_NOT_COVERED,
            f"the cached record does not vouch for every database this "
            f"install has: {pair_reason}",
        )

    recorded_path = record.get("db_path")
    if str(recorded_path or "") != str(db_path):
        return BootIntegrityDecision(
            False, RUN_DB_PATH_MISMATCH,
            f"the cached verdict was taken on {recorded_path!r}, not on "
            f"{str(db_path)!r}",
        )

    recorded_install = record.get("install_id")
    if not recorded_install:
        return BootIntegrityDecision(
            False, RUN_INSTALL_ID_UNRECORDED,
            "the cached verdict does not record which install it was taken "
            "on, so it cannot be shown to describe this database",
        )
    if not live_install_id or str(recorded_install) != str(live_install_id):
        return BootIntegrityDecision(
            False, RUN_INSTALL_ID_MISMATCH,
            "the cached verdict was taken on a different install, or this "
            "database's install_id could not be read",
        )

    recorded_size = record.get("db_size_bytes")
    if not isinstance(recorded_size, int) or isinstance(recorded_size, bool):
        return BootIntegrityDecision(
            False, RUN_DB_SHRANK,
            "the cached verdict does not record the size of the file it "
            "verified, so a replacement could not be ruled out",
        )
    if live_size_bytes is None or live_size_bytes < recorded_size:
        return BootIntegrityDecision(
            False, RUN_DB_SHRANK,
            f"the database is now {live_size_bytes} bytes against "
            f"{recorded_size} when it was verified; SQLite does not shrink "
            "in normal operation, so this file has been replaced, restored, "
            "truncated or VACUUMed",
        )

    return BootIntegrityDecision(
        True, SKIP_CACHED_OK,
        f"a full integrity check on this database returned ok and is still "
        f"current: {reading.reason}",
    )


def live_install_id(conn: sqlite3.Connection) -> Optional[str]:
    try:
        return get_meta(conn, META_INSTALL_ID)
    except sqlite3.Error as exc:
        logger.warning("db_boot_install_id_unreadable", error=str(exc))
        return None


def boot_integrity_verdict(
    state_dir: Path,
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> BootIntegrityResult:
    db_path = db_path_for(state_dir)
    record = read_verdict(state_dir)
    reading = classify_record(record, now=now)
    pair = fold_pair(record, expected_databases(state_dir))
    install = live_install_id(conn)
    decision = resolve_boot_integrity(
        enabled=integrity_check_enabled(),
        record=record,
        reading=reading,
        pair_verdict=pair["verdict"],
        pair_reason=pair["reason"],
        db_path=db_path,
        live_install_id=install,
        live_size_bytes=db_size_bytes(db_path),
    )
    if decision.skip_pragma:
        logger.info(
            "db_boot_integrity_skipped",
            rung=decision.rung,
            checked_at=(record or {}).get("finished_at"),
            age_seconds=(
                None if reading.age_seconds is None
                else round(reading.age_seconds, 1)
            ),
            reason=decision.reason,
        )
        return BootIntegrityResult(
            verdict=PRAGMA_OK,
            skipped=True,
            rung=decision.rung,
            reason=decision.reason,
            duration_seconds=0.0,
        )

    started = time.monotonic()
    verdict = integrity_check(conn)
    parts = check_every_database(state_dir, verdict)
    elapsed = round(time.monotonic() - started, 3)
    publish_run(
        state_dir,
        RUN_OK if verdict == PRAGMA_OK else RUN_FAILED,
        db_path,
        started,
        None if verdict == PRAGMA_OK else verdict,
        install_id=install,
        source=SOURCE_BOOT,
        parts=parts,
    )
    # could not
    fresh = fold_pair(
        {"status": RUN_OK if verdict == PRAGMA_OK else RUN_FAILED,
         "detail": None if verdict == PRAGMA_OK else verdict,
         "db_path": str(db_path), "databases": parts},
        expected_databases(state_dir),
    )
    if fresh["verdict"] == PAIR_OK:
        answer = PRAGMA_OK
    elif verdict != PRAGMA_OK:
        answer = verdict
    else:
        # something else
        answer = fresh["reason"]
    logger.info(
        "db_boot_integrity_ran",
        rung=decision.rung,
        verdict_ok=fresh["verdict"] == PAIR_OK,
        pair_verdict=fresh["verdict"],
        databases=len(parts),
        duration_seconds=elapsed,
        reason=decision.reason,
    )
    return BootIntegrityResult(
        verdict=answer,
        skipped=False,
        rung=decision.rung,
        reason=decision.reason,
        duration_seconds=elapsed,
    )


__all__ = [
    "PRAGMA_OK",
    "RUN_CHECKER_DISABLED",
    "RUN_DB_PATH_MISMATCH",
    "RUN_DB_SHRANK",
    "RUN_FRESHNESS_CANNOT_DETERMINE",
    "RUN_INSTALL_ID_MISMATCH",
    "RUN_INSTALL_ID_UNRECORDED",
    "RUN_NEVER_RAN",
    "RUN_RUNGS",
    "RUN_STALE",
    "RUN_VERDICT_CANNOT_DETERMINE",
    "RUN_VERDICT_FAILED",
    "SKIP_CACHED_OK",
    "BootIntegrityDecision",
    "BootIntegrityResult",
    "boot_integrity_verdict",
    "live_install_id",
    "resolve_boot_integrity",
]
