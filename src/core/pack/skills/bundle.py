
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from src.core.pack.skills import rules
from src.core.pack.skills.scan import FileEntry
from src.core.skills.digest import MODE_EXECUTABLE, MODE_REGULAR

FILES_JSON = "files.json"
MAX_FILES_JSON_BYTES = 2 * 1024 * 1024
MAX_MEMBERS = 20000
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

Pair = tuple[str, str]


class BundleError(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Bundle:

    staging: Path
    skills: Mapping[Pair, tuple[FileEntry, ...]]


def build_bundle(out: Path, items: Iterable[tuple[str, str, Path, Sequence[FileEntry]]]) -> None:
    listing = {f"{fam}/{name}": [{"path": e.path, "size": e.size, "mode": e.mode, "sha256": e.sha256} for e in files]
               for fam, name, _dir, files in items}
    manifest = json.dumps({"v": 1, "skills": listing}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with tarfile.open(out, "w:gz") as tar:
        _add(tar, FILES_JSON, manifest, 0o644)
        for fam, name, folder, files in items:
            for entry in files:
                fd = os.open(folder / entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise BundleError("unsafe_member", entry.path)
                    data = handle.read(rules.MAX_FILE_BYTES + 1)
                if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
                    raise BundleError("hash_mismatch", entry.path)
                _add(tar, f"{fam}/{name}/{entry.path}", data, 0o755 if entry.mode == MODE_EXECUTABLE else 0o644)


def _add(tar: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, 0
    tar.addfile(info, io.BytesIO(data))


def _parse_manifest(raw: bytes) -> dict[Pair, tuple[FileEntry, ...]]:
    try:
        doc = json.loads(raw.decode("utf-8"))
        listing = doc["skills"]
        if doc.get("v") != 1 or not isinstance(listing, dict):
            raise ValueError("shape")
        out: dict[Pair, tuple[FileEntry, ...]] = {}
        for key, rows in listing.items():
            family, _, name = key.partition("/")
            if family not in rules.FAMILIES or rules.skill_name_problem(name) is not None or rules.nfc(name) != name:
                raise ValueError("name")
            entries = []
            for row in rows:
                path, size, mode, sha = row["path"], row["size"], row["mode"], row["sha256"]
                if (not isinstance(path, str) or rules.path_problem(path) is not None or path.rsplit("/", 1)[-1] in rules.IGNORED_BASENAMES or type(size) is not int or size < 0
                        or size > rules.MAX_FILE_BYTES or mode not in (MODE_REGULAR, MODE_EXECUTABLE)
                        or not isinstance(sha, str) or not _SHA_RE.match(sha)):
                    raise ValueError("entry")
                entries.append(FileEntry(path, size, mode, sha))
            if (len(entries) > rules.MAX_SKILL_FILES or sum(e.size for e in entries) > rules.MAX_SKILL_BYTES
                    or len({e.path for e in entries}) != len(entries) or rules.collision(e.path for e in entries)):
                raise ValueError("limits")
            out[(family, name)] = tuple(entries)
        if (sum(len(v) for v in out.values()) > rules.MAX_SET_FILES
                or sum(e.size for v in out.values() for e in v) > rules.MAX_SET_BYTES):
            raise ValueError("set limits")
        return out
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError) as exc:
        raise BundleError("bad_bundle", f"files.json: {type(exc).__name__}") from None


def _member_pair(name: str) -> tuple[Optional[Pair], str]:
    parts = name.rstrip("/").split("/", 2)
    if len(parts) < 2 or parts[0] not in rules.FAMILIES:
        return None, ""
    return (parts[0], parts[1]), (parts[2] if len(parts) == 3 else "")


def read_bundle(path: Path, staging: Path) -> Bundle:
    try:
        with tarfile.open(path, "r:gz") as tar:
            members = []
            while (header := tar.next()) is not None:
                members.append(header)
                if len(members) > MAX_MEMBERS:
                    raise BundleError("too_large", "members")
            manifest_member = next((m for m in members if m.name == FILES_JSON), None)
            if manifest_member is None or not manifest_member.isreg() or manifest_member.size > MAX_FILES_JSON_BYTES:
                raise BundleError("bad_bundle", "files.json")
            listed = _parse_manifest(tar.extractfile(manifest_member).read())  # type: ignore[union-attr]
            expected = {(pair, e.path): e for pair, entries in listed.items() for e in entries}
            seen: set[tuple[Pair, str]] = set()
            total = 0
            for member in members:
                if member is manifest_member:
                    continue
                if not (member.isreg() or member.isdir()):
                    raise BundleError("unsafe_member", member.name)
                pair, inner = _member_pair(member.name)
                if pair is None or pair not in listed or rules.has_control_chars(member.name) or "\\" in member.name:
                    raise BundleError("unsafe_member", member.name)
                if member.isdir():
                    if inner and rules.path_problem(inner) is not None:
                        raise BundleError("unsafe_member", member.name)
                    continue
                entry = expected.get((pair, inner))
                if entry is None or member.size != entry.size or (pair, inner) in seen:
                    raise BundleError("unsafe_member", member.name)
                seen.add((pair, inner))
                total += member.size
                if total > rules.MAX_SET_BYTES:
                    raise BundleError("too_large", "bytes")
            if len(seen) != len(expected):
                raise BundleError("bad_bundle", "a listed file is missing")
            staging.mkdir(parents=True, mode=0o700)
            os.chmod(staging, 0o700)
            for member in members:
                if member is not manifest_member:
                    tar.extract(member, staging, filter="data")
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        raise BundleError("bad_bundle", type(exc).__name__) from None
    for (family, name), entries in listed.items():
        for entry in entries:
            _verify_file(staging / family / name / entry.path, entry)
    return Bundle(staging, listed)


def _verify_file(path: Path, entry: FileEntry) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(rules.MAX_FILE_BYTES + 1)
            ok = stat.S_ISREG(os.fstat(handle.fileno()).st_mode)
    except OSError:
        raise BundleError("hash_mismatch", entry.path) from None
    if not ok or len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
        raise BundleError("hash_mismatch", entry.path)
