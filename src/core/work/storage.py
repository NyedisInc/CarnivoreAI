
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from src.core.db import db_path_for
from src.core.test_write_guard import assert_test_write_allowed
from src.core.work import folders
from src.core.work.importer import copy, ready
from src.core.work.work_ladder import MIGRATIONS, VERSION
from src.plugins.sdk.storage import CoreStorageSpec, CplugStorage

DB_NAME = ready.LEGACY_DB
FOLDER_NAME = folders.CURRENT_ID
PLUGINS_FOLDER = folders.PLUGINS_FOLDER
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

    @property
    def legacy_folder(self) -> Path:
        return legacy_folder(self._state_dir) if self._state_dir is not None else self.path

    def ensure_ready(self) -> None:
        ready.ensure(self.db_path, self.legacy_folder, self._state_dir)

    def _legacy_waiting(self) -> bool:
        places = [self.legacy_folder / DB_NAME] + ([self._state_dir / DB_NAME] if self._state_dir is not None else [])
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
            for pragma in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA busy_timeout=30000",
                "PRAGMA cache_size=-16000",
                "PRAGMA temp_store=MEMORY",
                "PRAGMA mmap_size=67108864",
                "PRAGMA journal_size_limit=67108864",
            ):
                conn.execute(pragma)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def folder(state_dir: Path) -> Path:
    return Path(state_dir) / PLUGINS_FOLDER / FOLDER_NAME


def legacy_folder(state_dir: Path) -> Path:
    return Path(state_dir) / PLUGINS_FOLDER / folders.OLD_ID


def storage_for(state_dir: Path) -> WorkStorage:
    storage = WorkStorage(folder(state_dir), Path(state_dir))
    if FOLDER_NAME != folders.OLD_ID:
        storage.previous_path = legacy_folder(state_dir)
    return storage


LEGACY_STORAGE = ready.legacy_spec()

STORAGE = CoreStorageSpec(bind=WorkStorage)
