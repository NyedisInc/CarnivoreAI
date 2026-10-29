
from __future__ import annotations

import sqlite3

from src.config import settings
from src.core.db import connect, db_path_for


def open_main() -> sqlite3.Connection:
    """Open cloude.db read/write with rows as ``sqlite3.Row``; a missing file raises instead of becoming an empty database.

    Output: sqlite3.Connection. Raises: DatastoreUnreadableError or sqlite3.Error when the store cannot be opened.
    """
    return connect(db_path_for(settings.get_state_dir()), create=False)
