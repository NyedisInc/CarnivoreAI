""":class:`CrateSink`: write a crate's tar container in one streaming pass, with fixed headers and deduplicated blobs.

The container is ``tarfile.PAX_FORMAT``, uncompressed, written in order through a byte counter, so the sink never seeks
and can write straight into an :class:`~src.core.crate_crypto.age.AgeWriter`. Every member is a regular file with mode 0o644, uid
and gid 0, empty owner names and ``mtime = created_epoch``; there are no directory members and no links. Names are ASCII.
tarfile writes a PAX extended header (typeflag ``x``) only for a name over 100 characters (a long rows part name, up to
121, or a newer minor's name) or a member over 8 GiB; the fixed v1 members and blob names never need one.

Example:
    sink = CrateSink(out, created_epoch=1792267200, codec="zstd")
    sink.add_member("CRATE", MAGIC)
    ref = sink.add_blob(b"one chunk")
    ...
    sink.close()
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Iterator, List, Optional

from src.core.blobcodec.chunking import ChunkRef
from src.core.blobcodec.codec import blob_relpath, compress
from src.core.crate_format.constants import (
    CONTENT_ID_MEMBERS, GID, LINES_PREFIX, M_EXTRACT, M_MAGIC, M_MANIFEST, M_README, MAX_CHUNK_LENGTH, ROWS_PREFIX, TAR_MODE,
    UID,
)
from src.core.crate_format.canonical import dumps
from src.core.crate_format.model import MemberRecord
from src.core.crate_format.names import check_member_name


class _ChunkStream(io.RawIOBase):

    def __init__(self, chunks: Iterable[bytes]) -> None:
        super().__init__()
        self._chunks: Iterator[bytes] = iter(chunks)
        self._pending = b""
        self.digest = hashlib.sha256()
        self.count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        view = memoryview(b).cast("B")
        done = 0
        while done < len(view):
            if not self._pending:
                nxt = next(self._chunks, None)
                if nxt is None:
                    break
                self._pending = bytes(nxt)
                continue
            piece = self._pending[:len(view) - done]
            self._pending = self._pending[len(piece):]
            view[done:done + len(piece)] = piece
            done += len(piece)
        self.digest.update(view[:done])
        self.count += done
        return done

    def exhausted(self) -> bool:
        while not self._pending:
            nxt = next(self._chunks, None)
            if nxt is None:
                return True
            self._pending = bytes(nxt)
        return False


TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"


def template_bytes(name: str) -> bytes:
    if name not in (M_README, M_EXTRACT):
        raise ValueError(f"{name!r} is not a crate template")
    return (TEMPLATES_DIR / name).read_bytes()


class _Counter(io.RawIOBase):

    def __init__(self, raw: BinaryIO) -> None:
        super().__init__()
        self._raw, self._pos = raw, 0

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        data = bytes(b)
        self._raw.write(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos


def content_id_of(members: Iterable[MemberRecord]) -> str:
    pairs = sorted([m.name, m.sha256] for m in members
                   if m.name in CONTENT_ID_MEMBERS or m.name.startswith((ROWS_PREFIX, LINES_PREFIX)))
    return hashlib.sha256(dumps(pairs)).hexdigest()


def blob_set_sha256(names: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(names)) + "\n").encode("ascii")).hexdigest()


class CrateSink:

    def __init__(self, raw: BinaryIO, created_epoch: int, codec: str) -> None:
        self._raw = raw
        self._epoch = int(created_epoch)
        self.codec = codec
        self._tar: Optional[tarfile.TarFile] = tarfile.TarFile(fileobj=_Counter(raw), mode="w", format=tarfile.PAX_FORMAT)
        self._names: set = set()
        self._blobs: Dict[str, str] = {}
        self.members: List[MemberRecord] = []

    def _info(self, name: str, size: int) -> tarfile.TarInfo:
        if self._tar is None:
            raise ValueError("the crate sink is closed")
        check_member_name(name)
        if name in self._names:
            raise ValueError(f"member {name!r} was already written")
        self._names.add(name)
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = size, TAR_MODE, self._epoch
        info.uid, info.gid, info.uname, info.gname = UID, GID, "", ""
        info.type = tarfile.REGTYPE
        return info

    def add_member(self, name: str, data: bytes) -> MemberRecord:
        info = self._info(name, len(data))
        self._tar.addfile(info, io.BytesIO(data))
        record = MemberRecord(name, len(data), hashlib.sha256(data).hexdigest())
        self.members.append(record)
        return record

    def add_stream(self, name: str, chunks: Iterable[bytes], size: int) -> MemberRecord:
        info = self._info(name, size)
        stream = _ChunkStream(chunks)
        try:
            self._tar.addfile(info, stream)
        except OSError as exc:
            raise ValueError(f"member {name!r} is shorter than its stated {size} bytes") from exc
        if stream.count != size or not stream.exhausted():
            raise ValueError(f"member {name!r} is longer than its stated {size} bytes")
        record = MemberRecord(name, size, stream.digest.hexdigest())
        self.members.append(record)
        return record

    def add_blob(self, raw: bytes) -> ChunkRef:
        if not 0 < len(raw) <= MAX_CHUNK_LENGTH:
            raise ValueError(f"a chunk must hold 1 to {MAX_CHUNK_LENGTH} bytes, this one holds {len(raw)}")
        sha = hashlib.sha256(raw).hexdigest()
        if sha not in self._blobs:
            name = blob_relpath(sha, self.codec)
            packed = compress(raw, self.codec)
            info = self._info(name, len(packed))
            self._tar.addfile(info, io.BytesIO(packed))
            self._blobs[sha] = name
        return ChunkRef(sha, len(raw))

    def blob_names(self) -> List[str]:
        return list(self._blobs.values())

    def manifest_members(self) -> List[MemberRecord]:
        return sorted((m for m in self.members if m.name not in (M_MAGIC, M_MANIFEST)), key=lambda m: m.name)

    def blobs_block(self) -> Dict[str, object]:
        names = self.blob_names()
        return {"count": len(names), "set_sha256": blob_set_sha256(names), "codecs": [self.codec] if names else []}

    def close(self) -> None:
        if self._tar is None:
            return
        tar, self._tar = self._tar, None
        tar.close()
        self._raw.flush()
