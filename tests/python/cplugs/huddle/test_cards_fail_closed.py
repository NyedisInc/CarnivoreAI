
from __future__ import annotations

import asyncio
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from src.core.swarm.cards import port as card_port
from src.core.work.ladder import MIGRATIONS
from src.core.work.storage import LEGACY_STORAGE
from src.cplugs.host import runtime
from src.cplugs.sdk import CplugSchemaError, CplugStorage, StorageSpec, storage_backup
from tests.python.cplugs.huddle.test_cards_conversion import build_v22
from tests.python.cplugs.owner import turn_on


def version_of(path: Path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_a_failed_backup_stops_the_plugin_and_the_boot_goes_on(tmp_path: Path, monkeypatch):
    build_v22(tmp_path / "v22.db")
    folder = tmp_path / "cplugs" / "huddle"
    folder.mkdir(parents=True)
    shutil.copy2(tmp_path / "v22.db", folder / "huddle.db")
    (folder / "files").mkdir()

    def refuse(copy: Path, **kwargs: Any) -> None:
        raise storage_backup.BackupFailed("forced")

    monkeypatch.setattr(storage_backup, "verify", refuse)
    host = runtime.Host(tmp_path, FastAPI(), publish=lambda topic: None)
    turn_on(host)
    asyncio.run(host.start())
    assert "huddle" in host.unavailable
    with pytest.raises(card_port.CardsOff):
        card_port.get()
    assert version_of(folder / "huddle.db") == 22
    assert not [p for p in folder.iterdir() if "pre-cards" in p.name]


def test_a_walk_that_fails_after_its_backup_takes_one_copy_however_many_connects(tmp_path: Path):
    build_v22(tmp_path / "v22.db")
    folder = tmp_path / "huddle"
    folder.mkdir()
    shutil.copy2(tmp_path / "v22.db", folder / "huddle.db")
    broken = StorageSpec(db="huddle.db", migrations=[*MIGRATIONS[:22], "THIS IS NOT SQL;"], backup_before=LEGACY_STORAGE.backup_before)
    storage = CplugStorage(folder, broken)
    for _ in range(3):
        with pytest.raises(CplugSchemaError, match="after its backup"):
            storage.connect(True)
    assert len([p for p in folder.iterdir() if ".pre-cards-" in p.name]) == 1
    assert version_of(folder / "huddle.db") == 22
