
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger()

NO_COMMITS, NO_REMOTE = "no_commits", "no_remote"
MESSAGES = {
    NO_COMMITS: "the boards checkout has no commits, so no board is in any history; commit the boards so they can be restored",
    NO_REMOTE: "the boards checkout has no remote, so nothing copies the boards off this disk; add a remote and push",
}
_REMOTE_SECTION = re.compile(r'^\s*\[remote\s+"', re.MULTILINE)


@dataclass(frozen=True)
class CheckoutWarning:

    code: str
    message: str


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _git_dirs(folder: Path) -> Optional[Tuple[Path, Path]]:
    for candidate in (folder, *folder.parents):
        dot = candidate / ".git"
        if dot.is_dir():
            return dot, dot
        if dot.is_file():
            text = _read(dot) or ""
            match = re.match(r"gitdir:\s*(.+)", text.strip())
            if not match:
                return None
            git_dir = (candidate / match.group(1).strip()).resolve()
            if not git_dir.is_dir():
                return None
            pointer = _read(git_dir / "commondir")
            return git_dir, ((git_dir / pointer.strip()).resolve() if pointer and pointer.strip() else git_dir)
    return None


def _has_commit(git_dir: Path, common: Path) -> Optional[bool]:
    head = _read(git_dir / "HEAD")
    if head is None or not head.strip():
        return None
    head = head.strip()
    if not head.startswith("ref:"):
        return True
    ref = head[4:].strip()
    if (common / ref).is_file() or (git_dir / ref).is_file():
        return True
    packed = _read(common / "packed-refs") or ""
    return any(line.split(" ", 1)[-1].strip() == ref for line in packed.splitlines() if line and line[0] not in "#^")


def warnings_for(folder: Path) -> List[CheckoutWarning]:
    dirs = _git_dirs(folder)
    if dirs is None:
        return []
    git_dir, common = dirs
    out: List[CheckoutWarning] = []
    committed = _has_commit(git_dir, common)
    if committed is False:
        out.append(CheckoutWarning(NO_COMMITS, MESSAGES[NO_COMMITS]))
    config = _read(common / "config")
    if config is not None and not _REMOTE_SECTION.search(config):
        out.append(CheckoutWarning(NO_REMOTE, MESSAGES[NO_REMOTE]))
    if out:
        logger.warning("reviewboard_checkout_unsafe", codes=[w.code for w in out])
    return out
