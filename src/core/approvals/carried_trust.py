
from __future__ import annotations

from contextlib import closing
from typing import Optional

import structlog

logger = structlog.get_logger()

YES_LABEL: str = "Yes, I trust this folder"

IMPORTS_YES_LABEL: str = "Yes, allow external imports"


def carried_op_for(folder: str) -> Optional[str]:
    import sqlite3

    from src.config import settings
    from src.core import db
    from src.core.pack.trust_carry import store

    try:
        with closing(db.connect(db.db_path_for(settings.get_state_dir()), create=False)) as conn:
            return store.carried_op(conn, folder)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("pack_trust_carried_unreadable", error_type=type(exc).__name__)
        return None


def carried_imports_for(folder: str) -> bool:
    import sqlite3

    from src.config import settings
    from src.core import db
    from src.core.pack.trust_carry import store

    try:
        with closing(db.connect(db.db_path_for(settings.get_state_dir()), create=False)) as conn:
            return store.carried_imports_ok(conn, folder)
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("pack_imports_carried_unreadable", error_type=type(exc).__name__)
        return False
