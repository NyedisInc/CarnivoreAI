
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.core.db_rename.legacy import migrate_legacy_db
from src.core.db import (
    DatastoreUnreadableError,
    connect,
    db_path_for,
    get_schema_version,
    table_exists,
    transaction,
)
from src.core.db_integrity_gate import boot_integrity_verdict
from src.core.db_backup import prune_backups, take_backup
from src.core.db_version_gate import resolve_startable_version
from src.core.db_schema_audit import (
    AUDIT_CANNOT_DETERMINE,
    AUDIT_MISSING,
    audit_schema,
    repair_after_chain,
    repair_missing,
)
from src.core.db_steps import run_chain
from src.core.db_models import (
    CURRENT_SCHEMA_VERSION,
    TRAIL_STATUS_COMPLETED,
    TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT,
    TRAIL_STATUS_FAILED,
)
from src.core.db_state import (
    CANNOT_DETERMINE,
    STATUS_DEGRADED_BACKUP_UNVERIFIED,
    STATUS_DEGRADED_DB_UNREADABLE,
    STATUS_DEGRADED_MIGRATION_FAILED,
    STATUS_DEGRADED_SCHEMA_AHEAD,
    STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE,
    STATUS_OK,
    STATUS_PAUSED_TRAIL_UNREADABLE,
    TRAIL_STATUS_ABSENT,
    TRAIL_STATUS_INTERRUPTED,
    TRAIL_STATUS_OK,
    TRAIL_STATUS_UNREADABLE,
    DatastoreState,
)
from src.core.migration_trail import (
    TRAIL_READ_ABSENT,
    TRAIL_READ_TRUNCATED_TAIL,
    TRAIL_READ_UNREADABLE,
    MigrationTrail,
    TrailEntry,
    TrailReadResult,
    find_unclosed,
    prior_interrupt_uuid,
    utc_now,
)

logger = structlog.get_logger()

KIND_BOOTSTRAP = "bootstrap"
KIND_SCHEMA = "schema"


def _resolve_trail(trail: MigrationTrail) -> tuple:
    read = trail.read()
    if read.status == TRAIL_READ_UNREADABLE:
        logger.error(
            "migration_trail_unreadable",
            line=read.corrupt_line_no,
            error=read.error,
        )
        return read, [], TRAIL_STATUS_UNREADABLE

    unclosed = find_unclosed(read.entries)
    for entry in unclosed:
        try:
            trail.mark_interrupted(entry)
        except OSError as exc:
            logger.error("migration_trail_interrupt_write_failed", error=str(exc))
            break
        logger.warning(
            "migration_step_interrupted",
            entry_uuid=entry.entry_uuid,
            kind=entry.kind,
            from_version=entry.from_version,
            to_version=entry.to_version,
        )

    if unclosed:
        status = TRAIL_STATUS_INTERRUPTED
    elif read.status == TRAIL_READ_ABSENT:
        status = TRAIL_STATUS_ABSENT
    elif read.status == TRAIL_READ_TRUNCATED_TAIL:
        status = TRAIL_STATUS_INTERRUPTED
    else:
        status = TRAIL_STATUS_OK
    return read, unclosed, status


def reconcile_mirror(conn: sqlite3.Connection, read: TrailReadResult) -> int:
    if not table_exists(conn, "migration_trail"):
        return 0
    latest: Dict[str, TrailEntry] = {}
    for entry in read.entries:
        latest[entry.entry_uuid] = entry
    written = 0
    for entry in latest.values():
        conn.execute(
            "INSERT INTO migration_trail (entry_uuid, kind, from_version, "
            "to_version, status, started_at, completed_at, backup_path, "
            "backup_verified, app_version, error, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entry_uuid) DO UPDATE SET "
            "kind=excluded.kind, from_version=excluded.from_version, "
            "to_version=excluded.to_version, status=excluded.status, "
            "started_at=excluded.started_at, "
            "completed_at=excluded.completed_at, "
            "backup_path=excluded.backup_path, "
            "backup_verified=excluded.backup_verified, "
            "app_version=excluded.app_version, error=excluded.error, "
            "detail=excluded.detail",
            entry.to_row(),
        )
        written += 1
    return written


