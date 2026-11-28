
from __future__ import annotations

import os
from pathlib import Path
from typing import FrozenSet, Optional, Set

import structlog

from src.core.claude_config.transcript_roots import claude_transcript_roots

logger = structlog.get_logger()

_SUFFIX = ".jsonl"


def _uuids_under(base: Path) -> Set[str]:
    found: Set[str] = set()
    try:
        slugs = list(os.scandir(base))
    except FileNotFoundError:
        return found
    except OSError as exc:
        logger.warning("project_history_transcript_root_unreadable", root=str(base), error=str(exc))
        return found
    for slug in slugs:
        if not slug.is_dir(follow_symlinks=True):
            continue
        try:
            with os.scandir(slug.path) as entries:
                for entry in entries:
                    if entry.name.endswith(_SUFFIX):
                        found.add(entry.name[: -len(_SUFFIX)])
        except OSError as exc:
            logger.warning("project_history_transcript_slug_unreadable", slug=slug.path, error=str(exc))
    return found


def transcript_uuid_index(root: Optional[Path] = None) -> FrozenSet[str]:
    roots = (root,) if root is not None else claude_transcript_roots()
    found: Set[str] = set()
    for base in roots:
        found |= _uuids_under(base)
    return frozenset(found)


class OnDiskProbe:

    def __init__(self, roots: Optional[tuple] = None) -> None:
        self._roots = roots
        self._seen: dict = {}

    def __contains__(self, conversation: object) -> bool:
        if not isinstance(conversation, str) or not conversation or "/" in conversation:
            return False
        if conversation not in self._seen:
            roots = self._roots if self._roots is not None else tuple(claude_transcript_roots())
            try:
                self._seen[conversation] = any(True for base in roots for _ in base.glob(f"*/{conversation}{_SUFFIX}"))
            except OSError as exc:
                logger.warning("project_history_transcript_probe_unreadable", error=str(exc))
                self._seen[conversation] = False
        return self._seen[conversation]
