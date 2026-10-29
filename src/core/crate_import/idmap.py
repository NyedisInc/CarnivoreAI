
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from src.core.crate_import.keyrules import KeyRule
from src.core.inventory.model import MAIN_STORE


COMPANIES = f"{MAIN_STORE}.companies"
PROJECTS = f"{MAIN_STORE}.projects"
SESSIONS = f"{MAIN_STORE}.sessions"
SESSION_UUIDS = f"{SESSIONS}.session_uuid"
WORK_ITEMS = f"{MAIN_STORE}.work_items"


class IdMap:

    def __init__(self, prior: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.maps: Dict[str, Dict[str, Any]] = {t: dict(m) for t, m in (prior or {}).items()}

    def put(self, table_key: str, old: Any, new: Any) -> None:
        self.maps.setdefault(table_key, {})[str(old)] = new

    def get(self, table_key: str, old: Any) -> Optional[Any]:
        return self.maps.get(table_key, {}).get(str(old))

    def as_json(self) -> Dict[str, Dict[str, Any]]:
        return {t: dict(m) for t, m in self.maps.items()}


def ref(conn: sqlite3.Connection, idmap: IdMap, rule: KeyRule, value: Any) -> Optional[Any]:
    table, _, column = (rule.target or "").partition(".")
    if column == "id":
        return idmap.get(f"{MAIN_STORE}.{table}", value)
    found = conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)).fetchone()
    return value if found is not None else None
