
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Iterable, Optional, Union

import structlog

from src.core.blobcodec.chunking import READ_BYTES

logger = structlog.get_logger()

PathLike = Union[str, "os.PathLike[str]"]


class PlaceConflict(FileExistsError):
    pass


class PlaceMismatch(ValueError):
    pass


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(READ_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def file_matches(dest: PathLike, sha256: str, length: int) -> bool:
    try:
        return os.path.getsize(dest) == length and sha256_file(dest) == sha256
    except OSError:
        return False


def place_no_clobber(temp: PathLike, dest: PathLike) -> None:
    try:
        os.link(temp, dest)
    except FileExistsError:
        raise PlaceConflict(str(dest)) from None
    except OSError as exc:
        if os.path.lexists(dest):
            raise PlaceConflict(str(dest)) from None
        logger.debug("place_no_hard_links", dest=str(dest), error=str(exc))
        os.rename(temp, dest)


def stage_verified(chunks: Iterable[bytes], dest: PathLike, *, length: int, sha256: str) -> Path:
    target = Path(dest)
    temp = target.parent / f".{target.name[:40]}.{secrets.token_hex(6)}.partial"
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    digest, total = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as out:
            for block in chunks:
                digest.update(block)
                total += len(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if total != length or digest.hexdigest() != sha256:
            raise PlaceMismatch(f"{target.name}: the bytes written do not match the expected length and sha256")
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp


def apply_metadata(target: PathLike, mode: int = 0o600, mtime_ns: Optional[int] = None) -> None:
    try:
        if mtime_ns is not None:
            os.utime(target, ns=(mtime_ns, mtime_ns))
        os.chmod(target, (mode & 0o777) or 0o600)
    except (OSError, OverflowError, ValueError) as exc:
        logger.debug("place_metadata_unsupported", dest=str(target), error=str(exc))


def write_verified(chunks: Iterable[bytes], dest: PathLike, *, length: int, sha256: str, mode: int = 0o600,
                   mtime_ns: Optional[int] = None) -> int:
    target = Path(dest)
    temp = stage_verified(chunks, target, length=length, sha256=sha256)
    try:
        place_no_clobber(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    apply_metadata(target, mode, mtime_ns)
    return length
