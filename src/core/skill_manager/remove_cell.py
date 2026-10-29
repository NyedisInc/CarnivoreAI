
from __future__ import annotations

import os
from typing import Any, Dict

from src.core.skill_manager.remove import remove_location
from src.core.skill_manager.types import OverrideError


def remove_cell(matrix: Dict[str, Any], *, location_id: str, column_id: str, generation: str, stamp: str) -> Dict[str, Any]:
    if not generation:
        raise OverrideError(400, "stale_check_required", "generation is required to remove")
    col = next((c for c in matrix["columns"] if c["column_id"] == column_id), None)
    hit = next(((r, c) for r in matrix["rows"] for c in r["cells"].get(column_id, []) if c["location_id"] == location_id), None)
    if col is None or hit is None:
        raise OverrideError(404, "unknown_cell", "unknown or stale skill location")
    row, cell = hit
    if generation != matrix["generation"]:
        raise OverrideError(409, "stale", "the skills changed since you looked; reload and review again")
    if not col["writable"]:
        raise OverrideError(409, "read_only", "that column is read only")
    leaf = os.path.abspath(col["leaf"])
    root = {
        "path": col["path"], "scope": col["scope"], "read_only": False,
        "is_symlink": os.path.realpath(leaf) != leaf,
    }
    location = {"folder": cell["folder"], "managed": {"source": "ledger"} if cell["managed"] == "ledger" else None}
    trashed_to = remove_location(location, root, stamp)
    return {"name": row["name"], "folder": cell["folder"], "label": col["label"], "harness": col["harness"], "location_id": location_id, "trashed_to": trashed_to}
