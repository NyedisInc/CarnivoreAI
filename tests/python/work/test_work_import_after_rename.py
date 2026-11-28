
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core.work import folders, storage as work_storage
from src.core.work.importer import ready
from tests.python.work.test_work_import import _legacy, state  # noqa: F401


def test_the_import_still_finds_huddle_db_after_the_id_flip(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    legacy = _legacy(state)
    assert legacy.parent == state / "cplugs" / folders.OLD_ID
    monkeypatch.setattr(work_storage, "FOLDER_NAME", folders.NEW_ID)
    storage = work_storage.storage_for(state)
    assert storage.path == state / "cplugs" / folders.NEW_ID
    storage.ensure_ready()
    with closing(ready.open_db(storage.db_path)) as conn:
        assert conn.execute("SELECT kind FROM work_imports").fetchone()[0] == "import"
    assert (legacy.parent / ready.MARKER).exists() and not (storage.path / ready.MARKER).exists()
