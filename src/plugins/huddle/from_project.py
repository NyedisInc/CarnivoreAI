
from __future__ import annotations

from typing import Mapping, Optional


ID_FIELD = "from_project_id"
NAME_FIELD = "from_project_name"
FIELD = "from_project"
SELECT_COLS = f"{ID_FIELD}, {NAME_FIELD}"


def wire(row: Mapping) -> dict:
    source = row[ID_FIELD]
    if source is None:
        return {FIELD: None}
    return {FIELD: {"id": str(source), "name": row[NAME_FIELD] or str(source)}}


def is_unset(row: Mapping) -> bool:
    return row[ID_FIELD] is None


def stamp_sql() -> str:
    return f"UPDATE work_items SET {ID_FIELD} = ?, {NAME_FIELD} = ? WHERE id = ? AND {ID_FIELD} IS NULL"


def label(source: Optional[Mapping]) -> str:
    return str(source.get("name") or source.get("id") or "") if source else ""
