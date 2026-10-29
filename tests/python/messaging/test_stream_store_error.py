
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from src.core.messaging import stream


def test_a_store_error_backs_off_and_the_loop_keeps_running(world, monkeypatch):
    state = world.rt.providers[world.pid]
    calls = []

    async def ws(rt, st):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        raise asyncio.CancelledError

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(stream, "_ws_session", ws)
    monkeypatch.setattr(stream, "_rest_session", ws)
    monkeypatch.setattr(stream.asyncio, "sleep", no_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(stream.run_stream(world.rt, state))
    assert len(calls) == 2
