
from __future__ import annotations

import io
import re
import subprocess
import threading
from typing import Dict, Iterator, List, Optional, Set, Tuple

from src.core.pack.transport import ladder

GIT_TIMEOUT_S = 300.0
BATCH_BYTES = 16 * 1024 * 1024
MAX_HISTORY_OBJECTS = 500_000
MAX_NAMED_COMMITS = 200
_OBJECT_LINE = re.compile(rb"^([0-9a-f]{40}(?:[0-9a-f]{24})?)(?: (.*))?$")
_RAW_LINE = re.compile(r"^:\d+ \d+ [0-9a-f]+ ([0-9a-f]+) [A-Z]+\t")


class HistoryScanError(Exception):
    pass


class HistoryScanFailed(HistoryScanError):

    def __init__(self, reason: str, paths: Optional[List[str]] = None) -> None:
        super().__init__(reason)
        self.reason, self.paths = reason, paths or []


class HistoryTooBig(HistoryScanError):

    def __init__(self, limit: int) -> None:
        super().__init__("history over the object cap")
        self.limit = limit


class HistoryBudgetExceeded(HistoryScanError):

    def __init__(self, paths: List[str]) -> None:
        super().__init__("history over the scan budget")
        self.paths = paths


def git(root: str, *args: str, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    try:
        return ladder.run(["git", "-C", root, *args], air_gap=False, stdin=stdin, timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise HistoryScanFailed("timeout") from None


class ViewStream(io.RawIOBase):

    def __init__(self, view: memoryview) -> None:
        super().__init__()
        self._view, self._pos = view, 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        count = min(len(buffer), len(self._view) - self._pos)
        buffer[:count] = self._view[self._pos:self._pos + count]
        self._pos += count
        return count


def _stream_lines(root: str, *args: str) -> Iterator[bytes]:
    try:
        proc = ladder.stream(["git", "-C", root, *args], air_gap=False)
    except OSError:
        raise HistoryScanFailed(f"{args[0]}_start") from None
    if proc.stdout is None:
        proc.kill()
        proc.wait()
        raise HistoryScanFailed(f"{args[0]}_pipe")
    watchdog = threading.Timer(GIT_TIMEOUT_S, proc.kill)
    watchdog.start()
    finished = False
    try:
        for line in proc.stdout:
            yield line.rstrip(b"\n")
        finished = True
    finally:
        watchdog.cancel()
        if not finished:
            proc.kill()
        proc.stdout.close()
        status = proc.wait()
    if status != 0:
        raise HistoryScanFailed(args[0])


def reachable_objects(root: str, rev: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    lines = _stream_lines(root, "rev-list", "--objects", rev, "--")
    for line in lines:
        match = _OBJECT_LINE.match(line)
        if match:
            out.setdefault(match.group(1).decode("ascii"), (match.group(2) or b"").decode("utf-8", "replace"))
            if len(out) > MAX_HISTORY_OBJECTS:
                lines.close()
                raise HistoryTooBig(MAX_HISTORY_OBJECTS)
    return out


def object_sizes(root: str, ids: List[str]) -> Dict[str, Tuple[str, int]]:
    if not ids:
        return {}
    done = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", stdin=("\n".join(ids) + "\n").encode("ascii"))
    if done.returncode != 0:
        raise HistoryScanFailed("batch_check")
    sizes: Dict[str, Tuple[str, int]] = {}
    for line in done.stdout.decode("ascii", "replace").splitlines():
        parts = line.split(" ")
        if len(parts) != 3:
            raise HistoryScanFailed("missing_object")
        if parts[1] in ("blob", "commit"):
            sizes[parts[0]] = (parts[1], int(parts[2]))
    return sizes


def batches(sizes: Dict[str, Tuple[str, int]]) -> Iterator[List[str]]:
    group: List[str] = []
    total = 0
    for object_id, (_kind, size) in sizes.items():
        if group and total + size > BATCH_BYTES:
            yield group
            group, total = [], 0
        group.append(object_id)
        total += size
    if group:
        yield group


def read_batch(root: str, ids: List[str]) -> Iterator[Tuple[str, memoryview]]:
    done = git(root, "cat-file", "--batch", stdin=("\n".join(ids) + "\n").encode("ascii"))
    if done.returncode != 0:
        raise HistoryScanFailed("batch")
    data, view, pos = done.stdout, memoryview(done.stdout), 0
    for _ in ids:
        end = data.find(b"\n", pos)
        header = data[pos:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or not header[2].isdigit():
            raise HistoryScanFailed("batch_parse")
        start, size = end + 1, int(header[2])
        if start + size > len(data):
            raise HistoryScanFailed("batch_parse")
        yield header[0].decode("ascii"), view[start:start + size]
        pos = start + size + 1


def _short_ids(root: str, commit_ids: List[str]) -> Dict[str, str]:
    wanted = sorted(set(commit_ids))[:MAX_NAMED_COMMITS]
    if not wanted:
        return {}
    try:
        done = git(root, "log", "--no-walk=unsorted", "--format=%H %h", *wanted, "--")
    except HistoryScanFailed:
        return {}
    if done.returncode != 0:
        return {}
    pairs = (line.split(" ", 1) for line in done.stdout.decode("ascii", "replace").splitlines() if " " in line)
    return {full: short for full, short in pairs}


def commit_names(root: str, rev: str, blob_ids: Set[str], commit_ids: Set[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    added: Dict[str, str] = {}
    current = ""
    try:
        for raw_line in (_stream_lines(root, "log", "--raw", "--no-abbrev", "--no-renames", "--format=%H", rev, "--") if blob_ids else ()):
            line = raw_line.decode("utf-8", "replace")
            raw = _RAW_LINE.match(line)
            if raw:
                if raw.group(1) in blob_ids:
                    added[raw.group(1)] = current
            elif line:
                current = line.strip()
    except HistoryScanFailed:
        added = {}
    shorts = _short_ids(root, [*commit_ids, *added.values()])
    return shorts, {blob: shorts.get(commit, commit[:12]) for blob, commit in added.items()}


def git_common_dir(root: str) -> str:
    done = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    path = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not path:
        raise HistoryScanFailed("git_dir")
    return path
