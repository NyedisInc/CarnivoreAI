from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from src.core.refresh_store import RefreshStore, RefreshStoreNotReady


def _run(coro):
    return asyncio.run(coro)


def test_failed_insert_leaves_old_token_unsuperseded(tmp_path: Path) -> None:

    async def scenario() -> tuple[bool, bool]:
        store = RefreshStore(str(tmp_path / "r.db"))
        await store.init()
        exp = int(time.time()) + 3600
        await store.issue("old-jti-aaaaaaaa", "u", exp)
        await store.issue("dup-jti-bbbbbbbb", "u", exp)
        with pytest.raises(sqlite3.IntegrityError):
            await store.rotate("old-jti-aaaaaaaa", "dup-jti-bbbbbbbb", "u", exp)
        await store.issue("other-jti-cccccc", "u", exp)
        superseded = await store.is_superseded("old-jti-aaaaaaaa")
        valid = await store.is_valid("old-jti-aaaaaaaa")
        await store.close()
        return superseded, valid

    superseded, valid = _run(scenario())
    assert superseded is False
    assert valid is True


def test_methods_before_init_raise_typed_error(tmp_path: Path) -> None:
    store = RefreshStore(str(tmp_path / "r.db"))
    with pytest.raises(RefreshStoreNotReady):
        _run(store.issue("j", "u", 1))
    with pytest.raises(RefreshStoreNotReady):
        _run(store.rotate("a", "b", "u", 1))
