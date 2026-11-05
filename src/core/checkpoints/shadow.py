
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.core.swarm.gitrun import run_git

SHADOW_DIRNAME = "checkpoints"
GIT_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class RepoPaths:

    work_tree: Path
    git_dir: Path
    common_dir: Path
    index: Path
    shadow: Path


def _rev_parse(directory: Path, answers: int, *flags: str) -> Optional[list]:
    proc = run_git(directory, "rev-parse", *flags, timeout=GIT_TIMEOUT_S, optional_locks=False, untrusted_repo=True)
    if proc.returncode != 0:
        return None
    lines = proc.stdout.splitlines()
    return lines if len(lines) == answers else None


def shadow_key(common_dir: Path) -> str:
    return hashlib.sha256(str(common_dir.resolve()).encode("utf-8", "surrogateescape")).hexdigest()[:32] + ".git"


def resolve(directory: Path, state_root: Path) -> Optional[RepoPaths]:
    found = _rev_parse(directory, 5, "--is-inside-work-tree", "--show-toplevel", "--absolute-git-dir",
                       "--git-common-dir", "--git-path", "index")
    if not found or found[0] != "true":
        return None
    _, top, git_dir, common, index = found
    common_path = Path(common) if os.path.isabs(common) else (directory / common)
    index_path = Path(index) if os.path.isabs(index) else (directory / index)
    common_path = common_path.resolve()
    return RepoPaths(work_tree=Path(top), git_dir=Path(git_dir), common_dir=common_path, index=index_path,
                     shadow=state_root / SHADOW_DIRNAME / shadow_key(common_path))


def ensure(paths: RepoPaths) -> None:
    shadow = paths.shadow
    if not (shadow / "HEAD").is_file():
        shadow.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        proc = run_git(shadow.parent, "init", "--bare", "-q", str(shadow), timeout=GIT_TIMEOUT_S)
        if proc.returncode != 0:
            raise OSError(f"git init of the checkpoint store failed ({proc.returncode})")
        os.chmod(shadow, 0o700)
    alternates = shadow / "objects" / "info" / "alternates"
    want = str(paths.common_dir / "objects") + "\n"
    if not alternates.is_file() or alternates.read_text() != want:
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(want)


def _escape(rel: str) -> str:
    out = rel.replace("\\", "\\\\")
    for ch in "*?[!#":
        out = out.replace(ch, "\\" + ch)
    if out.endswith(" "):
        out = out[:-1] + "\\ "
    return "/" + out


def write_excludes(paths: RepoPaths, left_out: Iterable[str]) -> None:
    own = paths.common_dir / "info" / "exclude"
    try:
        base = own.read_text(encoding="utf-8", errors="surrogateescape")
    except FileNotFoundError:
        base = ""
    lines = [base.rstrip("\n")] if base else []
    lines += [_escape(rel) for rel in left_out if "\n" not in rel]
    target = paths.shadow / "info" / "exclude"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="surrogateescape")
