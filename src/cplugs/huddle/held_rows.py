
from __future__ import annotations

import json
from contextlib import closing
from typing import TYPE_CHECKING, Any, Dict, List

from src.cplugs.sdk.work import tables

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

TABLE = tables.HELD_SENDS


def save(store: "TaskManagerStore", row: Dict[str, Any]) -> None:
    with closing(store._connect(True)) as conn, conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE} (list_key, target, label, code, reason, since, deadline, params) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["list"], row["target"], row["label"], row["code"], row["reason"], row["since"], row["deadline"], json.dumps(row["params"])),
        )


def remove(store: "TaskManagerStore", list_key: str) -> None:
    with closing(store._connect(True)) as conn, conn:
        conn.execute(f"DELETE FROM {TABLE} WHERE list_key = ?", (list_key,))


def load(store: "TaskManagerStore") -> List[Dict[str, Any]]:
    with closing(store._read_connection()) as conn:
        cursor = conn.execute(f"SELECT list_key, target, label, code, reason, since, deadline, params FROM {TABLE} ORDER BY since")
        out = []
        for key, target, label, code, reason, since, deadline, params in cursor:
            try:
                decoded = json.loads(params)
            except ValueError:
                decoded = {}
            out.append({"list": key, "target": target, "label": label, "code": code, "reason": reason,
                        "since": since, "deadline": deadline, "params": decoded if isinstance(decoded, dict) else {}})
        return out


__all__ = ["TABLE", "load", "remove", "save"]
