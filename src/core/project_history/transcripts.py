
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
