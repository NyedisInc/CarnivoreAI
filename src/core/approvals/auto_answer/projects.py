
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Iterable

import structlog

logger = structlog.get_logger()


def _too_broad(root: str) -> bool:
    return root == os.sep or root == os.path.realpath(os.path.expanduser("~"))


def inside(folder: str, roots: Iterable[str]) -> bool:
    target = os.path.realpath(folder)
    for stored in roots:
        root = os.path.realpath(str(stored))
        if _too_broad(root):
            continue
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return False


def in_projects_db(folder: str) -> bool:
    from src.config import settings
    from src.core import db

    try:
        with closing(db.connect(db.db_path_for(settings.get_state_dir()), create=False)) as conn:
            roots = [r[0] for r in conn.execute("SELECT root FROM projects WHERE archived_at IS NULL")]
    except (sqlite3.Error, db.DatastoreUnreadableError, OSError) as exc:
        logger.info("auto_answer_projects_unreadable", error_type=type(exc).__name__)
        return False
    return inside(folder, roots)
