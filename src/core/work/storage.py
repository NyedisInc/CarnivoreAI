
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from src.core.db import db_path_for
from src.core.test_write_guard import assert_test_write_allowed
from src.core.work.importer import copy, ready
from src.core.work.work_ladder import MIGRATIONS, VERSION
from src.cplugs.sdk.storage import CoreStorageSpec, CplugStorage

DB_NAME = ready.LEGACY_DB
FOLDER_NAME = "huddle"
PLUGINS_FOLDER = "cplugs"
BUSY_SECONDS = 30.0


class WorkStorage(CplugStorage):

    def __init__(self, folder: Path, state_dir: Optional[Path] = None) -> None:
        super().__init__(folder, None, state_dir)
        self._home = Path(state_dir) if state_dir is not None else Path(folder)

    @property
    def db_path(self) -> Path:
        return db_path_for(self._home)

    @property
    def schema_version(self) -> int:
        return VERSION

    def ensure_ready(self) -> None:
        ready.ensure(self.db_path, self.path, self._state_dir)

    def _legacy_waiting(self) -> bool:
        places = [self.path / DB_NAME] + ([self._state_dir / DB_NAME] if self._state_dir is not None else [])
        return any(place.exists() for place in places)

    def _open(self, write: bool) -> sqlite3.Connection:
        path = self.db_path
        if not write and not path.exists() and not self._legacy_waiting():
            conn = sqlite3.connect(":memory:")
            copy.create_empty(conn)
            for rung in MIGRATIONS[1:]:
                copy.run_script(conn, rung)
            conn.commit()
        else:
            self.ensure_ready()
            assert_test_write_allowed(path)
            conn = sqlite3.connect(str(path), timeout=BUSY_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def folder(state_dir: Path) -> Path:
    return Path(state_dir) / PLUGINS_FOLDER / FOLDER_NAME


def storage_for(state_dir: Path) -> WorkStorage:
    return WorkStorage(folder(state_dir), Path(state_dir))


LEGACY_STORAGE = ready.legacy_spec()

STORAGE = CoreStorageSpec(bind=WorkStorage)
