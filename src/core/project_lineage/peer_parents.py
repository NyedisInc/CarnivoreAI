
from __future__ import annotations

import json
import sqlite3
from typing import Dict, Mapping, Optional

from src.core.db import get_meta, set_meta
from src.core.hosts.remote_project import UID_RE

META_PEER_PROJECT_PARENTS = "peer_project_parents"

MAX_PEER_PROJECT_PARENTS = 2000


def _valid_uid(value: object) -> Optional[str]:
    return value if isinstance(value, str) and UID_RE.fullmatch(value) else None


def read_peer_project_parents(conn: sqlite3.Connection) -> Dict[str, str]:
    raw = get_meta(conn, META_PEER_PROJECT_PARENTS)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, str] = {}
    for child, parent in parsed.items():
        c_uid, p_uid = _valid_uid(child), _valid_uid(parent)
        if c_uid is not None and p_uid is not None and c_uid != p_uid:
            out[c_uid] = p_uid
            if len(out) >= MAX_PEER_PROJECT_PARENTS:
                break
    return out


def merge_peer_project_parents(
    current: Mapping[str, str], updates: Mapping[str, Optional[str]]
) -> Dict[str, str]:
    merged = dict(current)
    for child, parent in updates.items():
        c_uid = _valid_uid(child)
        if c_uid is None:
            continue
        p_uid = _valid_uid(parent)
        if p_uid is not None and p_uid != c_uid:
            if c_uid not in merged and len(merged) >= MAX_PEER_PROJECT_PARENTS:
                continue
            merged[c_uid] = p_uid
        else:
            merged.pop(c_uid, None)
    return merged


def sync_peer_project_parents(conn: sqlite3.Connection, updates: Mapping[str, Optional[str]]) -> bool:
    if not updates:
        return False
    current = read_peer_project_parents(conn)
    merged = merge_peer_project_parents(current, updates)
    if merged == current:
        return False
    set_meta(conn, META_PEER_PROJECT_PARENTS, json.dumps(merged, sort_keys=True, separators=(",", ":")))
    return True
