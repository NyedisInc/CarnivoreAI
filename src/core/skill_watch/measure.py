"""A bounded, read-only measurement of one installed skill folder for Sentinel.

Two jobs the signed digest (``src.core.skills.digest``) deliberately does not do:

- It is BOUNDED: at most :data:`MAX_FILES` files, :data:`MAX_BYTES` bytes and
  :data:`MAX_SECONDS` seconds, else :class:`TooLarge`. A folder that later grows a
  ``node_modules`` or a multi-GB file is reported unmeasurable, never hashed in full.
- It is SAFE to point at a hostile folder: every entry is lstat-ed first, a file is
  opened ``O_NOFOLLOW | O_NONBLOCK`` and ``fstat``-ed regular AFTER the open (a
  file swapped for a FIFO or a symlink between the two steps is refused, never read
  and never blocks), and nothing outside the folder is opened.

The signed digest skips anything that is not a regular file, so an added symlink,
FIFO, socket, device or an unreadable subdirectory would leave it unchanged. Here each
of those is returned as an ANOMALY such as ``refs (symlink)``, and Sentinel counts an
anomaly as drift.
"""

from __future__ import annotations

import hashlib
import os
import stat
import time
from typing import List, Tuple

from src.core.skills.digest import CHUNK_BYTES, DigestEntry, mode_string
from src.core.skills.records import SIDECAR_NAME

MAX_FILES = 5000
MAX_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 2.0
MAX_ANOMALIES = 50

_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class TooLarge(Exception):
    pass


def _kind(mode: int) -> str:
    for test, word in ((stat.S_ISLNK, "symlink"), (stat.S_ISFIFO, "fifo"), (stat.S_ISSOCK, "socket"),
                       (stat.S_ISBLK, "device"), (stat.S_ISCHR, "device"), (stat.S_ISDIR, "directory")):
        if test(mode):
            return word
    return "special"


def _hash_regular(full: str, budget: List[int], deadline: float) -> Tuple[str, bool]:
    fd = os.open(full, _OPEN_FLAGS)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        digest = hashlib.sha256()
        while True:
            if time.monotonic() > deadline:
                raise TooLarge("time")
            chunk = os.read(fd, CHUNK_BYTES)
            if not chunk:
                break
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise TooLarge("bytes")
            digest.update(chunk)
        return digest.hexdigest(), bool(info.st_mode & stat.S_IXUSR)
    finally:
        os.close(fd)


def measure_bounded(root: str) -> Tuple[Tuple[DigestEntry, ...], Tuple[str, ...]]:
    deadline = time.monotonic() + MAX_SECONDS
    budget = [MAX_BYTES]
    entries: List[DigestEntry] = []
    anomalies: set = set()

    def rel(path: str) -> str:
        return os.path.relpath(path, root).replace(os.sep, "/")

    def unreadable(exc: OSError) -> None:
        anomalies.add(f"{rel(exc.filename) if exc.filename else '.'} (unreadable)")

    files = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=unreadable):
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                anomalies.add(f"{rel(full)} (symlink)")
        for name in filenames:
            files += 1
            if files > MAX_FILES or time.monotonic() > deadline:
                raise TooLarge("files" if files > MAX_FILES else "time")
            full = os.path.join(dirpath, name)
            relpath = rel(full)
            if relpath == SIDECAR_NAME:
                continue
            try:
                mode = os.lstat(full).st_mode
                if not stat.S_ISREG(mode):
                    anomalies.add(f"{relpath} ({_kind(mode)})")
                    continue
                hex_digest, executable = _hash_regular(full, budget, deadline)
            except ValueError:
                anomalies.add(f"{relpath} (special)")
                continue
            except OSError:
                anomalies.add(f"{relpath} (unreadable)")
                continue
            entries.append(DigestEntry(relpath=relpath, mode=mode_string(executable), sha256=hex_digest))
    ordered = tuple(sorted(entries, key=lambda e: e.relpath.encode("utf-8")))
    return ordered, tuple(sorted(anomalies))[:MAX_ANOMALIES]
