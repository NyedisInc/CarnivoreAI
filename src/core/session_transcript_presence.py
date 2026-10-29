
from __future__ import annotations

import errno
import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import structlog

logger = structlog.get_logger()

CONVERSATION_PRESENT = "present"

CONVERSATION_ABSENT = "absent"

CONVERSATION_UNCHECKED = "unchecked"

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


STATUS_CACHE_SECONDS = 2.0

_CACHE_MAX_ENTRIES = 512

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str, str], Tuple[float, "ConversationPresence"]] = {}


_LOCATE_MAX_ENTRIES = 2048

_RACY_WINDOW_NS = 2_000_000_000

_locate_lock = threading.Lock()
_found_paths: Dict[Tuple[str, str], Tuple[int, Path]] = {}
_root_listings: Dict[str, Tuple[int, Tuple[Path, ...]]] = {}


@dataclass(frozen=True)
class ConversationPresence:

    outcome: str
    path: Optional[Path] = None
    detail: Optional[str] = None

    @property
    def missing(self) -> bool:
        return self.outcome == CONVERSATION_ABSENT


def _cache_get(key: Tuple[str, str, str], max_age: float) -> Optional["ConversationPresence"]:
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < max_age:
        return hit[1]
    return None


def _cache_put(key: Tuple[str, str, str], value: "ConversationPresence") -> None:
    now = time.monotonic()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            for old in [k for k, (at, _v) in _cache.items() if now - at >= STATUS_CACHE_SECONDS]:
                del _cache[old]
            if len(_cache) >= _CACHE_MAX_ENTRIES:
                del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (now, value)


def conversation_presence(
    claude_session_uuid: Optional[str],
    *,
    working_dir: Optional[str] = None,
    corpus_root: Optional[Path] = None,
    cache_seconds: float = 0.0,
) -> ConversationPresence:
    key = (str(claude_session_uuid), str(working_dir or ""), str(corpus_root or ""))
    if cache_seconds > 0:
        cached = _cache_get(key, cache_seconds)
        if cached is not None:
            return cached
    result = _measure_presence(claude_session_uuid, working_dir=working_dir, corpus_root=corpus_root)
    if cache_seconds > 0:
        _cache_put(key, result)
    return result


def _is_racy(stamp_ns: int) -> bool:
    return time.time_ns() - stamp_ns < _RACY_WINDOW_NS


def _remembered_path(root: Path, filename: str) -> Optional[Path]:
    key = (str(root), filename)
    with _locate_lock:
        entry = _found_paths.get(key)
    if entry is None:
        return None
    try:
        if os.stat(root).st_mtime_ns == entry[0] and entry[1].is_file():
            return entry[1]
    except OSError as exc:
        logger.debug("conversation_presence_remembered_unreadable", path=str(entry[1]), error=str(exc))
    with _locate_lock:
        _found_paths.pop(key, None)
    return None


def _remember_path(root: Path, filename: str, path: Path) -> None:
    try:
        stamp = os.stat(root).st_mtime_ns
    except OSError:
        return
    if _is_racy(stamp):
        return
    with _locate_lock:
        if len(_found_paths) >= _LOCATE_MAX_ENTRIES:
            _found_paths.clear()
        _found_paths[(str(root), filename)] = (stamp, path)


def _forget_root_listing(root: Path) -> None:
    with _locate_lock:
        _root_listings.pop(str(root), None)


def _root_children(root: Path) -> Tuple[Tuple[Path, ...], bool]:
    stamp = os.stat(root).st_mtime_ns
    key = str(root)
    with _locate_lock:
        hit = _root_listings.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1], True
    children = tuple(sorted(root.iterdir()))
    if not _is_racy(stamp):
        with _locate_lock:
            if len(_root_listings) >= _LOCATE_MAX_ENTRIES:
                _root_listings.clear()
            _root_listings[key] = (stamp, children)
    return children, False


def _scan_children(
    children: Tuple[Path, ...], filename: str, root: Path
) -> Tuple[Optional[Path], bool]:
    unreadable = False
    for child in children:
        candidate = child / filename
        try:
            if stat.S_ISREG(os.stat(candidate).st_mode):
                _remember_path(root, filename, candidate)
                return candidate, unreadable
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            unreadable = True
    return None, unreadable


