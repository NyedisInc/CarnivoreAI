
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.core.subagents.reader import subagents_dir_for
from src.core.timeline.model import FILE_KEY_MAIN, THREAD_AGENT_PREFIX, THREAD_RE


class UnknownThreadError(ValueError):
    pass


SUBAGENT_PREFIX = "agent-"
SUFFIX = ".jsonl"
LISTING_CACHE_FOLDERS = 256

_LISTING_CACHE: "OrderedDict[str, Tuple[Tuple[int, int], Dict[str, str]]]" = OrderedDict()
_LISTING_LOCK = threading.Lock()


def _list_folder(real_folder: str) -> Dict[str, str]:
    with os.scandir(real_folder) as scan:
        found = [e for e in scan if e.name.startswith(SUBAGENT_PREFIX) and e.name.endswith(SUFFIX)]
    found.sort(key=lambda e: e.name)
    return {e.name[len(SUBAGENT_PREFIX):-len(SUFFIX)]: (os.path.realpath(e.path) if e.is_symlink() else os.path.join(real_folder, e.name))
            for e in found}


def main_file(conv: str, working_dir: Optional[str]) -> str:
    from src.core.bookmarks import locate  # noqa: PLC0415

    return os.path.realpath(locate.find_transcript(conv, working_dir))


def agent_files(main_real: str) -> Dict[str, str]:
    real_folder = os.path.realpath(subagents_dir_for(Path(main_real)))
    try:
        stat = os.stat(real_folder)
    except OSError:
        return {}
    stamp = (stat.st_mtime_ns, stat.st_ino)
    with _LISTING_LOCK:
        cached = _LISTING_CACHE.get(real_folder)
        if cached is not None and cached[0] == stamp:
            _LISTING_CACHE.move_to_end(real_folder)
            return dict(cached[1])
    try:
        listing = _list_folder(real_folder)
    except OSError:
        return {}
    with _LISTING_LOCK:
        _LISTING_CACHE[real_folder] = (stamp, listing)
        _LISTING_CACHE.move_to_end(real_folder)
        while len(_LISTING_CACHE) > LISTING_CACHE_FOLDERS:
            _LISTING_CACHE.popitem(last=False)
    return dict(listing)


def file_for_thread(main_real: str, thread: Optional[str]) -> Optional[tuple]:
    if thread is None:
        return FILE_KEY_MAIN, main_real
    if not THREAD_RE.match(thread):
        raise UnknownThreadError("a thread is main, side, agent:<id> or wf:<id>")
    if not thread.startswith(THREAD_AGENT_PREFIX):
        return FILE_KEY_MAIN, main_real
    agent_id = thread[len(THREAD_AGENT_PREFIX):]
    found = agent_files(main_real).get(agent_id)
    return (agent_id, found) if found else None


def locate_or_none(conv: str, working_dir: Optional[str]) -> Optional[str]:
    from src.core.bookmarks.errors import TranscriptUnavailable  # noqa: PLC0415

    try:
        return main_file(conv, working_dir)
    except TranscriptUnavailable:
        return None
