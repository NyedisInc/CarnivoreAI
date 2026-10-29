
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.swarm import spawn


class Stop(Exception):
    pass


def _run(monkeypatch, chosen):
    seen = {}

    async def run_db(fn):
        return fn(None)

    def caps(conn, agent, **kw):
        seen.update(kw)
        raise Stop

    async def place(plan):
        return SimpleNamespace(chosen=chosen)

    monkeypatch.setattr(spawn.body, "run_db", run_db)
    monkeypatch.setattr(spawn.body, "caps_refusal", caps)
    monkeypatch.setattr(spawn, "_place", place)
    monkeypatch.setattr("src.core.pack.machines.runtime.wiring", lambda: SimpleNamespace(runtime=SimpleNamespace(install_id="me")))
    plan = SimpleNamespace(parent={"id": 1}, target=None, workload=None, request={"rank": "task", "task_type": "browser-test"})
    with pytest.raises(Stop):
        import asyncio

        asyncio.run(spawn._start_child(None, plan, mint_card=False))
    return seen


def test_remote_placement_skips_local_machine_check(monkeypatch):
    assert _run(monkeypatch, "peer")["machine"] is False


def test_local_placement_keeps_machine_check(monkeypatch):
    assert _run(monkeypatch, "me")["machine"] is True


def test_queue_count_opens_its_connection_in_the_calling_thread(tmp_path):
    import asyncio
    import sqlite3
    from src.core.pack.placement import maintain

    db = tmp_path / "q.db"
    sqlite3.connect(db).execute("CREATE TABLE pack_spawn_queue (id INTEGER, state TEXT)").connection.commit()
    assert asyncio.run(asyncio.to_thread(maintain._count_waiting, lambda: sqlite3.connect(db))) == 0


def test_span_paths_are_relative_to_the_peer_client_prefix():
    from src.core.pack.span import proxy_client, refresh_fanout, remote_body

    for path in (remote_body.BODY_PATH, remote_body.SLEEP_PATH, remote_body.WRITEBACK_PATH, proxy_client.PROXY_PATH, refresh_fanout.PEER_PATH):
        assert path.startswith("/federation/") and "/api/v1" not in path
