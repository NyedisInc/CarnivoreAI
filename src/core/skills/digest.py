
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DIGEST_DOMAIN = b"carnivore-skill-digest-v1\n"

MODE_EXECUTABLE = "100755"
MODE_REGULAR = "100644"

CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class DigestEntry:

    relpath: str
    mode: str
    sha256: str


def mode_string(is_executable: bool) -> str:
    return MODE_EXECUTABLE if is_executable else MODE_REGULAR


def render_entries(entries: Iterable[DigestEntry]) -> bytes:
    lines: list[bytes] = []
    for entry in sorted(entries, key=lambda e: e.relpath.encode("utf-8")):
        lines.append(
            entry.mode.encode("ascii")
            + b"\0"
            + entry.relpath.encode("utf-8")
            + b"\0"
            + entry.sha256.encode("ascii")
            + b"\n"
        )
    return b"".join(lines)


def digest_entries(entries: Iterable[DigestEntry]) -> str:
    return hashlib.sha256(DIGEST_DOMAIN + render_entries(entries)).hexdigest()


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
    return digest.hexdigest(), read


def digest_directory(root: Path) -> tuple[str, tuple[DigestEntry, ...]]:
    entries: list[DigestEntry] = []
    root_str = str(root)
    for dirpath, _dirnames, filenames in os.walk(root_str, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            info = os.lstat(full)
            if not stat.S_ISREG(info.st_mode):
                continue
            relpath = os.path.relpath(str(full), root_str).replace(os.sep, "/")
            hex_digest, _read = hash_file(full)
            entries.append(
                DigestEntry(
                    relpath=relpath,
                    mode=mode_string(bool(info.st_mode & stat.S_IXUSR)),
                    sha256=hex_digest,
                )
            )
    ordered = tuple(sorted(entries, key=lambda e: e.relpath.encode("utf-8")))
    return digest_entries(ordered), ordered
