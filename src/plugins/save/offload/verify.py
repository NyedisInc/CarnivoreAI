
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Tuple

import structlog

from src.plugins.save.vault import restore
from src.plugins.save.vault.chunks import BlobStore
from src.plugins.save.vault.manifest import FileEntry, Manifest
from src.plugins.save.vault.units import UnitPlan
from src.plugins.sdk.transcript_files import dataless

logger = structlog.get_logger()


class VerifyFailed(RuntimeError):

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Verified:

    point_id: str
    manifest_sha256: str
    files: int
    bytes: int
    stats: Mapping[Path, Tuple[int, int]]


def manifest_digest(manifest: Manifest) -> str:
    digest = hashlib.sha256()
    for entry in sorted(manifest.files, key=lambda e: (e.home, e.rel)):
        digest.update(f"{entry.home}\0{entry.rel}\0{entry.length}\0{entry.sha256}\n".encode("utf-8"))
    return digest.hexdigest()


def verify_conversation(blobs: BlobStore, plan: UnitPlan, point: Manifest) -> Verified:
    held: Dict[Tuple[str, str], FileEntry] = {(e.home, e.rel): e for e in point.files}
    wanted = {(f.home, f.rel): f for f in plan.files}
    if point.main() is None:
        raise VerifyFailed("the vault point has no main transcript")
    if set(held) != set(wanted):
        raise VerifyFailed(f"the files on disk are not the files of the vault point ({len(wanted)} on disk, {len(held)} in the point)")
    total = 0
    stats: Dict[Path, Tuple[int, int]] = {}
    for key, planned in sorted(wanted.items()):
        entry = held[key]
        if entry.torn_bytes:
            raise VerifyFailed(f"{planned.rel}: the vault left out a torn last line, so it does not hold the whole file")
        try:
            info = os.lstat(planned.path)
        except OSError as exc:
            raise VerifyFailed(f"{planned.rel}: cannot be read ({exc.strerror or exc})") from exc
        if dataless.is_dataless_stat(info):
            raise VerifyFailed(f"{planned.rel}: is an iCloud placeholder, not a file on this disk")
        try:
            restore.verify_entry(blobs, entry)
        except restore.RestoreError as exc:
            raise VerifyFailed(f"the vault copy of {planned.rel} is damaged: {exc}") from exc
        if not restore.file_matches(planned.path, entry):
            raise VerifyFailed(f"{planned.rel}: the file on disk does not match the vault point")
        total += info.st_size
        stats[Path(planned.path)] = (info.st_size, info.st_mtime_ns)
    logger.info("offload_verified", conversation_id=plan.unit, point_id=point.point_id, files=len(wanted), bytes=total)
    return Verified(point.point_id, manifest_digest(point), len(wanted), total, stats)