def _measure_presence(
    claude_session_uuid: Optional[str],
    *,
    working_dir: Optional[str] = None,
    corpus_root: Optional[Path] = None,
) -> ConversationPresence:
    from src.core.claude_transcript_correlate import (
        default_projects_dir,
        slugify_project_dir,
    )

    if not claude_session_uuid or not _UUID_RE.match(str(claude_session_uuid)):
        return ConversationPresence(
            CONVERSATION_UNCHECKED,
            detail=(
                "no canonical claude session id to look for, so the "
                "transcript corpus was not searched"
            ),
        )

    root = Path(corpus_root) if corpus_root is not None else default_projects_dir()
    filename = f"{claude_session_uuid}.jsonl"

    if working_dir:
        fast = root / slugify_project_dir(str(working_dir)) / filename
        try:
            if fast.is_file():
                return ConversationPresence(CONVERSATION_PRESENT, path=fast)
        except OSError as exc:
            logger.debug(
                "conversation_presence_fast_path_unreadable",
                path=str(fast),
                error=str(exc),
            )

    remembered = _remembered_path(root, filename)
    if remembered is not None:
        return ConversationPresence(CONVERSATION_PRESENT, path=remembered)

    for _attempt in (0, 1):
        try:
            children, from_cache = _root_children(root)
        except OSError as exc:
            return ConversationPresence(
                CONVERSATION_UNCHECKED,
                detail=(
                    f"the transcript corpus at {root} could not be read "
                    f"({exc.strerror or exc}), so whether this conversation "
                    "still exists could not be determined"
                ),
            )
        found, unreadable = _scan_children(children, filename, root)
        if found is not None:
            return ConversationPresence(CONVERSATION_PRESENT, path=found)
        if not (unreadable and from_cache):
            break
        _forget_root_listing(root)

    return ConversationPresence(
        CONVERSATION_ABSENT,
        detail=(
            f"no transcript for claude session {claude_session_uuid} "
            f"exists under {root}, so it cannot be resumed"
        ),
    )


def codex_rollout_presence(
    thread_uuid: Optional[str], *, codex_home: Optional[str] = None
) -> ConversationPresence:
    from src.core.attention import codex_gather

    if not thread_uuid or not _UUID_RE.match(str(thread_uuid)):
        return ConversationPresence(
            CONVERSATION_UNCHECKED,
            detail=(
                "no canonical codex thread id to look for, so the rollout "
                "store was not searched"
            ),
        )
    home = codex_home or codex_gather.DEFAULT_CODEX_HOME
    sessions = Path(home) / "sessions"
    try:
        if not stat.S_ISDIR(os.stat(sessions).st_mode):
            raise NotADirectoryError(errno.ENOTDIR, "not a directory")
        if not os.access(sessions, os.R_OK | os.X_OK):
            raise PermissionError(errno.EACCES, "permission denied")
    except OSError as exc:
        return ConversationPresence(
            CONVERSATION_UNCHECKED,
            detail=(
                f"the codex rollout store at {sessions} could not be read "
                f"({exc.strerror or exc}), so whether this conversation "
                "still exists could not be determined"
            ),
        )
    found = codex_gather.rollout_path_in_sessions(home, str(thread_uuid))
    if found is not None:
        return ConversationPresence(CONVERSATION_PRESENT, path=Path(found))
    return ConversationPresence(
        CONVERSATION_ABSENT,
        detail=(
            f"no rollout for codex conversation {thread_uuid} exists under "
            f"{sessions}, so it cannot be resumed"
        ),
    )


def family_conversation_presence(
    family: Optional[str],
    conversation_uuid: Optional[str],
    *,
    working_dir: Optional[str] = None,
    corpus_root: Optional[Path] = None,
    codex_home: Optional[str] = None,
) -> ConversationPresence:
    from src.core.attention.evidence import FAMILY_CODEX

    if family == FAMILY_CODEX:
        return codex_rollout_presence(conversation_uuid, codex_home=codex_home)
    return conversation_presence(
        conversation_uuid, working_dir=working_dir, corpus_root=corpus_root
    )
