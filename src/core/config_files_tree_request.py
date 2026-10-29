from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.config_files_constants import TREE_MAX_DEPTH

FULL_TREE_LEVELS = TREE_MAX_DEPTH + 1


@dataclass(frozen=True)
class TreeRequest:
    rel_path: str
    levels: int
    shallow: bool


def plan_tree_request(path: Optional[str], depth: Optional[int]) -> TreeRequest:
    if depth is not None:
        if depth < 1:
            raise ValueError("depth must be at least 1")
        if depth > FULL_TREE_LEVELS:
            raise ValueError(f"depth must be at most {FULL_TREE_LEVELS}")

    return TreeRequest(
        rel_path=(path or ""),
        levels=(FULL_TREE_LEVELS if depth is None else depth),
        shallow=depth is not None,
    )
