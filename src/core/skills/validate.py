
from __future__ import annotations

import gzip
import hashlib
import json
import stat
import tarfile
import unicodedata
import zlib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import IO, Iterator

from src.core.skills import kinds
from src.core.skills.digest import CHUNK_BYTES, DigestEntry, digest_entries, mode_string
from src.core.skills.member_names import unsafe_name_reason, unsafe_relpath_reason
from src.core.skills.validate_types import (  # noqa: F401
    is_script_member,
    ARCHIVE_INVALID,
    EXCLUDED_BASENAME_PREFIXES,
    EXCLUDED_BASENAMES,
    EXCLUDED_SEGMENTS,
    SCRIPTS_DIR,
    SCRIPTS_NOT_SUPPORTED,
    ArchiveRefused,
    Limits,
    ValidatedArchive,
    ValidatedMember,
)


class _StreamCapExceeded(Exception):
    pass


class _CountingReader:

    def __init__(self, inner: IO[bytes], cap: int) -> None:
        self._inner = inner
        self._cap = cap
        self.count = 0
        self.tripped = False

    def read(self, size: int = -1) -> bytes:
        chunk = self._inner.read(size)
        self.count += len(chunk)
        if self.count > self._cap:
            self.tripped = True
            raise _StreamCapExceeded(
                f"archive exceeds the {self._cap} byte decompressed stream cap"
            )
        return chunk


@contextmanager
def open_capped_tar(path: Path, *, max_archive_bytes: int) -> Iterator[tarfile.TarFile]:
    raw = path.open("rb")
    try:
        gz = gzip.GzipFile(fileobj=raw, mode="rb")
        reader = _CountingReader(gz, max_archive_bytes)
        tar = tarfile.open(fileobj=reader, mode="r|")
        try:
            yield tar
        finally:
            tar.close()
    except _StreamCapExceeded as exc:
        raise ArchiveRefused(ARCHIVE_INVALID, str(exc)) from exc
    except (gzip.BadGzipFile, zlib.error, EOFError) as exc:
        raise ArchiveRefused(ARCHIVE_INVALID, f"unreadable gzip stream: {exc}") from exc
    except tarfile.TarError as exc:
        raise ArchiveRefused(ARCHIVE_INVALID, f"unreadable archive: {exc}") from exc
    finally:
        raw.close()


def _refuse(reason: str | None) -> None:
    if reason is not None:
        raise ArchiveRefused(ARCHIVE_INVALID, reason)


def _is_excluded(relpath: str) -> bool:
    segments = relpath.split("/")
    if EXCLUDED_SEGMENTS.intersection(segments):
        return True
    basename = segments[-1]
    if basename in EXCLUDED_BASENAMES:
        return True
    return basename.startswith(EXCLUDED_BASENAME_PREFIXES)


def duplicate_key(relpath: str) -> str:
    return unicodedata.normalize("NFC", relpath).casefold()


def _member_kind(member: tarfile.TarInfo) -> str:
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hard link"
    if member.ischr():
        return "character device"
    if member.isblk():
        return "block device"
    if member.isfifo():
        return "fifo"
    return "not a regular file"


def _hash_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    already_read: int,
    limits: Limits,
    capture: bytearray | None = None,
    capture_limit: int = 0,
) -> tuple[str, int]:
    extracted = tar.extractfile(member)
    if extracted is None:
        raise ArchiveRefused(
            ARCHIVE_INVALID, f"member has no readable body: {member.name!r}"
        )
    digest = hashlib.sha256()
    read = 0
    while True:
        chunk = extracted.read(CHUNK_BYTES)
        if not chunk:
            break
        read += len(chunk)
        if read > member.size:
            raise ArchiveRefused(
                ARCHIVE_INVALID,
                f"member body is longer than its header claims: {member.name!r}",
            )
        if already_read + read > limits.max_bytes:
            raise ArchiveRefused(
                ARCHIVE_INVALID,
                f"skill folder exceeds {limits.max_bytes} bytes while reading "
                f"{member.name!r}",
            )
        digest.update(chunk)
        if capture is not None and len(capture) < capture_limit:
            need = capture_limit - len(capture)
            capture.extend(chunk[:need])
    if read != member.size:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"member body is shorter than its header claims: {member.name!r}",
        )
    return digest.hexdigest(), read


_MAX_CPLUG_MANIFEST_BYTES = 1024 * 1024


def _validate_cplug_manifests(
    folder_label: str,
    kept: list[ValidatedMember],
    carnivore_json_bytes: bytearray | None,
) -> None:
    paths = {entry.relpath for entry in kept}
    cplug_name = kinds.MANIFEST_FOR[kinds.KIND_CPLUG]
    has_cplug = cplug_name in paths
    has_toml = kinds.CPLUG_TOML_MANIFEST in paths
    has_json = kinds.CPLUG_JSON_MANIFEST in paths

    if not has_cplug and not has_toml and not has_json:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r} has no {cplug_name}",
        )
    if has_toml and has_cplug:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r}: "
            f"{kinds.CPLUG_TOML_MANIFEST} cannot coexist with {cplug_name}",
        )
    if has_toml and has_json:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r}: "
            f"both {kinds.CPLUG_TOML_MANIFEST} and {kinds.CPLUG_JSON_MANIFEST} exist; keep one",
        )
    if has_toml:
        return
    if has_cplug and not has_json:
        return

    if carnivore_json_bytes is None or len(carnivore_json_bytes) > _MAX_CPLUG_MANIFEST_BYTES:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r}: "
            f"{kinds.CPLUG_JSON_MANIFEST} exceeds {_MAX_CPLUG_MANIFEST_BYTES} bytes",
        )

    if has_cplug:
        try:
            raw = json.loads(carnivore_json_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and type(raw.get("schema")) is int and raw.get("schema") == 2:
            raise ArchiveRefused(
                ARCHIVE_INVALID,
                f"{kinds.KIND_CPLUG} folder {folder_label!r}: "
                f"v2 {kinds.CPLUG_JSON_MANIFEST} cannot coexist with {cplug_name}",
            )
        return

    try:
        raw = json.loads(carnivore_json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r} has no {cplug_name} "
            f"({kinds.CPLUG_JSON_MANIFEST} is not valid JSON: {exc})",
        ) from exc
    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw.get("schema") != 2:
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kinds.KIND_CPLUG} folder {folder_label!r} has no {cplug_name} "
            f"({kinds.CPLUG_JSON_MANIFEST} is not schema = 2)",
        )


