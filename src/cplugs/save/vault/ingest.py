
from __future__ import annotations

import os
import stat as stat_mod
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, MutableMapping, Optional, Protocol

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import digest as digest_mod
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.manifest import FileEntry
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing, ChunkReader, ChunkRef, chain_sha
from src.cplugs.sdk.transcript_files import dataless

logger = structlog.get_logger()


class SourceError(RuntimeError):
    """A source file could not be copied faithfully. The unit is retried later; nothing is recorded for it."""


class DatalessSource(SourceError):

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"icloud placeholder not downloaded: {path}")


class SourceUnstable(SourceError):
    pass


class SliceExpired(RuntimeError):
    pass


class Pacer(Protocol):

    def rest(self, worked_seconds: float) -> None:
        pass

    def expired(self) -> bool:
        pass


@dataclass
class Partial:

    ino: int
    size: int
    mtime_ns: int
    refs: List[ChunkRef] = field(default_factory=list)
    digests: List[dict] = field(default_factory=list)
    stored: int = 0
    lines: int = 0
    entry: Optional[FileEntry] = None

    def length(self) -> int:
        return sum(r.length for r in self.refs)


def unchanged(prior: Optional[FileEntry], st: os.stat_result, blobs: BlobStore) -> bool:
    return (prior is not None and prior.size_seen == st.st_size and prior.mtime_ns == st.st_mtime_ns
            and not prior.tail_due(st.st_mtime_ns, time.time()) and all(blobs.has(c.sha256) for c in prior.chunks))


def _region_matches(handle: BinaryIO, offset: int, ref: ChunkRef) -> bool:
    import hashlib

    handle.seek(offset)
    raw = handle.read(ref.length)
    return len(raw) == ref.length and hashlib.sha256(raw).hexdigest() == ref.sha256


def _prefix_intact(handle: BinaryIO, refs: List[ChunkRef], blobs: BlobStore) -> bool:
    if not refs:
        return True
    if not all(blobs.has(r.sha256) for r in refs):
        return False
    last_offset = sum(r.length for r in refs[:-1])
    return _region_matches(handle, 0, refs[0]) and (len(refs) == 1 or _region_matches(handle, last_offset, refs[-1]))


def _starting_point(path: Path, st: os.stat_result, line_mode: bool, blobs: BlobStore, prior: Optional[FileEntry],
                    parked: Optional[Partial], want_digests: bool) -> Partial:
    fresh = Partial(st.st_ino, st.st_size, st.st_mtime_ns)
    try:
        with open(path, "rb") as handle:
            if parked is not None and parked.entry is None and parked.ino == st.st_ino and (
                    st.st_size >= parked.size if line_mode else (st.st_size == parked.size and st.st_mtime_ns == parked.mtime_ns)):
                if _prefix_intact(handle, parked.refs, blobs):
                    return Partial(st.st_ino, st.st_size, st.st_mtime_ns, list(parked.refs), list(parked.digests),
                                   parked.stored, parked.lines)
            reusable = prior.chunks[:-1] if prior is not None and line_mode and prior.sha_kind == K.SHA_CHAIN else []
            if (reusable and st.st_size >= prior.length and (not want_digests or len(prior.digests) == len(prior.chunks))
                    and _prefix_intact(handle, reusable, blobs)):
                keep = len(reusable)
                tail_lines = blobs.get(prior.chunks[-1]).count(b"\n")
                return Partial(st.st_ino, st.st_size, st.st_mtime_ns, list(reusable),
                               list(prior.digests[:keep]) if want_digests else [],
                               sum(blobs.stored_size(r.sha256) for r in reusable), max(0, prior.lines - tail_lines))
    except (OSError, BlobMissing, BlobCorrupt):
        pass
    return fresh


def _read_from(path: Path, st: os.stat_result, line_mode: bool, blobs: BlobStore, pace: Optional[Pacer],
               start: Partial, want_digests: bool, parked: Optional[MutableMapping[str, Partial]]) -> tuple:
    offset = start.length()
    progress = start
    with open(path, "rb") as handle:
        handle.seek(offset)
        quiet = time.time() - st.st_mtime_ns / 1e9 >= K.QUIET_TAIL_SECONDS
        reader = ChunkReader(handle, st.st_size - offset, line_mode, keep_tail=line_mode and quiet)
        mark = time.monotonic()
        for raw in reader:
            ref, size, _new = blobs.put(raw)
            progress.refs.append(ref)
            progress.stored += size
            if want_digests:
                progress.digests.append(digest_mod.chunk_digest(raw))
            if line_mode:
                progress.lines += raw.count(b"\n")
            if pace is not None:
                pace.rest(time.monotonic() - mark)
                if parked is not None and pace.expired():
                    parked[str(path)] = progress
                    raise SliceExpired(f"{path.name}: {progress.length()} of {st.st_size} bytes read; continues next slice")
                mark = time.monotonic()
    return progress, reader.torn_bytes, reader.short


def ingest_file(blobs: BlobStore, path: Path, *, role: str, home: str, rel: str, prior: Optional[FileEntry] = None,
                pace: Optional[Pacer] = None, parked: Optional[MutableMapping[str, Partial]] = None) -> FileEntry:
    line_mode = role in K.LINE_ROLES
    want_digests = role in K.MAIN_ROLES
    key = str(path)
    for _attempt in range(K.STABLE_READ_TRIES):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            if parked is not None:
                parked.pop(key, None)
            raise
        if not stat_mod.S_ISREG(st.st_mode):
            raise SourceError(f"not a regular file: {path}")
        if dataless.is_dataless_file(path):
            raise DatalessSource(str(path))
        if unchanged(prior, st, blobs):
            if parked is not None:
                parked.pop(key, None)
            return prior
        done = parked.get(key) if parked is not None else None
        if (done is not None and done.entry is not None and done.ino == st.st_ino and done.entry.size_seen == st.st_size
                and done.entry.mtime_ns == st.st_mtime_ns and all(blobs.has(c.sha256) for c in done.entry.chunks)):
            return done.entry
        start = _starting_point(path, st, line_mode, blobs, prior, parked.get(key) if parked is not None else None, want_digests)
        try:
            progress, torn, short = _read_from(path, st, line_mode, blobs, pace, start, want_digests, parked)
            after = os.stat(path)
        except OSError as exc:
            if dataless.is_deadlock(exc):
                raise DatalessSource(str(path)) from exc
            raise
        if parked is not None:
            parked.pop(key, None)
        stable = not short and after.st_ino == st.st_ino and after.st_size >= st.st_size and (
            line_mode or (after.st_size == st.st_size and after.st_mtime_ns == st.st_mtime_ns))
        if stable:
            entry = FileEntry(role=role, home=home, rel=rel, source_path=key, length=progress.length(),
                             sha256=chain_sha(progress.refs), sha_kind=K.SHA_CHAIN, chunks=list(progress.refs),
                             size_seen=st.st_size, mtime_ns=st.st_mtime_ns, torn_bytes=torn, lines=progress.lines,
                             stored_bytes=progress.stored, mode=stat_mod.S_IMODE(st.st_mode), digests=progress.digests)
            if parked is not None:
                parked[key] = Partial(st.st_ino, st.st_size, st.st_mtime_ns, entry=entry)
            return entry
        logger.info("vault_source_changed_while_read", path=key, short_read=short)
    raise SourceUnstable(f"{path} kept changing while it was read")