def _last_migration_at(read: TrailReadResult) -> Optional[str]:
    stamps = [e.completed_at for e in read.entries if e.completed_at]
    return max(stamps) if stamps else None


def ensure_db_migrated(
    state_dir: Path,
    config_version: object = CANNOT_DETERMINE,
    app_version: Optional[str] = None,
) -> DatastoreState:
    state_dir = Path(state_dir)
    migrate_legacy_db(state_dir)
    db_path = db_path_for(state_dir)
    trail = MigrationTrail(state_dir)

    try:
        read, _interrupted, trail_status = _resolve_trail(trail)
    except OSError as exc:
        logger.error("migration_trail_resolve_failed", error=str(exc))
        read = TrailReadResult(status=TRAIL_READ_UNREADABLE, error=str(exc))
        trail_status = TRAIL_STATUS_UNREADABLE

    last_at = _last_migration_at(read)

    def _state(status: str, schema: object, message: str, **kw) -> DatastoreState:
        return DatastoreState(
            status=status,
            schema_version=schema,
            config_version=config_version,
            trail_status=trail_status,
            code_schema_version=CURRENT_SCHEMA_VERSION,
            message=message,
            last_migration_at=last_at,
            trail_corrupt_line=read.corrupt_line_no,
            db_path=str(db_path),
            fresh_install=is_fresh,
            **kw,
        )

    is_fresh = not db_path.exists() or db_path.stat().st_size == 0
    started: Optional[TrailEntry] = None

    if is_fresh and trail_status != TRAIL_STATUS_UNREADABLE:
        try:
            started = trail.open_step(
                KIND_BOOTSTRAP,
                "0",
                str(CURRENT_SCHEMA_VERSION),
                app_version=app_version,
                detail=(
                    f"state dir {state_dir} exists, cloude.db does not exist "
                    "yet - creating it"
                ),
            )
        except OSError as exc:
            return _state(
                STATUS_DEGRADED_DB_UNREADABLE,
                CANNOT_DETERMINE,
                "cloude.db was not created because its upgrade trail could "
                "not be written.",
                detail=f"could not append to {trail.path}: {exc}",
            )

    try:
        conn = connect(db_path, create=True)
    except DatastoreUnreadableError as exc:
        return _state(
            STATUS_DEGRADED_DB_UNREADABLE,
            CANNOT_DETERMINE,
            "cloude.db could not be opened. The app is running read-only "
            "and is NOT showing you an empty database as if it were your "
            "real one.",
            detail=str(exc),
        )

    with closing(conn):
        verdict = boot_integrity_verdict(state_dir, conn).verdict
        if verdict != "ok":
            return _state(
                STATUS_DEGRADED_DB_UNREADABLE,
                CANNOT_DETERMINE,
                "cloude.db failed its integrity check. The app is running "
                "read-only. Restore the most recent verified backup from "
                "the state directory.",
                detail=f"PRAGMA integrity_check: {verdict}",
            )

        gate = resolve_startable_version(conn)
        if gate.blocked:
            return _state(
                STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE,
                CANNOT_DETERMINE,
                gate.message,
                detail=gate.detail,
            )
        current = gate.version

        if current > CURRENT_SCHEMA_VERSION:
            return _state(
                STATUS_DEGRADED_SCHEMA_AHEAD,
                current,
                f"this install's data is at schema v{current}, this app "
                f"version only knows schema v{CURRENT_SCHEMA_VERSION} - "
                "restore the newer app version, or restore data to "
                f"v{CURRENT_SCHEMA_VERSION} via the trail. Running "
                "read-only until then; no data has been changed.",
                detail=(
                    f"meta.schema_version={current}, code "
                    f"CURRENT_SCHEMA_VERSION={CURRENT_SCHEMA_VERSION}. "
                    "Migrating backward is not attempted: this code was "
                    "never written to understand a newer schema."
                ),
            )

        if trail_status == TRAIL_STATUS_UNREADABLE:
            return _state(
                STATUS_PAUSED_TRAIL_UNREADABLE,
                current,
                "upgrade history could not be read (migration_trail.jsonl "
                f"is corrupt past line {read.corrupt_line_no}) - data is at "
                f"schema v{current} / config v{config_version} and is NOT at "
                "risk, but automatic migration is paused until this is "
                "resolved.",
                detail=read.error,
            )

        if current == CURRENT_SCHEMA_VERSION:
            _safe_reconcile(conn, read)
            prune_backups(state_dir)
            return _audit_and_repair(
                conn, current, trail, app_version, _state
            )

        if started is None:
            try:
                started = trail.open_step(
                    KIND_BOOTSTRAP if current == 0 else KIND_SCHEMA,
                    str(current),
                    str(CURRENT_SCHEMA_VERSION),
                    app_version=app_version,
                )
            except OSError as exc:
                return _state(
                    STATUS_DEGRADED_MIGRATION_FAILED,
                    current,
                    "the schema migration did not run because its trail "
                    "entry could not be written. Running read-only; no data "
                    "has been changed.",
                    detail=f"could not append to {trail.path}: {exc}",
                )

        backup_verified: Optional[int] = None
        backup_name: Optional[str] = None
        if current > 0:
            result = take_backup(db_path, state_dir, current)
            backup_name = result.basename
            backup_verified = 1 if result.verified else 0
            if not result.verified:
                _close(
                    trail, started, TRAIL_STATUS_FAILED,
                    backup_path=backup_name, backup_verified=backup_verified,
                    error=result.reason,
                )
                return _state(
                    STATUS_DEGRADED_BACKUP_UNVERIFIED,
                    current,
                    "the pre-migration backup could not be verified, so it "
                    "is treated as a backup that does not exist. The "
                    f"migration was ABORTED before touching anything - your "
                    f"data is intact at schema v{current}. Running "
                    "read-only.",
                    detail=result.reason,
                    backup_path=backup_name,
                    failed_entry_uuid=started.entry_uuid,
                )

        try:
            with transaction(conn):
                applied = run_chain(conn, current, CURRENT_SCHEMA_VERSION)
                applied += repair_after_chain(conn, CURRENT_SCHEMA_VERSION)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "db_migration_failed",
                from_version=current,
                to_version=CURRENT_SCHEMA_VERSION,
                entry_uuid=started.entry_uuid,
                error=str(exc),
            )
            _close(
                trail, started, TRAIL_STATUS_FAILED,
                backup_path=backup_name, backup_verified=backup_verified,
                error=f"{type(exc).__name__}: {exc}",
            )
            return _state(
                STATUS_DEGRADED_MIGRATION_FAILED,
                current,
                f"the schema v{current} to v{CURRENT_SCHEMA_VERSION} "
                "migration failed and was rolled back. Your data is intact "
                f"at schema v{current}. Running read-only.",
                detail=f"{type(exc).__name__}: {exc}",
                backup_path=backup_name,
                failed_entry_uuid=started.entry_uuid,
            )

        prior = prior_interrupt_uuid(read, started)
        close_status = (
            TRAIL_STATUS_COMPLETED_AFTER_INTERRUPT if prior else TRAIL_STATUS_COMPLETED
        )
        detail = (
            f"retried after interrupted entry {prior}" if prior else None
        )
        _close(
            trail, started, close_status,
            backup_path=backup_name, backup_verified=backup_verified,
            detail=detail,
        )

        _safe_reconcile(conn, trail.read())
        prune_backups(state_dir)

        logger.info(
            "db_migration_applied",
            applied=applied,
            entry_uuid=started.entry_uuid,
            status=close_status,
        )
        state = _state(
            STATUS_OK,
            CURRENT_SCHEMA_VERSION,
            f"datastore migrated to schema v{CURRENT_SCHEMA_VERSION}.",
            backup_path=backup_name,
        )
        state.migrations_applied = applied
        state.last_migration_at = utc_now()
        return state


