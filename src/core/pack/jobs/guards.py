
from __future__ import annotations

import os
from typing import Iterable, List, Optional, Tuple

DEP_DIR_NAMES = {"node_modules", ".venv", "venv", "__pycache__"}
_DEP_FOLDED = {n.casefold() for n in DEP_DIR_NAMES}
LAND_TEMP_MARK = ".carn-land-"
MAX_UNTRACKED_BYTES = 50 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 ** 3
MAX_UNTRACKED_FILES = 20000


def is_dep_name(part: str) -> bool:
    return part.casefold() in _DEP_FOLDED


def skip_reason(rel: str, abs_path: str) -> Optional[str]:
    for part in rel.split("/"):
        if is_dep_name(part):
            return f"dependency folder {part}"
    if LAND_TEMP_MARK in os.path.basename(rel.rstrip("/")):
        return "a leftover of an interrupted land"
    if rel.endswith("/") or os.path.lexists(os.path.join(abs_path, ".git")):
        return "a nested repository"
    try:
        size = os.lstat(abs_path).st_size
    except OSError:
        return None
    if size > MAX_UNTRACKED_BYTES:
        return f"larger than {MAX_UNTRACKED_BYTES // (1024 * 1024)} MiB"
    return None


def exclude_pathspecs() -> List[str]:
    return [f":(exclude,glob)**/{name}/**" for name in sorted(DEP_DIR_NAMES)]


def oversize(changes: Iterable[Tuple[str, Optional[str], Optional[str]]], **git_where: str) -> Optional[str]:
    from src.core.pack.jobs import gitio

    new = [(path, sha) for path, old, sha in changes if sha and sha != old]
    if not new:
        return None
    raw = gitio.run(["cat-file", "--batch-check=%(objectsize)"], input="".join(f"{sha}\n" for _p, sha in new).encode(), **git_where).stdout
    sizes = [int(x) if x.isdigit() else 0 for x in raw.decode().splitlines()]
    held = {path for path, old, _sha in changes if old}
    for (path, _sha), size in zip(new, sizes):
        if size > MAX_UNTRACKED_BYTES and path not in held:
            return f"{path} is larger than {MAX_UNTRACKED_BYTES // (1024 * 1024)} MiB"
    if sum(sizes) > MAX_SNAPSHOT_BYTES:
        return f"the result is larger than {MAX_SNAPSHOT_BYTES // 1024 ** 3} GiB"
    return None
