
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from src.core.session_status import ACTIVITY_STATUS_PRIORITY

Row = Mapping[str, Any]


def row_key(row: Row) -> Optional[str]:
    session = row.get("session")
    key = session.get("id") if isinstance(session, Mapping) else None
    return key if isinstance(key, str) else None


def row_name(row: Row) -> str:
    session = row.get("session")
    nested = session.get("name") if isinstance(session, Mapping) else None
    return str(row.get("label") or row.get("tmux_session") or nested or row_key(row) or "")


def is_remote(row: Row) -> bool:
    key = row.get("host_key")
    return bool(key) and key != "local"


def visible(rows: Iterable[Row]) -> list[Row]:
    return [r for r in rows if r.get("activity_status") != "asleep"]


def arrange(rows: list[Row], arrangement: Optional[Mapping[str, Any]]) -> list[Row]:
    if not isinstance(arrangement, Mapping):
        return list(rows)
    rank: dict[str, int] = {}
    for field in ("pinned", "order"):
        for uuid in arrangement.get(field) or []:
            if isinstance(uuid, str) and uuid not in rank:
                rank[uuid] = len(rank)
    far = len(rank)
    return sorted(rows, key=lambda r: rank.get(r.get("session_uuid") or "", far))


def sort_by_status(rows: list[Row]) -> list[Row]:
    last = len(ACTIVITY_STATUS_PRIORITY)

    def rank(row: Row) -> int:
        status = row.get("activity_status")
        return ACTIVITY_STATUS_PRIORITY.index(status) if status in ACTIVITY_STATUS_PRIORITY else last

    return sorted(rows, key=rank)


def matches(row: Row, needle: str, status_label: str) -> bool:
    needle = needle.strip().lower()
    if not needle:
        return True
    hay = (row_name(row), row.get("project_name"), row.get("agent_family"), row.get("host_label"), status_label)
    return any(needle in str(h).lower() for h in hay if h)
