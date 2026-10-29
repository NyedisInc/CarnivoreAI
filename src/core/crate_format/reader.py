""":func:`open_crate`: open a crate from untrusted input and read it member by member, never through ``extractall``.

A plain crate is read straight from the file. An encrypted one (``<id>.crate.age``, first bytes ``age-encryption.org/v1``)
is read through ``src.core.crate_crypto.age.AgeReader``, which is seekable, so no plaintext ever touches disk; that
package is imported here only when such a file is opened.

The header walk refuses (``CrateMalformed``): a member that is not a regular file; a name outside the grammar (a name
only the safe generic grammar allows is accepted when the manifest's minor is newer than this build's); a name twice;
``CRATE`` missing, not first, or not the magic bytes; ``crate.json`` not last; more than ``MAX_MEMBERS`` members; a JSON
member over ``MAX_JSON_MEMBER``; a blob over ``MAX_BLOB_MEMBER``; a rows part over ``MAX_ROWS_PART``; two blob members
for one chunk (``<sha>.zst`` beside ``<sha>.xz``: each distinct chunk is stored once); a member whose data runs past the
end of the file. A member a newer minor added has no size cap: it is only ever streamed in ``READ_BYTES`` blocks, never
buffered. A streamed line longer than its bound (``MAX_ROWS_LINE`` for rows) is malformed.
Every blob is decompressed with a bound equal to the length its chunk ref claims, then its sha256 and length are checked.

Example:
    with open_crate(Path("x.crate")) as reader:
        for rec in reader.files():
            data = b"".join(reader.file_chunks(rec))
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from src.core.blobcodec.chunking import ChunkRef
from src.core.blobcodec.codec import BLOB_EXTENSIONS, BlobCorrupt, decompress_bounded
from src.core.crate_format import canonical, readers
from src.core.crate_format.constants import (
    AGE_MAGIC, FORMAT_MINOR, M_FILES, M_MAGIC, M_MANIFEST, M_SCHEMA, MAGIC, MAX_BLOB_MEMBER, MAX_JSON_MEMBER, MAX_MEMBERS,
    MAX_ROWS_LINE, MAX_ROWS_PART, READ_BYTES,
)
from src.core.crate_format.errors import CrateCorrupt, CrateMalformed, NeedsIdentity, UnsafeName, WrongKey
from src.core.crate_format.model import ConversationRecord, CrateManifest
from src.core.crate_format.model_files import FileRecord, LinesRecord, TableRecord, parse_schema
from src.core.crate_format.names import KIND_BLOB, KIND_LINES, KIND_ROWS, KIND_UNKNOWN, member_kind

Identity = Union[str, bytes, bytearray]
_CODEC_OF_EXT = {ext: codec for codec, ext in BLOB_EXTENSIONS.items()}


@dataclass(frozen=True)
class TarMember:

    name: str
    size: int
    offset: int
    kind: str


def _age_open(raw: BinaryIO, identities: Sequence[Identity]) -> Tuple[BinaryIO, tuple]:
    from src.core.crate_crypto import errors as crypto_errors
    from src.core.crate_crypto.age import AgeReader
    from src.core.crate_crypto.keys import parse_identity

    if not identities:
        raise NeedsIdentity("this crate is encrypted; an age identity is needed to read it")
    try:
        keys = [bytes(i) if isinstance(i, (bytes, bytearray)) else parse_identity(i) for i in identities]
        return AgeReader(raw, keys), (crypto_errors.Corrupt,)
    except crypto_errors.KeyFormatError as exc:
        raise NeedsIdentity(f"the identity given is not an age identity: {exc}") from None
    except crypto_errors.WrongKey as exc:
        raise WrongKey(str(exc)) from None
    except crypto_errors.Malformed as exc:
        raise CrateMalformed([f"age header: {exc}"]) from None
    except crypto_errors.Corrupt as exc:
        raise CrateCorrupt([f"age: {exc}"], code="age_corrupt") from None


def open_crate(path: Path, identity: Optional[Identity] = None, *,
               extra_identities: Sequence[Identity] = ()) -> "CrateReader":
    raw = open(path, "rb")
    try:
        encrypted = raw.read(len(AGE_MAGIC)) == AGE_MAGIC
        raw.seek(0)
        stream: BinaryIO = raw
        age_errors: tuple = ()
        if encrypted:
            ids = ([identity] if identity is not None else []) + list(extra_identities)
            stream, age_errors = _age_open(raw, ids)
        return CrateReader(raw, stream, encrypted, age_errors)
    except BaseException:
        raw.close()
        raise


def _member_cap(kind: str) -> Optional[int]:
    if kind == KIND_BLOB:
        return MAX_BLOB_MEMBER
    if kind == KIND_ROWS:
        return MAX_ROWS_PART
    if kind == KIND_UNKNOWN:
        return None
    return MAX_JSON_MEMBER


class CrateReader:

    def __init__(self, raw: BinaryIO, stream: BinaryIO, encrypted: bool, age_errors: tuple) -> None:
        self._raw, self._stream, self.encrypted, self._age_errors = raw, stream, encrypted, age_errors
        self._members: Dict[str, TarMember] = {}
        self._order: List[str] = []
        self._guard(self._walk)
        manifest_json = self.read_json(M_MANIFEST)
        self.manifest: CrateManifest = readers.load(manifest_json)
        self.format_version: Tuple[int, int] = tuple(self.manifest.format_version)
        unknown = self.unknown_members()
        if unknown and self.format_version[1] <= FORMAT_MINOR:
            raise UnsafeName(f"member {unknown[0]!r} is outside the crate v1.{self.format_version[1]} grammar")

    def _guard(self, work: Any, *args: Any) -> Any:
        try:
            return work(*args)
        except tarfile.TarError as exc:
            raise CrateMalformed([f"not a readable tar container: {exc}"]) from None
        except self._age_errors as exc:
            raise CrateCorrupt([f"age: {exc}"], code="age_corrupt") from None

    def _walk(self) -> None:
        total = self._stream.seek(0, io.SEEK_END)
        if self.encrypted:
            self._stream.read(1)
        self._stream.seek(0)
        tar = tarfile.open(fileobj=self._stream, mode="r:")
        chunks: set = set()
        for info in tar:
            if len(self._order) >= MAX_MEMBERS:
                raise CrateMalformed([f"more than {MAX_MEMBERS} members"])
            name = info.name
            kind = member_kind(name)
            if kind is None:
                raise UnsafeName(f"member name {name!r} is outside every crate grammar")
            if info.type != tarfile.REGTYPE:
                raise CrateMalformed([f"member {name!r} is not a regular file"])
            if name in self._members:
                raise CrateMalformed([f"member {name!r} appears twice"])
            if not self._order and name != M_MAGIC:
                raise CrateMalformed(["the first member is not CRATE"])
            if kind == KIND_BLOB:
                chunk = name.split("/")[2].split(".")[0]
                if chunk in chunks:
                    raise CrateMalformed([f"chunk {chunk[:12]} is stored twice (member {name!r})"])
                chunks.add(chunk)
            cap = _member_cap(kind)
            if cap is not None and info.size > cap:
                raise CrateMalformed([f"member {name!r} is larger than {cap} bytes"])
            if info.offset_data + info.size > total:
                raise CrateMalformed([f"member {name!r} runs past the end of the file"])
            self._members[name] = TarMember(name, info.size, info.offset_data, kind)
            self._order.append(name)
        if not self._order:
            raise CrateMalformed(["the first member is not CRATE"])
        if self._order[-1] != M_MANIFEST:
            raise CrateMalformed(["crate.json is not the last member"])
        if self._read_at(self._members[M_MAGIC]) != MAGIC:
            raise CrateMalformed(["CRATE does not hold the crate magic"])

    def _read_at(self, member: TarMember, offset: int = 0, size: Optional[int] = None) -> bytes:
        want = member.size - offset if size is None else size
        self._stream.seek(member.offset + offset)
        data = self._stream.read(want)
        if len(data) != want:
            raise CrateMalformed([f"member {member.name!r} is truncated"])
        return data

    def has(self, name: str) -> bool:
        return name in self._members

    def members(self) -> List[TarMember]:
        return [self._members[n] for n in self._order]

    def unknown_members(self) -> List[str]:
        return [n for n in self._order if self._members[n].kind == KIND_UNKNOWN]

    def blob_names(self) -> List[str]:
        return [n for n in self._order if self._members[n].kind == KIND_BLOB]

    def read_member(self, name: str) -> bytes:
        member = self._members.get(name)
        if member is None:
            raise CrateMalformed([f"member {name!r} is missing"])
        if member.size > MAX_JSON_MEMBER:
            raise CrateMalformed([f"member {name!r} is too large to read whole"])
        return self._guard(self._read_at, member)

    def read_json(self, name: str) -> Any:
        try:
            return canonical.loads(self.read_member(name))
        except ValueError as exc:
            raise CrateMalformed([f"member {name!r} is not valid JSON: {exc}"]) from None

    def iter_member(self, name: str, block: int = READ_BYTES) -> Iterator[bytes]:
        member = self._members.get(name)
        if member is None:
            raise CrateMalformed([f"member {name!r} is missing"])
        done = 0
        while done < member.size:
            piece = self._guard(self._read_at, member, done, min(block, member.size - done))
            done += len(piece)
            yield piece

    def iter_lines(self, name: str, max_line: int = MAX_JSON_MEMBER) -> Iterator[bytes]:
        tail = bytearray()
        for piece in self.iter_member(name):
            start = 0
            end = piece.find(b"\n")
            while end != -1:
                if len(tail) + end - start > max_line:
                    raise CrateMalformed([f"member {name!r} has a line longer than {max_line} bytes"])
                tail += piece[start:end + 1]
                yield bytes(tail)
                tail.clear()
                start = end + 1
                end = piece.find(b"\n", start)
            tail += piece[start:]
            if len(tail) > max_line:
                raise CrateMalformed([f"member {name!r} has a line longer than {max_line} bytes"])
        if tail:
            yield bytes(tail)

    @cached_property
    def _files(self) -> List[FileRecord]:
        records: List[FileRecord] = []
        seen = set()
        for line in self.iter_lines(M_FILES):
            try:
                record = FileRecord.from_json(canonical.loads(line))
            except ValueError as exc:
                raise CrateMalformed([f"files.jsonl has a line that is not valid JSON: {exc}"]) from None
            if record.sort_key in seen:
                raise CrateMalformed([f"files.jsonl lists {record.place!r} twice"])
            seen.add(record.sort_key)
            records.append(record)
        return records

    def files(self) -> List[FileRecord]:
        return list(self._files)

    def conversations(self) -> List[ConversationRecord]:
        return list(self.manifest.conversations)

    @cached_property
    def _tables(self) -> Dict[str, Dict[str, TableRecord]]:
        return parse_schema(self.read_json(M_SCHEMA)) if self.has(M_SCHEMA) else {}

    def tables(self) -> Dict[str, Dict[str, TableRecord]]:
        return {store: dict(by_name) for store, by_name in self._tables.items()}

    def lines(self) -> List[LinesRecord]:
        return [LinesRecord.from_name(n) for n in self._order if self._members[n].kind == KIND_LINES]

    def rows(self, store: str, table: str) -> Iterator[dict]:
        record = self._tables.get(store, {}).get(table)
        if record is None:
            raise CrateMalformed([f"no table {store}.{table} in this crate"])
        for part in record.parts:
            for line in self.iter_lines(part, MAX_ROWS_LINE):
                try:
                    row = canonical.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("a row is not a JSON object")
                    yield {key: canonical.decode_value(value) for key, value in row.items()}
                except ValueError as exc:
                    raise CrateMalformed([f"rows part {part!r} has a bad line: {exc}"]) from None

    def blob_member(self, sha: str) -> Optional[Tuple[str, str]]:
        for ext, codec in _CODEC_OF_EXT.items():
            name = f"blobs/{sha[:2]}/{sha}{ext}"
            if name in self._members:
                return name, codec
        return None

    def read_chunk(self, ref: ChunkRef) -> bytes:
        found = self.blob_member(ref.sha256)
        if found is None:
            raise CrateCorrupt([f"chunk {ref.sha256[:12]} has no blob"], code="missing_blob")
        name, codec = found
        packed = self._guard(self._read_at, self._members[name])
        try:
            raw = decompress_bounded(packed, codec, ref.length)
        except BlobCorrupt as exc:
            raise CrateCorrupt([f"blob {name!r}: {exc}"]) from None
        if len(raw) != ref.length or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise CrateCorrupt([f"blob {name!r} does not hold the chunk its name and length say"])
        return raw

    def file_chunks(self, record: FileRecord) -> Iterator[bytes]:
        for ref in record.chunks:
            yield self.read_chunk(ref)

    def close(self) -> None:
        self._raw.close()

    def __enter__(self) -> "CrateReader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
