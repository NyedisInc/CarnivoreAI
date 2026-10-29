
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from src.core.db import table_exists
from src.core.project_move.paths import prefix_params, prefix_where, rebase

ITEMS, TARGETS = "installed_items", "installed_item_targets"


def _present(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, ITEMS) and table_exists(conn, TARGETS)


def plan_install_rows(conn: sqlite3.Connection, plan: Any, rebasable: bool) -> None:
    if not _present(conn):
        return
    params = prefix_params(plan.old_root)
    items = conn.execute(f"SELECT item_id, name, scope, project_path FROM {ITEMS} "
                         f"WHERE {prefix_where('project_path')}", params).fetchall()
    files = conn.execute(f"SELECT COUNT(*) FROM {TARGETS} WHERE {prefix_where('path')}", params).fetchone()[0]
    plan.skill_installs = {"items": len(items), "files": int(files)}
    if not items or not rebasable:
        return
    clashes: List[str] = []
    for row in items:
        target = rebase(row["project_path"], plan.old_root, plan.new_root)
        taken = conn.execute(
            f"SELECT name FROM {ITEMS} WHERE scope = ? AND project_path = ? AND (item_id = ? OR name = ?)",
            (row["scope"], target, row["item_id"], row["name"])).fetchone()
        if taken:
            clashes.append(f"{row['name']} is already installed at {target}")
    plan.check("skill_installs_free", not clashes, "every project-scope install can follow the folder"
               if not clashes else "; ".join(clashes) + "; uninstall one first")


def rewrite_install_rows(conn: sqlite3.Connection, old_root: str, new_root: str) -> Dict[str, int]:
    if not _present(conn):
        return {"skill_install_items": 0, "skill_install_files": 0}
    params = {**prefix_params(old_root), "new": new_root, "old_len": len(prefix_params(old_root)["old"])}
    items = conn.execute(f"UPDATE {ITEMS} SET project_path = :new || substr(project_path, :old_len + 1) "
                         f"WHERE {prefix_where('project_path')}", params).rowcount
    files = conn.execute(f"UPDATE {TARGETS} SET path = :new || substr(path, :old_len + 1) "
                         f"WHERE {prefix_where('path')}", params).rowcount
    return {"skill_install_items": items, "skill_install_files": files}
