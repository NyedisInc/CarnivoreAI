
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.attention.transcript_facts import TranscriptFacts

logger = structlog.get_logger(__name__)

MAX_ENTRIES: int = 256

_Key = Tuple[str, Optional[int]]


def _roots() -> Tuple[Path, ...]:
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    return claude_transcript_roots()


def _expected_paths(uuid: str, working_dir: Optional[str],
                    roots: Tuple[Path, ...]) -> Tuple[Path, ...]:
    from src.core.claude_project_dirs import candidate_project_dirs

    out = []
    for root in roots:
        for directory in candidate_project_dirs(working_dir, projects_dir=root):
            out.append(directory / f"{uuid}.jsonl")
    return tuple(out)


class AbsentTranscriptCache:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[_Key, tuple]" = OrderedDict()

    @staticmethod
    def _signature(registry: Any, working_dir: Optional[str],
                   roots: Tuple[Path, ...]) -> Optional[tuple]:
        if not getattr(registry, "known", False):
            return None
        return (registry.status, registry.status_updated_at, working_dir, roots)

    def recall(self, uuid: Optional[str], epoch: Optional[int], registry: Any,
               working_dir: Optional[str]) -> Optional[TranscriptFacts]:
        if not uuid:
            return None
        key: _Key = (str(uuid), epoch)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        roots = _roots()
        if entry[0] != self._signature(registry, working_dir, roots):
            self._forget(key)
            return None
        try:
            if any(path.is_file() for path in _expected_paths(str(uuid), working_dir, roots)):
                self._forget(key)
                return None
        except OSError as exc:
            logger.debug("absent_transcript_recheck_unreadable", error=str(exc))
            self._forget(key)
            return None
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
        return entry[1]

    def remember(self, uuid: Optional[str], epoch: Optional[int], registry: Any,
                 working_dir: Optional[str], facts: TranscriptFacts) -> None:
        if not uuid:
            return
        key: _Key = (str(uuid), epoch)
        signature = self._signature(registry, working_dir, _roots())
        if not facts.absent or signature is None:
            self._forget(key)
            return
        with self._lock:
            self._entries[key] = (signature, facts)
            self._entries.move_to_end(key)
            while len(self._entries) > MAX_ENTRIES:
                self._entries.popitem(last=False)

    def _forget(self, key: _Key) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


ABSENT_TRANSCRIPTS = AbsentTranscriptCache()
