
from __future__ import annotations

import posixpath
from typing import Any, Dict, Iterable, Optional, Tuple

LOCAL_HOST = "local"


def _clean_root(root: Any) -> Optional[str]:
    if not isinstance(root, str) or not root.startswith("/"):
        return None
    return posixpath.normpath(root)


def parent_project_ids(projects: Iterable[Dict[str, Any]]) -> Dict[int, Optional[int]]:
    rows = [p for p in projects if isinstance(p.get("id"), int) and not isinstance(p.get("id"), bool)]
    holders: Dict[Tuple[str, str], int] = {}
    for p in rows:
        root = _clean_root(p.get("root"))
        if root is None or p.get("archived_at"):
            continue
        key = (p.get("host_key") or LOCAL_HOST, root)
        holders[key] = min(holders.get(key, p["id"]), p["id"])
    out: Dict[int, Optional[int]] = {}
    for p in rows:
        root = _clean_root(p.get("root"))
        host = p.get("host_key") or LOCAL_HOST
        parent: Optional[int] = None
        current = root
        while current is not None and current != "/":
            current = posixpath.dirname(current)
            found = holders.get((host, current))
            if found is not None and found != p["id"]:
                parent = found
                break
        out[p["id"]] = parent
    return out
