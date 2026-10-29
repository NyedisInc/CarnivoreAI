
from __future__ import annotations

import difflib
import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.skills.manifest_preview import list_files, read_manifest_text

MAX_TEXT_FILE_BYTES = 32 * 1024
MAX_TEXT_FILES = 200
MAX_TEXT_TOTAL_BYTES = 512 * 1024
MAX_DIFF_LINES = 200
CACHE_ENTRIES = 24

KIND_TEXT = "text"
KIND_BINARY = "binary"
KIND_LARGE = "large"


@dataclass(frozen=True)
class ViewFile:

    path: str
    size: int
    kind: str
    sha256: str
    text: Optional[str]


@dataclass(frozen=True)
class ContentsView:

    digest: str
    manifest_text: str
    manifest_truncated: bool
    files: Tuple[ViewFile, ...]
    total_bytes: int


def _read_file(
    path: Path, relpath: str, size: int, budget_left: int, files_left: int
) -> ViewFile:
    if os.path.islink(path):
        return ViewFile(relpath, size, KIND_BINARY, "", None)
    keep = size <= MAX_TEXT_FILE_BYTES and size <= budget_left and files_left > 0
    digest = hashlib.sha256()
    chunks: List[bytes] = []
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
            if keep:
                chunks.append(chunk)
    sha = digest.hexdigest()
    if not keep:
        return ViewFile(relpath, size, KIND_LARGE, sha, None)
    raw = b"".join(chunks)
    if b"\0" in raw:
        return ViewFile(relpath, size, KIND_BINARY, sha, None)
    try:
        return ViewFile(relpath, size, KIND_TEXT, sha, raw.decode("utf-8"))
    except UnicodeDecodeError:
        return ViewFile(relpath, size, KIND_BINARY, sha, None)


def build_view(
    staged_dir: Path, kind: str, digest: str, exclude: Tuple[str, ...] = ()
) -> ContentsView:
    entries, total = list_files(staged_dir)
    entries = tuple(e for e in entries if e.relpath not in exclude)
    total = sum(e.size for e in entries)
    text, truncated = read_manifest_text(staged_dir, kind)
    out: List[ViewFile] = []
    budget = MAX_TEXT_TOTAL_BYTES
    left = MAX_TEXT_FILES
    for entry in entries:
        try:
            vf = _read_file(staged_dir / entry.relpath, entry.relpath, entry.size, budget, left)
        except OSError:
            vf = ViewFile(entry.relpath, entry.size, KIND_BINARY, "", None)
        if vf.text is not None:
            budget -= vf.size
            left -= 1
        out.append(vf)
    return ContentsView(digest, text, truncated, tuple(out), total)


class ContentsCache:

    def __init__(self, capacity: int = CACHE_ENTRIES) -> None:
        self._capacity = capacity
        self._items: "OrderedDict[str, ContentsView]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, digest: str) -> Optional[ContentsView]:
        with self._lock:
            view = self._items.get(digest)
            if view is not None:
                self._items.move_to_end(digest)
            return view

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def put(self, view: ContentsView) -> None:
        with self._lock:
            self._items[view.digest] = view
            self._items.move_to_end(view.digest)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)


default_cache = ContentsCache()


def _unified(old: str, new: str, path: str) -> Tuple[str, bool]:
    lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )
    cut = len(lines) > MAX_DIFF_LINES
    return "".join(x if x.endswith("\n") else x + "\n" for x in lines[:MAX_DIFF_LINES]), cut


def diff_views(old: ContentsView, new: ContentsView) -> Tuple[List[Dict[str, object]], int]:
    before = {f.path: f for f in old.files}
    after = {f.path: f for f in new.files}
    changes: List[Dict[str, object]] = []
    same = 0
    for path in sorted(set(before) | set(after)):
        a, b = before.get(path), after.get(path)
        if a is not None and b is not None and a.sha256 and a.sha256 == b.sha256:
            same += 1
            continue
        status = "changed" if a and b else ("added" if b else "removed")
        row: Dict[str, object] = {
            "path": path,
            "status": status,
            "old_size": a.size if a else None,
            "new_size": b.size if b else None,
            "diff": None,
            "diff_reason": None,
            "diff_truncated": False,
        }
        sides = [x for x in (a, b) if x is not None]
        if any(s.kind != KIND_TEXT for s in sides):
            row["diff_reason"] = KIND_BINARY if any(s.kind == KIND_BINARY for s in sides) else KIND_LARGE
        else:
            text, cut = _unified(a.text or "" if a else "", b.text or "" if b else "", path)
            row["diff"], row["diff_truncated"] = text, cut
        changes.append(row)
    return changes, same
