
from __future__ import annotations

import asyncio
import errno
import hashlib
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders, refs, service
from src.cplugs.crate.errors import CrateApiError, conflict, invalid
from src.cplugs.crate.publish import NameTaken, publish, sha_sidecar, write_new
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf

logger = structlog.get_logger()

_HEADROOM = 16 * 1024 * 1024


def check_name(name: str) -> None:
    if not K.UPLOAD_NAME_RE.match(name or "") or Path(name).name != name or ".." in name:
        raise invalid("bad_crate_name", "the file is not named like a crate (crate-...crate or crate-...crate.age)")


def check_sha(sha256: Optional[str]) -> Optional[str]:
    if not sha256 or not sha256.strip():
        return None
    text = sha256.strip().lower()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise invalid("bad_sha256", "the checksum is not 64 hex characters")
    return text


def _open_temp(temp: Path) -> int:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        return os.open(temp, flags, K.FILE_MODE)
    except FileExistsError as exc:
        try:
            stale = time.time() - temp.stat().st_mtime > K.UPLOAD_STALE_S
        except OSError:
            stale = False
        if not stale:
            raise conflict("upload_busy", "another upload of this file is in progress") from exc
        os.unlink(temp)
        return os.open(temp, flags, K.FILE_MODE)


def _prove(temp: Path, encrypted: bool, received: str, expected: Optional[str]) -> None:
    if expected is not None and received != expected:
        raise invalid("sha256_mismatch", "the file does not match its checksum; it was damaged on the way or is a different file")
    if encrypted:
        with open(temp, "rb") as handle:
            if handle.read(len(K.AGE_MAGIC)) != K.AGE_MAGIC:
                raise invalid("crate_unreadable", "the file is not an encrypted crate")
        return
    try:
        with cf.open_crate(temp):
            return
    except (cf.CrateError, OSError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        raise invalid("crate_unreadable", f"{code}: the file is not a crate this version can read") from exc


async def _stream_to(fd: int, body: AsyncIterator[bytes]) -> Tuple[int, str]:
    digest, total, pending = hashlib.sha256(), 0, bytearray()
    out = os.fdopen(fd, "wb")
    try:
        async for chunk in body:
            pending += chunk
            if len(pending) >= bc.READ_BYTES:
                block, pending = bytes(pending), bytearray()
                digest.update(block)
                total += len(block)
                await asyncio.to_thread(out.write, block)
        tail = bytes(pending)
        digest.update(tail)
        total += len(tail)

        def finish() -> None:
            out.write(tail)
            out.flush()
            os.fsync(out.fileno())

        await asyncio.to_thread(finish)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise CrateApiError(507, K.B_SPACE, "the folder's volume ran out of room") from exc
        raise
    finally:
        out.close()
    return total, digest.hexdigest()


def _prepare(ctx: Any, name: str, length: Optional[int]) -> Tuple[Path, Path]:
    env = service.env_of(ctx)
    try:
        folder = folders.resolve(env, K.FOLDER_PRIMARY)
    except folders.FolderUnavailable as exc:
        raise conflict(exc.code, exc.detail) from exc
    final = folder / name
    if os.path.lexists(final):
        raise conflict("name_taken", f"{name} is already in the crates folder; nothing was replaced")
    if length is not None and folders.free_bytes(folder) < length + _HEADROOM:
        raise CrateApiError(507, K.B_SPACE, "the crates folder's volume has no room for this file")
    return final, folder / f".{name}.partial"


def _place(temp: Path, final: Path, received: str, with_sidecar: bool) -> None:
    try:
        publish(temp, final)
    except NameTaken as exc:
        raise conflict("name_taken", f"{final.name} is already in the crates folder; nothing was replaced") from exc
    if with_sidecar:
        try:
            write_new(final.parent / f"{final.name}.sha256", sha_sidecar(received, final.name))
        except (NameTaken, OSError) as exc:
            os.unlink(final)
            raise conflict("sidecar_failed", f"the checksum file could not be written ({type(exc).__name__})") from exc


async def receive(ctx: Any, name: str, body: AsyncIterator[bytes], length: Optional[int] = None,
                  sha256: Optional[str] = None) -> Dict[str, Any]:
    check_name(name)
    expected = check_sha(sha256)
    final, temp = await asyncio.to_thread(_prepare, ctx, name, length)
    fd = await asyncio.to_thread(_open_temp, temp)
    try:
        size, received = await _stream_to(fd, body)
        await asyncio.to_thread(_prove, temp, name.endswith(".age"), received, expected)
        await asyncio.to_thread(_place, temp, final, received, expected is not None)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    logger.info("crate_uploaded", name=name, size=size, sidecar=expected is not None)
    ctx.notify("jobs", None)
    root = await asyncio.to_thread(refs.project_root_of, final)
    return {"name": name, "size": size, "sha256": received, "sidecar": expected is not None, "project_root": root}
