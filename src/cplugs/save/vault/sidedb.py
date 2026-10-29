
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.ingest import Pacer, SourceError, ingest_file
from src.cplugs.save.vault.manifest import HOME_STATE, FileEntry

logger = structlog.get_logger()


class SnapshotFailed(SourceError):
    pass


def snapshot(source: Path, dest: Path) -> None:
    try:
        with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=30)) as live, \
                closing(sqlite3.connect(str(dest))) as copy:
            live.backup(copy, pages=-1)
            verdict = copy.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        dest.unlink(missing_ok=True)
        raise SnapshotFailed(f"online backup of {source.name} failed: {exc}") from exc
    if not verdict or verdict[0] != "ok":
        dest.unlink(missing_ok=True)
        raise SnapshotFailed(f"the copy of {source.name} failed its integrity check: {verdict}")


def ingest_databases(blobs: BlobStore, staging: Path, state_dir: Path, databases: Sequence[Tuple[str, Path]],
                     pace: Optional[Pacer] = None) -> List[FileEntry]:
    staging.mkdir(parents=True, exist_ok=True)
    entries: List[FileEntry] = []
    try:
        for name, path in databases:
            copy = staging / f"{len(entries)}-{name}"
            try:
                rel = path.relative_to(state_dir).as_posix()
            except ValueError:
                rel = name
            try:
                snapshot(path, copy)
                entry = ingest_file(blobs, copy, role=K.ROLE_SIDE_DB, home=HOME_STATE, rel=rel, pace=pace)
            except (SourceError, FileNotFoundError) as exc:
                logger.error("vault_side_database_skipped", database=name, error=str(exc))
                continue
            entry.source_path, entry.size_seen, entry.mtime_ns = str(path), -1, 0
            entry.mode = 0o600
            entries.append(entry)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return entries
