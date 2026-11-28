
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.retention import constants as K
from src.core.retention.archive import archive_matches, pack_bundle
from src.core.retention.drive import Drive
from src.core.retention.errors import ArchiveError, ProtectedPathError
from src.core.retention.paths import RetentionPaths
from src.core.retention.report import Action
from src.core.retention.transfer import refuse_protected

logger = structlog.get_logger()
TASK = "bundles"


def _bundle_roots(rollback_dir: Path) -> List[Path]:
    return [rollback_dir, rollback_dir / K.ROLLBACK_PACKED_SUBDIR]


def list_bundles(rollback_dir: Path) -> List[Path]:
    found = [p for root in _bundle_roots(rollback_dir) if root.is_dir() for p in root.iterdir()
             if p.name.endswith(K.BUNDLE_SUFFIX) and p.is_dir() and not p.is_symlink()]
    return sorted(found, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def plan(rollback_dir: Path, drive_root: Path, keep: int) -> List[Action]:
    archive_dir = drive_root.joinpath(*K.APP_ARCHIVE_DRIVE_DIR)
    return [Action(TASK, "archive_bundle", p, archive_dir / (p.name + K.ARCHIVE_SUFFIX), None,
                   detail=f"older than the newest {keep}; removed only after a verified archive exists")
            for p in list_bundles(rollback_dir)[max(keep, 0):]]


def _existing_verified(bundle: Path, drive: Drive) -> Optional[Path]:
    for parts in (K.APP_ARCHIVE_DRIVE_DIR, K.APP_EXPIRED_DRIVE_DIR):
        candidate = drive.folder(parts) / (bundle.name + K.ARCHIVE_SUFFIX)
        if candidate.is_file() and archive_matches(candidate, bundle):
            return candidate
    return None


def _remove_bundle(bundle: Path, paths: RetentionPaths) -> None:
    refuse_protected(bundle)
    if bundle.is_symlink() or bundle.parent not in _bundle_roots(paths.rollback_dir) or not bundle.name.endswith(K.BUNDLE_SUFFIX):
        raise ProtectedPathError(f"{bundle} is not a rollback bundle")
    shutil.rmtree(bundle)


def apply(action: Action, drive: Drive, paths: RetentionPaths) -> str:
    bundle = action.source
    existing = _existing_verified(bundle, drive)
    if existing is not None:
        archive, how = existing, "existing archive verified"
    else:
        out = drive.folder(K.APP_ARCHIVE_DRIVE_DIR) / (bundle.name + K.ARCHIVE_SUFFIX)
        if out.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = out.with_name(f"{bundle.name[:-len(K.BUNDLE_SUFFIX)]}-dup-{stamp}{K.BUNDLE_SUFFIX}{K.ARCHIVE_SUFFIX}")
        archive, how = pack_bundle(bundle, out), "packed and verified"
    if not archive.is_file():
        raise ArchiveError(f"archive {archive} vanished before the bundle was removed")
    _remove_bundle(bundle, paths)
    logger.info("retention_bundle_archived", bundle=bundle.name, archive=str(archive), how=how)
    return f"{how}: {archive}; bundle removed"
