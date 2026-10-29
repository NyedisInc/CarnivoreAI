
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.message_block_ddl import DDL_V18
from src.core.message_host_ddl import DDL_V17
from src.core.message_model_ddl import DDL_V16

from src.core.db import connect as db_connect  # noqa: E402



def make_state_dir(tmp_path: Path, name: str = "state") -> Path:
    state_dir = tmp_path / name
    state_dir.mkdir(parents=True, exist_ok=True)
    conn = db_connect(state_dir / "carnivore.db")
    try:
        with conn:
            run_chain(conn, 0, 15)
            for ddl in (DDL_V16, DDL_V17, DDL_V18):
                for statement in ddl:
                    conn.execute(statement)
            run_chain(conn, 15, CURRENT_SCHEMA_VERSION)
    finally:
        conn.close()
    return state_dir


def writable(state_dir: Path) -> sqlite3.Connection:
    conn = db_connect(Path(state_dir) / "carnivore.db")
    conn.row_factory = sqlite3.Row
    return conn