def validate_archive(
    path: Path,
    *,
    publisher: str,
    name: str,
    kind: str = kinds.KIND_SKILL,
    limits: Limits = Limits(),
    allow_scripts: bool = False,
    src_path: str | None = None,
) -> ValidatedArchive:
    manifest = kinds.manifest_name(kind)
    candidates = kinds.candidate_manifests(kind)
    try:
        skill_rel = kinds.archive_root(kind, publisher, name, src_path) + "/"
    except ValueError as exc:
        raise ArchiveRefused(ARCHIVE_INVALID, str(exc)) from exc
    prefix: str | None = None
    kept: list[ValidatedMember] = []
    scripts: list[str] = []
    seen: dict[str, str] = {}
    size_sum = 0
    total_bytes = 0
    carnivore_json_bytes: bytearray | None = None

    with open_capped_tar(path, max_archive_bytes=limits.max_archive_bytes) as tar:
        for member in tar:
            raw_name = member.name
            _refuse(unsafe_name_reason(raw_name))

            if prefix is None:
                prefix = raw_name.split("/", 1)[0] + "/"
            if raw_name == prefix[:-1]:
                continue
            if not raw_name.startswith(prefix):
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"member outside the archive prefix {prefix!r}: {raw_name!r}",
                )

            rest = raw_name[len(prefix) :]
            if _is_excluded(rest):
                continue
            if not rest.startswith(skill_rel):
                continue
            relpath = rest[len(skill_rel) :]
            if not relpath or member.isdir():
                continue

            _refuse(unsafe_relpath_reason(relpath, raw_name))

            if not relpath.isascii():
                raise ArchiveRefused(
                    ARCHIVE_INVALID, f"non-ASCII member name: {raw_name!r}"
                )

            key = duplicate_key(relpath)
            if key in seen:
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"duplicate member after case folding and NFC: {raw_name!r} "
                    f"collides with {seen[key]!r}",
                )

            if not member.isreg():
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"{_member_kind(member)} member: {raw_name!r}",
                )

            base_name = PurePosixPath(relpath).name
            if base_name in candidates and "/" in relpath:
                raise ArchiveRefused(
                    ARCHIVE_INVALID, f"nested {base_name}: {raw_name!r}"
                )

            if len(kept) + 1 > limits.max_members:
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"more than {limits.max_members} members at {raw_name!r}",
                )

            size_sum += member.size
            if size_sum > limits.max_bytes:
                raise ArchiveRefused(
                    ARCHIVE_INVALID,
                    f"header sizes sum over {limits.max_bytes} bytes at {raw_name!r}",
                )

            executable = bool(member.mode & stat.S_IXUSR)
            is_script = is_script_member(relpath, executable)
            if is_script and not allow_scripts:
                what = f"{SCRIPTS_DIR}/ member" if is_script_member(relpath, False) else "executable member"
                raise ArchiveRefused(SCRIPTS_NOT_SUPPORTED, f"{what}: {raw_name!r}")
            if is_script:
                scripts.append(relpath)

            capture: bytearray | None = None
            if kind == kinds.KIND_CPLUG and relpath == kinds.CPLUG_JSON_MANIFEST:
                capture = bytearray()
                carnivore_json_bytes = capture
            hex_digest, read = _hash_member(
                tar,
                member,
                already_read=total_bytes,
                limits=limits,
                capture=capture,
                capture_limit=_MAX_CPLUG_MANIFEST_BYTES + 1 if capture is not None else 0,
            )
            total_bytes += read
            seen[key] = relpath
            kept.append(
                ValidatedMember(
                    relpath=relpath,
                    size=read,
                    mode=mode_string(bool(member.mode & stat.S_IXUSR)),
                    sha256=hex_digest,
                )
            )

    if prefix is None:
        raise ArchiveRefused(ARCHIVE_INVALID, "archive holds no members")
    if kind == kinds.KIND_CPLUG:
        _validate_cplug_manifests(prefix + skill_rel, kept, carnivore_json_bytes)
    elif not any(entry.relpath == manifest for entry in kept):
        raise ArchiveRefused(
            ARCHIVE_INVALID,
            f"{kind} folder {prefix + skill_rel!r} has no {manifest}",
        )

    ordered = tuple(sorted(kept, key=lambda entry: entry.relpath.encode("utf-8")))
    digest = digest_entries(
        DigestEntry(relpath=entry.relpath, mode=entry.mode, sha256=entry.sha256)
        for entry in ordered
    )
    return ValidatedArchive(
        prefix=prefix,
        skill_root=prefix + skill_rel,
        members=ordered,
        digest=digest,
        total_bytes=total_bytes,
        script_members=tuple(sorted(scripts)),
    )
