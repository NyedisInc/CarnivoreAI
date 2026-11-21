
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import structlog

from src.plugins.sdk.safe_io import connect_readonly

from src.plugins.reviewboard.public import links, responses

logger = structlog.get_logger()

OLD_FOLDER = "publicboard"
LADDERS: Dict[str, int] = {responses.DB_FILE: len(responses.MIGRATIONS), "links.db": len(links.MIGRATIONS)}
MARKER_DB = "links.db"
RECORD_FILE = "carried-from-publicboard.json"
TEMP_SUFFIX = ".carry"
PRIVATE_DIR, PRIVATE_FILE = 0o700, 0o600
BUSY_TIMEOUT_S = 5.0

Outcome = str


class CarryRefused(Exception):

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class CarryReport:

    outcome: Outcome
    reason: str = ""
    counts: Dict[str, int] = field(default_factory=dict)
    backup: Optional[Path] = None

    @property
    def moved(self) -> bool:
        return self.outcome == "moved"


def tables_of(path: Path) -> List[str]:
    with closing(connect_readonly(path, timeout=BUSY_TIMEOUT_S)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [row[0] for row in rows]


def count_rows(path: Path, tables: Sequence[str]) -> Dict[str, int]:
    with closing(connect_readonly(path, timeout=BUSY_TIMEOUT_S)) as conn:
        return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}


def user_version(path: Path) -> int:
    with closing(connect_readonly(path, timeout=BUSY_TIMEOUT_S)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def integrity_ok(path: Path) -> bool:
    with closing(connect_readonly(path, timeout=BUSY_TIMEOUT_S)) as conn:
        return conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def check_source(path: Path, newest: int) -> None:
    try:
        version = user_version(path)
        if version > newest:
            raise CarryRefused("unknown_schema_version", f"{path.name} is at {version}, this build knows up to {newest}")
        if not integrity_ok(path):
            raise CarryRefused("unreadable_source", f"{path.name} failed integrity_check")
    except sqlite3.OperationalError as exc:
        raise CarryRefused("source_busy" if "locked" in str(exc) else "unreadable_source", f"{path.name}: {exc}") from exc
    except sqlite3.DatabaseError as exc:
        raise CarryRefused("unreadable_source", f"{path.name}: {exc}") from exc


def online_copy(source: Path, target: Path) -> None:
    with closing(connect_readonly(source, timeout=BUSY_TIMEOUT_S)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
    os.chmod(target, PRIVATE_FILE)
    with open(target, "rb") as handle:
        os.fsync(handle.fileno())


def verify_copy(backup: Path, copy: Path) -> Dict[str, int]:
    tables = tables_of(backup)
    if not integrity_ok(copy) or user_version(copy) != user_version(backup) or tables_of(copy) != tables:
        raise CarryRefused("verification_failed", f"{copy.name} is not the same database as its backup")
    wanted, got = count_rows(backup, tables), count_rows(copy, tables)
    if wanted != got:
        raise CarryRefused("verification_failed", f"{copy.name} row counts differ: {wanted} vs {got}")
    return wanted


def _publish(stage: Dict[str, Path], new_dir: Path) -> None:
    for name in sorted(stage, key=lambda n: n == MARKER_DB):
        os.replace(stage[name], new_dir / name)
    fd = os.open(new_dir, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _newest_backup(new_dir: Path) -> Optional[Path]:
    found = sorted(new_dir.glob("carry-backup-*")) if new_dir.is_dir() else []
    return found[-1] if found else None


def _resume_from(new_dir: Path, clash: Sequence[str]) -> Optional[Path]:
    backup = _newest_backup(new_dir)
    if backup is None or MARKER_DB in clash or any(not (backup / name).is_file() for name in LADDERS):
        return None
    try:
        for name in clash:
            verify_copy(backup / name, new_dir / name)
    except (CarryRefused, sqlite3.Error, OSError):
        return None
    return backup


def _stage(names: Sequence[str], backup: Path, new_dir: Path, fresh_from: Dict[str, Path]) -> Dict[str, Path]:
    stage: Dict[str, Path] = {}
    for name in names:
        if name in fresh_from:
            online_copy(fresh_from[name], backup / name)
        stage[name] = new_dir / f"{name}{TEMP_SUFFIX}"
        shutil.copyfile(backup / name, stage[name])
        os.chmod(stage[name], PRIVATE_FILE)
        verify_copy(backup / name, stage[name])
    return stage


def _counts_of(new_dir: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name in LADDERS:
        path = new_dir / name
        if path.is_file():
            out.update({f"{name}:{table}": rows for table, rows in count_rows(path, tables_of(path)).items()})
            out[f"{name}:user_version"] = user_version(path)
    return out


def _run(old_dir: Path, new_dir: Path) -> CarryReport:
    sources = {name: old_dir / name for name in LADDERS if (old_dir / name).is_file()}
    if not sources:
        return CarryReport("nothing_to_carry")
    if (new_dir / RECORD_FILE).exists():
        return CarryReport("already_carried")
    if MARKER_DB not in sources:
        raise CarryRefused("links_db_missing", "the old folder holds responses.db but no links.db")
    clash = [name for name in sources if (new_dir / name).exists()]
    resumed = _resume_from(new_dir, clash) if clash else None
    if clash and resumed is None:
        raise CarryRefused("target_exists", f"{clash} already in {new_dir.name} without a finished carry; not overwriting")
    for name, path in sources.items():
        check_source(path, LADDERS[name])
    new_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(new_dir, PRIVATE_DIR)
    if resumed is None:
        backup = new_dir / f"carry-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        backup.mkdir(mode=PRIVATE_DIR)
    else:
        backup = resumed
    try:
        stage = _stage([n for n in sources if n not in clash], backup, new_dir, {} if resumed else sources)
    except (CarryRefused, sqlite3.Error, OSError):
        if resumed is None:
            shutil.rmtree(backup, ignore_errors=True)
        raise
    _publish(stage, new_dir)
    counts = _counts_of(new_dir)
    record = {"source": str(old_dir), "carried_at": datetime.now(timezone.utc).isoformat(), "counts": counts, "resumed": resumed is not None}
    (new_dir / RECORD_FILE).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(new_dir / RECORD_FILE, PRIVATE_FILE)
    shutil.rmtree(backup, ignore_errors=True)
    return CarryReport("moved", counts=counts, backup=backup)


def carry(old_dir: Path, new_dir: Path) -> CarryReport:
    try:
        report = _run(old_dir, new_dir)
    except CarryRefused as exc:
        _remove_temps(new_dir)
        logger.warning("reviewboard_public_carry_refused", reason=exc.reason, detail=exc.detail, source=str(old_dir), target=str(new_dir))
        return CarryReport("refused", reason=exc.reason)
    except (sqlite3.Error, OSError) as exc:
        _remove_temps(new_dir)
        logger.warning("reviewboard_public_carry_refused", reason="carry_failed", detail=f"{type(exc).__name__}: {exc}", source=str(old_dir), target=str(new_dir))
        return CarryReport("refused", reason="carry_failed")
    if report.moved:
        logger.info("reviewboard_public_carried", counts=report.counts, backup_removed=str(report.backup), source=str(old_dir), target=str(new_dir), source_kept=True)
    return report


def _remove_temps(new_dir: Path) -> None:
    for name in LADDERS:
        (new_dir / f"{name}{TEMP_SUFFIX}").unlink(missing_ok=True)
