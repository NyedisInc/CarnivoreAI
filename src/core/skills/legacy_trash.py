
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from src.core.live_install_roots import TRASH_DIR_NAME


def trash_root_for(
    roots: Any,
    *,
    kind: str,
    harness: str,
    scope: str,
    project_path: Optional[str],
    live_path: Path,
) -> Path:
    parent = os.path.realpath(Path(live_path).parent)
    for legacy in roots.legacy_targets_for(kind, scope, project_path):
        if os.path.realpath(legacy.leaf_dir) == parent:
            return legacy.leaf_dir.parent / TRASH_DIR_NAME
    return roots.trash_dir(harness, scope, project_path)
