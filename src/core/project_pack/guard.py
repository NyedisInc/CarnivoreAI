
from __future__ import annotations

import sqlite3
from typing import Optional

from src.core.db import table_exists
from src.core.project_move.paths import is_within
from src.core.project_pack import constants as K

PACKED_MESSAGE = "this project is packed; unpack it first"


def packed_project_name(conn: sqlite3.Connection, working_dir: str) -> Optional[str]:
    if not table_exists(conn, "project_storage"):
        return None
    marks = ",".join("?" * (len(K.BUSY_STATES) + 1))
    rows = conn.execute(
        f"SELECT p.display_name, p.root FROM project_storage s JOIN projects p ON p.id = s.project_id "
        f"WHERE s.state IN ({marks})", (K.STATE_PACKED, *K.BUSY_STATES)).fetchall()
    for row in rows:
        if is_within(working_dir, row["root"]):
            return row["display_name"]
    return None
