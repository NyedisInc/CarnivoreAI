
from __future__ import annotations

import sqlite3

from src.core.db import table_exists
from src.core.project_move.paths import prefix_params, prefix_where

AGENTS = "swarm_agents"


def rewrite_agent_dirs(conn: sqlite3.Connection, old_root: str, new_root: str) -> int:
    if not table_exists(conn, AGENTS):
        return 0
    params = {**prefix_params(old_root), "new": new_root, "old_len": len(prefix_params(old_root)["old"])}
    return conn.execute(f"UPDATE {AGENTS} SET repo_dir = :new || substr(repo_dir, :old_len + 1) "
                        f"WHERE {prefix_where('repo_dir')}", params).rowcount
