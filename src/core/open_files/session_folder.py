
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from src.core.db import connect
from src.core.hosts.ddl import host_scope
from src.core.sessions import errors as session_errors


class SessionFolderError(LookupError):
    pass


class SessionNotFound(SessionFolderError, session_errors.SessionNotFound):
    pass


def working_dir_in(conn: sqlite3.Connection, session_uuid: str) -> Optional[str]:
    scope_sql, scope_params = host_scope(conn)
    row = conn.execute("SELECT working_dir FROM sessions WHERE session_uuid = ?" + scope_sql,
                       (session_uuid, *scope_params)).fetchone()
    if row is None:
        raise SessionNotFound(session_uuid)
    return row["working_dir"] or None


def working_dir_for(db_path: Path, session_uuid: str) -> Optional[str]:
    with closing(connect(db_path, create=False)) as conn:
        return working_dir_in(conn, session_uuid)
