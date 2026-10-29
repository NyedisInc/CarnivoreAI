
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.core.project_move.icloud import SF_DATALESS
from src.core.project_pack import constants as K

KIND_FILE, KIND_DIR, KIND_LINK = "f", "d", "l"
DATALESS_LIST_LIMIT = 20


class InventoryError(Exception):
    """The folder could not be read as a plain tree (an unreadable entry, a device file, a cloud-only file)."""


@dataclass
class Entry:

    path: str
    kind: str
    size: int = 0
    mode: int = 0
    mtime_ns: int = 0
    link: Optional[str] = None
    sha256: Optional[str] = None
    group: Optional[int] = None
    blocks: int = 0

    def as_row(self) -> list:
        return [self.path, self.kind, self.size, self.mode, self.mtime_ns, self.link, self.sha256, self.group]

    @classmethod
    def from_row(cls, row: list) -> "Entry":
        return cls(path=row[0], kind=row[1], size=row[2], mode=row[3], mtime_ns=row[4], link=row[5],
                   sha256=row[6], group=row[7])


@dataclass
class Tree:

    entries: List[Entry] = field(default_factory=list)
    dataless: int = 0
    dataless_paths: List[str] = field(default_factory=list)
    allocated_bytes: int = 0
    transcript_hits: List[str] = field(default_factory=list)
    top_sizes: Dict[str, int] = field(default_factory=dict)
    unreadable: List[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(1 for e in self.entries if e.kind == KIND_FILE)

    @property
    def logical_bytes(self) -> int:
        return sum(e.size for e in self.entries if e.kind == KIND_FILE)

    @property
    def newest_mtime_ns(self) -> int:
        return max((e.mtime_ns for e in self.entries), default=0)

    def top_level(self) -> List[str]:
        return sorted({e.path.split("/", 1)[0] for e in self.entries})


def walk(root: str, skip_top: Iterable[str] = ()) -> Tree:
    skip: Set[str] = set(skip_top)
    tree = Tree()
    seen: Dict[Tuple[int, int], int] = {}
    stack: List[Tuple[str, str]] = [(root, "")]
    while stack:
        abs_dir, rel_dir = stack.pop()
        try:
            with os.scandir(abs_dir) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            if not rel_dir:
                raise InventoryError(f"cannot list {abs_dir}: {exc}") from exc
            tree.unreadable.append(rel_dir)
            continue
        dir_name = os.path.basename(abs_dir)
        for child in children:
            if not rel_dir and child.name in skip:
                continue
            rel = f"{rel_dir}/{child.name}" if rel_dir else child.name
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                tree.unreadable.append(rel)
                continue
            _record(tree, seen, stack, child, rel, st)
            if stat.S_ISDIR(st.st_mode) and (
                    (child.name == "projects" and dir_name == ".claude")
                    or (child.name.startswith(K.TRANSCRIPT_KEY_PREFIX) and len(child.name) > 1
                        and _holds_jsonl(child.path))):
                tree.transcript_hits.append(rel)
    tree.entries.sort(key=lambda e: e.path)
    for entry in tree.entries:
        if entry.kind == KIND_FILE:
            top = entry.path.split("/", 1)[0]
            tree.top_sizes[top] = tree.top_sizes.get(top, 0) + entry.size
    return tree


def _holds_jsonl(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return any(e.name.endswith(K.TRANSCRIPT_SUFFIX) for e in it)
    except OSError:
        return False


def _record(tree: Tree, seen: Dict[Tuple[int, int], int], stack: list, child: os.DirEntry, rel: str,
            st: os.stat_result) -> None:
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISDIR(st.st_mode):
        tree.entries.append(Entry(rel, KIND_DIR, mode=mode, mtime_ns=st.st_mtime_ns))
        stack.append((child.path, rel))
    elif stat.S_ISLNK(st.st_mode):
        tree.entries.append(Entry(rel, KIND_LINK, mode=mode, mtime_ns=st.st_mtime_ns, link=os.readlink(child.path)))
    elif stat.S_ISREG(st.st_mode):
        group = None
        if st.st_nlink > 1:
            group = seen.setdefault((st.st_dev, st.st_ino), len(seen) + 1)
        if getattr(st, "st_flags", 0) & SF_DATALESS:
            tree.dataless += 1
            if len(tree.dataless_paths) < DATALESS_LIST_LIMIT:
                tree.dataless_paths.append(rel)
        tree.allocated_bytes += st.st_blocks * 512
        tree.entries.append(Entry(rel, KIND_FILE, size=st.st_size, mode=mode, mtime_ns=st.st_mtime_ns,
                                  group=group, blocks=st.st_blocks))
    else:
        raise InventoryError(f"{rel} is a device, socket or pipe; it cannot be packed exactly")


def stat_signature(entries: Iterable[Entry]) -> str:
    digest = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x.path):
        digest.update(f"{e.path}\0{e.kind}\0{e.size}\0{e.mode}\0{e.mtime_ns}\0{e.link or ''}\n".encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def sha256_file(path: str, progress: Optional[Callable[[int], None]] = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(K.HASH_CHUNK), b""):
            digest.update(chunk)
            if progress:
                progress(len(chunk))
    return digest.hexdigest()


def hash_files(root: str, entries: List[Entry], progress: Optional[Callable[[int], None]] = None) -> None:
    """Fill ``sha256`` on every regular file, reading it once. A cloud-only file is never read.

    Inputs: root; entries (modified in place); progress(bytes) called per chunk.
    Output: None. Raises: InventoryError - a file turned cloud-only, vanished or could not be read.
    """
    for entry in entries:
        if entry.kind != KIND_FILE:
            continue
        full = os.path.join(root, entry.path)
        try:
            if getattr(os.lstat(full), "st_flags", 0) & SF_DATALESS:
                raise InventoryError(f"{entry.path} is in iCloud only; download it in Finder first")
            entry.sha256 = sha256_file(full, progress)
        except OSError as exc:
            raise InventoryError(f"cannot read {entry.path}: {exc}") from exc


def top_level_names(entries: Iterable[Entry]) -> List[str]:
    return sorted({e.path.split("/", 1)[0] for e in entries})


def estimate_archive_bytes(entries: Iterable[Entry]) -> Tuple[int, int]:
    compressible = other = 0
    for e in entries:
        if e.kind != KIND_FILE:
            continue
        if e.path.lower().endswith(K.INCOMPRESSIBLE_SUFFIXES):
            other += e.size
        else:
            compressible += e.size
    return (int(compressible * K.ESTIMATE_RATIO_LOW + other), int(compressible * K.ESTIMATE_RATIO_HIGH + other))
