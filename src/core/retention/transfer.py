
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import structlog

from src.core.retention import constants as K
from src.core.retention.errors import CopyVerifyError, InsufficientSpaceError, ProtectedPathError, SourceChangedError

logger = structlog.get_logger()


def refuse_protected(path: Path) -> None:
    hit = next((part for part in path.parts if part in K.PROTECTED_NAMES), None)
    if hit is not None:
        raise ProtectedPathError(f"{path} is under protected name {hit!r}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(K.COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    n = 2
    while dest.with_name(f"{dest.stem}-{n}{dest.suffix}").exists():
        n += 1
    return dest.with_name(f"{dest.stem}-{n}{dest.suffix}")


def _copy_hashing(src: Path, partial: Path) -> str:
    digest = hashlib.sha256()
    with src.open("rb") as fin, partial.open("wb") as fout:
        for chunk in iter(lambda: fin.read(K.COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
            fout.write(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    return digest.hexdigest()


def move_file_verified(src: Path, dest: Path) -> Path:
    refuse_protected(src)
    before = src.stat()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(dest.parent).free < before.st_size + K.FREE_SPACE_MARGIN_BYTES:
        raise InsufficientSpaceError(f"{dest.parent} lacks room for {before.st_size} bytes")
    final = unique_destination(dest)
    partial = final.with_name(final.name + K.PARTIAL_SUFFIX)
    try:
        src_hash = _copy_hashing(src, partial)
        after = src.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise SourceChangedError(f"{src} changed while it was copied")
        if partial.stat().st_size != before.st_size or sha256_of(partial) != src_hash:
            raise CopyVerifyError(f"copy of {src} did not match its source")
        os.replace(partial, final)
    except (OSError, SourceChangedError, CopyVerifyError):
        partial.unlink(missing_ok=True)
        raise
    src.unlink()
    logger.info("retention_file_moved", source=str(src), dest=str(final), bytes=before.st_size)
    return final
