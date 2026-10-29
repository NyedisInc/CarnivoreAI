
from __future__ import annotations

import sqlite3

from src.config import settings
from src.core.db import connect, db_path_for


def open_main() -> sqlite3.Connection:
    return connect(db_path_for(settings.get_state_dir()), create=False)