def _audit_and_repair(
    conn: sqlite3.Connection,
    current: int,
    trail: MigrationTrail,
    app_version: Optional[str],
    _state,
) -> DatastoreState:
    audit = audit_schema(conn, current)
    if audit.status == AUDIT_CANNOT_DETERMINE:
        logger.warning(
            "db_schema_audit_cannot_determine",
            schema_version=current,
            error=audit.error,
            note=(
                "the objects behind this version were NOT verified. The "
                "app is running on the version's word alone"
            ),
        )
        return _state(
            STATUS_OK, current, f"datastore is current at schema v{current}."
        )
    if audit.status != AUDIT_MISSING:
        return _state(
            STATUS_OK, current, f"datastore is current at schema v{current}."
        )

    logger.error(
        "db_schema_audit_objects_missing",
        schema_version=current,
        missing=audit.missing_names,
        checked=audit.checked,
        note=(
            "meta.schema_version claims migrations that created no "
            "objects. This is the empty-reservation defect: a key "
            "crossed while it was a no-op is never revisited, because "
            "the version is already past it. Repairing from the "
            "migration steps' own DDL"
        ),
    )

    detail = (
        f"schema v{current} implied objects that were absent: "
        + ", ".join(audit.missing_names)
        + ". Re-applied their verbatim DDL from src/core/db_models.py. "
        "schema_version is UNCHANGED - the version was correct and the "
        "objects behind it were not."
    )
    started: Optional[TrailEntry] = None
    try:
        started = trail.open_step(
            KIND_SCHEMA,
            str(current),
            str(current),
            app_version=app_version,
            detail=detail,
        )
    except OSError as exc:
        logger.error("db_schema_repair_trail_unwritable", error=str(exc))

    try:
        with transaction(conn):
            created = repair_missing(conn, audit.missing)
    except sqlite3.DatabaseError as exc:
        logger.error(
            "db_schema_repair_failed",
            schema_version=current,
            missing=audit.missing_names,
            error=str(exc),
        )
        if started is not None:
            _close(
                trail,
                started,
                TRAIL_STATUS_FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        return _state(
            STATUS_DEGRADED_MIGRATION_FAILED,
            current,
            f"this database says schema v{current} but is missing objects "
            f"that version creates ({', '.join(audit.missing_names)}), and "
            "the automatic repair failed. Your data has NOT been changed. "
            "Running read-only.",
            detail=f"{type(exc).__name__}: {exc}",
        )

    logger.info(
        "db_schema_repaired",
        schema_version=current,
        created=created,
    )
    if started is not None:
        _close(trail, started, TRAIL_STATUS_COMPLETED, detail=detail)
    state = _state(
        STATUS_OK,
        current,
        f"datastore is current at schema v{current}.",
    )
    state.migrations_applied = [f"repair:{name}" for name in created]
    return state


def _close(trail: MigrationTrail, started: TrailEntry, status: str, **kw) -> None:
    try:
        trail.close_step(started, status, **kw)
    except OSError as exc:
        logger.error(
            "migration_trail_close_failed",
            entry_uuid=started.entry_uuid,
            status=status,
            error=str(exc),
        )


def _safe_reconcile(conn: sqlite3.Connection, read: TrailReadResult) -> None:
    try:
        with transaction(conn):
            reconcile_mirror(conn, read)
    except sqlite3.Error as exc:
        logger.warning("migration_trail_mirror_failed", error=str(exc))
