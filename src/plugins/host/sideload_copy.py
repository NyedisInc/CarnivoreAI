
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Dict, List, Tuple

from src.core.skills.validate_types import EXCLUDED_BASENAME_PREFIXES, EXCLUDED_BASENAMES
from src.plugins.host.sideload_errors import SideloadRefused

MAX_FILES = 2000
MAX_BYTES = 20 * 1024 * 1024
_SKIP_DIRS = frozenset({"__pycache__", ".git"})
_SKIP_SUFFIXES = (".pyc", ".pyo")


def _copy_one(dirfd: int, name: str, dest: Path, budget: int) -> Tuple[str, int]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    except OSError as exc:
        raise SideloadRefused("source_unsafe", "the folder holds a link or a file that cannot be opened safely", 422) from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise SideloadRefused("source_unsafe", "the folder holds a link, a special file or a hard-linked file; sideload copies real files only", 422)
        if info.st_size > budget:
            raise SideloadRefused("source_too_big", f"a sideload is capped at {MAX_FILES} files and {MAX_BYTES // 1048576} MB", 422)
        data = handle.read(info.st_size + 1)
    if len(data) != info.st_size:
        raise SideloadRefused("source_unsafe", "a file changed while it was being copied", 422)
    with open(dest, "xb") as out:
        out.write(data)
    os.chmod(dest, 0o755 if info.st_mode & stat.S_IXUSR else 0o644)
    return hashlib.sha256(data).hexdigest(), info.st_size


_SF_DATALESS = 0x40000000


def is_placeholder(name: str, flags: int) -> bool:
    return (name.startswith(".") and name.endswith(".icloud")) or bool(flags & _SF_DATALESS)


def is_noise(name: str) -> bool:
    return name in EXCLUDED_BASENAMES or name.startswith(EXCLUDED_BASENAME_PREFIXES)


def copy_tree(source: Path, dest: Path) -> Dict[str, str]:
    files: Dict[str, str] = {}
    total = 0
    pending: set = set()
    dest.mkdir(parents=True)
    for root, dirs, names, dirfd in os.fwalk(source, follow_symlinks=False):
        rel_root = Path(root).relative_to(source)
        pending.discard(rel_root.as_posix())
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for d in dirs:
            if not stat.S_ISDIR(os.stat(d, dir_fd=dirfd, follow_symlinks=False).st_mode):
                raise SideloadRefused("source_unsafe", "the folder holds a link; sideload copies real files only", 422)
            (dest / rel_root / d).mkdir(parents=True, exist_ok=True)
            pending.add((rel_root / d).as_posix())
        for n in sorted(names):
            if n.endswith(_SKIP_SUFFIXES) or is_noise(n):
                continue
            info = os.stat(n, dir_fd=dirfd, follow_symlinks=False)
            if is_placeholder(n, getattr(info, "st_flags", 0)):
                raise SideloadRefused("source_not_downloaded", "the folder has files that are not downloaded from iCloud yet; download the folder first", 422)
            if not stat.S_ISREG(info.st_mode):
                raise SideloadRefused("source_unsafe", "the folder holds a link or special file; sideload copies real files only", 422)
            if len(files) >= MAX_FILES:
                raise SideloadRefused("source_too_big", f"a sideload is capped at {MAX_FILES} files and {MAX_BYTES // 1048576} MB", 422)
            rel = rel_root / n
            files[rel.as_posix()], size = _copy_one(dirfd, n, dest / rel, MAX_BYTES - total)
            total += size
    if pending:
        raise SideloadRefused("source_unsafe", "a folder changed while it was being copied", 422)
    return files


def changed_files(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
