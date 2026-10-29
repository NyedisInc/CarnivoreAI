
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Optional, Tuple

from src.core.db_models import (
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)

_PARENT_SEGMENT = ".."


def normalize_path_for_match(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        expanded = Path(text).expanduser()
    except (RuntimeError, TypeError, ValueError):
        return None
    if not expanded.is_absolute():
        return None
    if _PARENT_SEGMENT in expanded.parts:
        return None
    return str(expanded)


def _ancestor_chain(normalized: str) -> Tuple[str, ...]:
    pure = PurePosixPath(normalized)
    return (str(pure), *(str(parent) for parent in pure.parents))


def _depth(normalized: str) -> int:
    return len(PurePosixPath(normalized).parts)


def normalize_roots(roots: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for root, project_id in roots.items():
        normalized = normalize_path_for_match(root)
        if normalized is None:
            continue
        existing = out.get(normalized)
        if existing is None or int(project_id) < existing:
            out[normalized] = int(project_id)
    return out


def attribute(
    working_dir: Optional[str], roots: Dict[str, int]
) -> Tuple[Optional[int], str]:
    normalized = normalize_path_for_match(working_dir)
    if normalized is None:
        return None, SESSION_ATTRIBUTION_UNKNOWN

    candidates = _ancestor_chain(normalized)
    comparable = normalize_roots(roots)

    best_id: Optional[int] = None
    best_depth = -1
    for root, project_id in comparable.items():
        if root not in candidates:
            continue
        depth = _depth(root)
        if depth > best_depth:
            best_id, best_depth = project_id, depth

    if best_id is None:
        return None, SESSION_ATTRIBUTION_NONE
    return best_id, SESSION_ATTRIBUTION_DERIVED_DEEPEST


def attribution_is_determined(attribution: Optional[str]) -> bool:
    if attribution is None:
        return False
    return attribution != SESSION_ATTRIBUTION_UNKNOWN


def unresolved_roots(roots: Iterable[str]) -> Tuple[str, ...]:
    return tuple(
        root for root in roots if normalize_path_for_match(root) is None
    )
