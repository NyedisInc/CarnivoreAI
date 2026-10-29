"""Sources a crate never reads, and the one way a source file is opened (plan 2.5).

A file is opened ``O_RDONLY | O_NOFOLLOW`` and refused when it is not a regular file, when its parent's real path is not
inside an allowed root, when its name matches a deny pattern, when its ``(st_dev, st_ino)`` is a known credential file's
(a hard link named like a transcript), or when it is an iCloud placeholder. A refusal names the path, never content.
"""

from __future__ import annotations

import fnmatch
import glob
import os
import stat
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk.transcript_files import dataless

DENY_NAMES: Tuple[str, ...] = (
    "auth.json", ".credentials.json", "credentials.json", ".claude.json", "config.toml",
    "*.sqlite", "*.sqlite-wal", "*.sqlite-shm",
    *sorted({os.path.basename(s.store) for s in cs.EXCLUDED_STORES if s.kind == cs.SECRET}),
)


class SourceForbidden(Exception):

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")
        self.path, self.detail = path, detail


class DatalessSource(SourceForbidden):
    pass


def _stat_key(path: Path) -> Tuple[int, int]:
    st = os.stat(path)
    return st.st_dev, st.st_ino


def deny_inodes(locs: cs.Locations) -> Set[Tuple[int, int]]:
    codex = Path(locs.codex_home())
    candidates: List[Path] = [codex / "auth.json", *map(Path, glob.glob(str(codex / "*.sqlite*")))]
    candidates += list(cs.claude_json_files(locs))
    candidates += [Path(h) / ".credentials.json" for h in locs.claude_homes()]
    for store in cs.EXCLUDED_STORES:
        if store.kind == cs.SECRET:
            candidates += [Path(p) for p in glob.glob(str(Path(locs.state_dir) / store.store))]
    out: Set[Tuple[int, int]] = set()
    for path in candidates:
        try:
            out.add(_stat_key(path))
        except OSError:
            continue
    return out


def allowed_roots(locs: cs.Locations, project_roots: Iterable[str] = ()) -> List[str]:
    roots: List[Path] = []
    for home in locs.claude_homes():
        roots += [Path(home) / sub for sub in ("projects", "file-history", "todos", "plans")]
    codex = Path(locs.codex_home())
    roots += [codex / "sessions", codex / "archived_sessions"]
    state = Path(locs.state_dir)
    roots += [state / "cplugs" / "huddle" / "files", state / "swarm" / "desk"]
    roots += [Path(p) for p in project_roots]
    return sorted({os.path.realpath(str(r)) for r in roots})


def _under(real_parent: str, roots: Sequence[str]) -> bool:
    return any(real_parent == r or real_parent.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def project_root_problem(root: str, locs: cs.Locations) -> Optional[str]:
    real = os.path.realpath(root)
    if not os.path.isdir(real):
        return f"the project folder {root} does not exist or is not a folder"
    homes = [os.path.realpath(str(h)) for h in locs.claude_homes()]
    homes += [os.path.realpath(str(locs.codex_home())), os.path.realpath(str(locs.state_dir))]
    for home in homes:
        if _under(real, [home]):
            return f"the project folder {root} is inside a live harness home or the state folder"
        if _under(home, [real]):
            return f"the project folder {root} holds a live harness home or the state folder"
    return None


def open_source(path: str, roots: Sequence[str], deny: Set[Tuple[int, int]],
                names: bool = True) -> Tuple[int, os.stat_result]:
    name = os.path.basename(path)
    if names and any(fnmatch.fnmatch(name, pattern) for pattern in DENY_NAMES):
        raise SourceForbidden(path, "a credential or database file by its name")
    if not _under(os.path.realpath(os.path.dirname(path)), roots):
        raise SourceForbidden(path, "outside every folder a crate reads")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if os.path.islink(path):
            raise SourceForbidden(path, "a symlink, never followed") from exc
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SourceForbidden(path, "not a regular file")
        if (st.st_dev, st.st_ino) in deny:
            raise SourceForbidden(path, "the same file as a credential store (a hard link)")
        if dataless.is_dataless_file(Path(path)):
            raise DatalessSource(path, "an iCloud placeholder whose bytes are not on this disk")
    except BaseException:
        os.close(fd)
        raise
    return fd, st
