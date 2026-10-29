
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.trail_entry import utc_now

logger = structlog.get_logger()

CHUNK_BYTES = 1024 * 1024
STALE_SECONDS = 24 * 3600.0
MAX_BLOB_BYTES = 8 * 1024 ** 3
MAX_PEER_INBOX_BYTES = 16 * 1024 ** 3
MAX_TOTAL_INBOX_BYTES = 32 * 1024 ** 3
KINDS = ("bundle", "tar", "transcripts", "memory", "manifest")
BLOB_PATH = "/federation/pack/blobs"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
Request = Callable[..., Awaitable[Tuple[int, Any]]]


class BlobError(Exception):

    def __init__(self, code: str, status: int, received: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.status, self.received = code, status, received


def valid_id(blob_id: object) -> bool:
    return isinstance(blob_id, str) and bool(_ID_RE.match(blob_id))


def new_id() -> str:
    return "b-" + os.urandom(15).hex()


class Inbox:

    def __init__(self, directory: Path, *, clock: Callable[[], float] = time.time, max_blob_bytes: Optional[int] = None,
                 max_peer_bytes: Optional[int] = None, max_total_bytes: Optional[int] = None,
                 stale_seconds: Optional[float] = None, purge_sealed: bool = False) -> None:
        self.directory, self._clock = Path(directory), clock
        self._max_blob, self._max_peer, self._max_total = max_blob_bytes, max_peer_bytes, max_total_bytes
        self._stale, self._purge_sealed = stale_seconds, purge_sealed

    def _part(self, blob_id: str) -> Path:
        return self.directory / f"{blob_id}.part"

    def _sealed(self, blob_id: str) -> Path:
        return self.directory / f"{blob_id}.blob"

    def _ensure(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    def status(self, blob_id: str) -> Dict[str, Any]:
        if not valid_id(blob_id):
            raise BlobError("bad_blob_id", 400)
        if self._sealed(blob_id).is_file():
            return {"received": self._sealed(blob_id).stat().st_size, "sealed": True}
        part = self._part(blob_id)
        return {"received": part.stat().st_size if part.is_file() else 0, "sealed": False}

    def _held(self, peer: Optional[str] = None) -> int:
        total = 0
        for f in self.directory.glob("*.*"):
            if f.suffix not in (".part", ".blob"):
                continue
            if peer is not None:
                owner = f.with_suffix(".peer")
                if not owner.is_file() or owner.read_text() != peer:
                    continue
            total += f.stat().st_size
        return total

    def put(self, blob_id: str, offset: int, data: bytes, chunk_sha256: str, peer: str = "") -> int:
        if not valid_id(blob_id):
            raise BlobError("bad_blob_id", 400)
        if len(data) > CHUNK_BYTES:
            raise BlobError("chunk_too_large", 413)
        if not _SHA_RE.match(chunk_sha256 or "") or hashlib.sha256(data).hexdigest() != chunk_sha256:
            raise BlobError("bad_chunk_hash", 422)
        if self._sealed(blob_id).is_file():
            raise BlobError("blob_sealed", 409)
        self._ensure()
        part = self._part(blob_id)
        have = part.stat().st_size if part.is_file() else 0
        if offset != have:
            raise BlobError("offset_mismatch", 409, received=have)
        if have + len(data) > (MAX_BLOB_BYTES if self._max_blob is None else self._max_blob):
            raise BlobError("blob_too_large", 413)
        if peer:
            if self._held(peer) + len(data) > (MAX_PEER_INBOX_BYTES if self._max_peer is None else self._max_peer):
                raise BlobError("inbox_quota_peer", 507)
        if self._held() + len(data) > (MAX_TOTAL_INBOX_BYTES if self._max_total is None else self._max_total):
            raise BlobError("inbox_quota_total", 507)
        if peer and offset == 0:
            self._part(blob_id).with_suffix(".peer").write_text(peer)
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return have + len(data)

    def seal(self, blob_id: str, size: int, sha256: str, kind: str) -> Path:
        if not valid_id(blob_id):
            raise BlobError("bad_blob_id", 400)
        if kind not in KINDS or not _SHA_RE.match(sha256 or ""):
            raise BlobError("bad_kind", 422)
        sealed, part = self._sealed(blob_id), self._part(blob_id)
        if sealed.is_file():
            if sealed.stat().st_size == size and _file_sha256(sealed) == sha256:
                return sealed
            raise BlobError("blob_sealed", 409)
        if not part.is_file():
            raise BlobError("unknown_blob", 404)
        have = part.stat().st_size
        if have != size:
            raise BlobError("size_mismatch", 409, received=have)
        if _file_sha256(part) != sha256:
            part.unlink(missing_ok=True)
            raise BlobError("hash_mismatch", 422)
        os.replace(part, sealed)
        os.chmod(sealed, 0o600)
        return sealed

    def sealed_path(self, blob_id: str, *, peer: str) -> Path:
        if not valid_id(blob_id):
            raise BlobError("bad_blob_id", 400)
        path = self._sealed(blob_id)
        if not path.is_file():
            raise BlobError("unknown_blob", 404)
        if not peer or self.owner(blob_id) != peer:
            logger.warning("pack_blob_owner_mismatch", blob_id=blob_id, requested_by=peer or None)
            raise BlobError("blob_not_yours", 403)
        return path

    def owner(self, blob_id: str) -> Optional[str]:
        if not valid_id(blob_id):
            return None
        marker = self._part(blob_id).with_suffix(".peer")
        try:
            return marker.read_text() if marker.is_file() else None
        except OSError:
            return None

    def remove(self, blob_id: str) -> None:
        if valid_id(blob_id):
            self._part(blob_id).unlink(missing_ok=True)
            self._sealed(blob_id).unlink(missing_ok=True)
            self._part(blob_id).with_suffix(".peer").unlink(missing_ok=True)

    def purge_stale(self) -> List[str]:
        gone: List[str] = []
        if not self.directory.is_dir():
            return gone
        limit = STALE_SECONDS if self._stale is None else self._stale
        for part in self.directory.glob("*.part" if not self._purge_sealed else "*.*"):
            if part.suffix not in (".part", ".blob"):
                continue
            try:
                if self._clock() - part.stat().st_mtime > limit:
                    part.unlink(missing_ok=True)
                    part.with_suffix(".peer").unlink(missing_ok=True)
                    gone.append(part.stem)
            except FileNotFoundError:
                continue
        return gone


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def file_sha256(path: str) -> str:
    return _file_sha256(Path(path))


async def send_file(request: Request, path: str, *, blob_id: str, kind: str, chunk_bytes: int = CHUNK_BYTES,
                    base_path: str = BLOB_PATH) -> str:
    if kind not in KINDS or not valid_id(blob_id):
        raise BlobError("bad_blob", 400)
    size, digest = os.path.getsize(path), file_sha256(path)
    base = f"{base_path}/{blob_id}"
    status, answer = await request("GET", base)
    offset = int(answer.get("received", 0)) if status == 200 and isinstance(answer, dict) else 0
    if status == 200 and isinstance(answer, dict) and answer.get("sealed"):
        return blob_id
    with open(path, "rb") as handle:
        while offset < size:
            handle.seek(offset)
            data = handle.read(min(chunk_bytes, size - offset))
            status, answer = await request("PUT", f"{base}?offset={offset}", content=data,
                                           headers={"X-Chunk-Sha256": hashlib.sha256(data).hexdigest()})
            if status == 200:
                offset += len(data)
            elif status == 409 and isinstance(answer, dict) and isinstance(answer.get("received"), int):
                offset = answer["received"]
            else:
                raise BlobError(_code(answer, "send_failed"), status)
    status, answer = await request("POST", f"{base}/seal", json={"size": size, "sha256": digest, "kind": kind})
    if status != 200:
        raise BlobError(_code(answer, "send_failed"), status)
    return blob_id


def _code(answer: Any, default: str) -> str:
    detail = answer.get("detail") if isinstance(answer, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else default


def ledger_note(conn: sqlite3.Connection, blob_id: str, peer_install_id: str, direction: str, kind: Optional[str], size: int,
                state: str, *, sha256: Optional[str] = None, path: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO pack_blobs (blob_id, peer_install_id, direction, kind, size, sha256, state, path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(blob_id) DO UPDATE SET kind = COALESCE(excluded.kind, kind), "
        "size = excluded.size, sha256 = COALESCE(excluded.sha256, sha256), state = excluded.state, path = COALESCE(excluded.path, path)",
        (blob_id, peer_install_id, direction, kind, size, sha256, state, path, utc_now()))


def request_via(client: Any, timeout: float = 60.0) -> Request:
    import asyncio

    async def request(method: str, path: str, *, content: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
                      json: Any = None) -> Tuple[int, Any]:
        reply = await asyncio.wait_for(
            client.request(method, path, json=json, content=content, headers=headers, timeout=timeout), timeout + 5.0)
        try:
            return reply.status_code, reply.json()
        except ValueError:
            return reply.status_code, None

    return request
