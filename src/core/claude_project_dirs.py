
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

from src.core.claude_transcript_correlate import (
    default_projects_dir,
    slugify_project_dir,
)

logger = structlog.get_logger()

HOME_ALIAS_SCAN_DEPTH = 1


def _real(path: str) -> Optional[str]:
    if not path:
        return None
    try:
        return os.path.realpath(path)
    except OSError as exc:
        logger.debug("claude_project_dir_realpath_failed", path=path, error=str(exc))
        return None


HOME_ALIAS_TTL_SECONDS = 60.0

_ALIAS_LOCK = threading.Lock()
_ALIAS_CACHE: dict = {}


def _alias_clock() -> float:
    return time.monotonic()


def _home_dir_aliases(home: Optional[Path] = None) -> List[tuple]:
    base = home if home is not None else Path.home()
    try:
        key = (str(base), os.stat(base).st_mtime_ns)
    except OSError as exc:
        logger.debug("claude_project_dir_home_scan_failed", home=str(base), error=str(exc))
        return []
    now = _alias_clock()
    with _ALIAS_LOCK:
        hit = _ALIAS_CACHE.get(key)
    if hit is not None and now - hit[0] < HOME_ALIAS_TTL_SECONDS:
        return list(hit[1])
    out = _scan_home_aliases(base)
    if out is not None:
        with _ALIAS_LOCK:
            for old in [k for k in _ALIAS_CACHE if k[0] == key[0]]:
                del _ALIAS_CACHE[old]
            _ALIAS_CACHE[key] = (now, tuple(out))
    return out or []


def _scan_home_aliases(base: Path) -> Optional[List[tuple]]:
    out: List[tuple] = []
    try:
        entries = sorted(os.listdir(base))
    except OSError as exc:
        logger.debug("claude_project_dir_home_scan_failed", home=str(base), error=str(exc))
        return None
    for name in entries:
        link = os.path.join(str(base), name)
        try:
            if not os.path.islink(link) or not os.path.isdir(link):
                continue
        except OSError:
            continue
        target = _real(link)
        if target and target != link:
            out.append((link, target))
    return out


def path_spellings(
    working_dir: Optional[str], *, home: Optional[Path] = None
) -> List[str]:
    if not working_dir:
        return []
    seen: List[str] = [working_dir]
    resolved = _real(working_dir)
    if resolved and resolved not in seen:
        seen.append(resolved)
    anchor = resolved or working_dir
    for link, target in _home_dir_aliases(home=home):
        if anchor == target:
            alias = link
        elif anchor.startswith(target.rstrip("/") + "/"):
            alias = link.rstrip("/") + anchor[len(target.rstrip("/")):]
        else:
            continue
        if alias not in seen:
            seen.append(alias)
    return seen


def candidate_project_dirs(
    working_dir: Optional[str],
    *,
    projects_dir: Optional[Path] = None,
    home: Optional[Path] = None,
    existing: Optional[Sequence[str]] = None,
    default_dir: Optional[Path] = None,
) -> List[Path]:
    if projects_dir is not None:
        bases: Sequence[Path] = (projects_dir,)
    elif existing is not None:
        bases = (default_dir or default_projects_dir(),)
    else:
        from src.core.claude_config.profile_roots import PROJECTS_DIRNAME, profile_subdir_roots

        bases = profile_subdir_roots(default_dir or default_projects_dir(), PROJECTS_DIRNAME)
    known = set(existing) if existing is not None else None
    out: List[Path] = []
    for spelling in path_spellings(working_dir, home=home):
        for base in bases:
            candidate = base / slugify_project_dir(spelling)
            if candidate in out:
                continue
            if known is not None:
                if candidate.name in known:
                    out.append(candidate)
                continue
            try:
                if candidate.is_dir():
                    out.append(candidate)
            except OSError as exc:
                logger.debug(
                    "claude_project_dir_stat_failed",
                    candidate=str(candidate),
                    error=str(exc),
                )
    return out


def same_directory(
    left: Optional[str], right: Optional[str], *, home: Optional[Path] = None
) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    lr = _real(left)
    rr = _real(right)
    if lr is None or rr is None:
        return False
    return lr == rr


def project_dir_names(dirs: Sequence[Path]) -> List[str]:
    return [d.name for d in dirs]
