
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SCAN_BUDGET_SECONDS: float = 3.0
SCAN_ENTRY_LIMIT: int = 200_000


@dataclass(frozen=True)
class TreeFacts:

    newest_at: Optional[float]
    conversations: int
    size_bytes: int
    truncated: bool = False


def scan_vault(root: Path, *, clock: Callable[[], float] = time.monotonic, budget: float = SCAN_BUDGET_SECONDS,
               limit: int = SCAN_ENTRY_LIMIT) -> TreeFacts:
    deadline = clock() + budget
    newest: Optional[float] = None
    conversations = seen = 0
    try:
        units = [u for u in os.scandir(Path(root) / "manifests") if u.is_dir(follow_symlinks=False) and not u.name.startswith(".")]
    except OSError:
        return TreeFacts(None, 0, 0)
    for unit in units:
        try:
            files = [f for f in os.scandir(unit.path) if f.name.endswith(".json")]
        except OSError:
            continue
        for entry in files:
            seen += 1
            if seen > limit or clock() > deadline:
                return TreeFacts(newest, conversations, _size(root), True)
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            newest = mtime if newest is None else max(newest, mtime)
        conversations += bool(files)
    return TreeFacts(newest, conversations, _size(root))


def _size(root: Path) -> int:
    try:
        return int(json.loads((Path(root) / "vault-state.json").read_text(encoding="utf-8")).get("blob_bytes") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0
