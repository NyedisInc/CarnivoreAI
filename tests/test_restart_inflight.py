
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import HTTPException

from src.api import imported_restart_routes, recreate_routes
from src.api import session_restart_apply_routes as apply_routes
from src.core import restart_inflight


def test_claim_refuses_the_same_row_and_frees_it_after_a_failure():
    with restart_inflight.claim("row-a"):
        assert restart_inflight.in_flight("row-a")
        with pytest.raises(restart_inflight.RestartInFlightError):
            with restart_inflight.claim("row-a"):
                pass
        with restart_inflight.claim("row-b"):
            pass
    assert not restart_inflight.in_flight("row-a")

    with pytest.raises(ValueError):
        with restart_inflight.claim("row-a"):
            raise ValueError("create_session blew up")
    assert not restart_inflight.in_flight("row-a")


async def _second_call_is_refused(first, second):
    task = asyncio.create_task(first())
    await asyncio.sleep(0)
    with pytest.raises(HTTPException) as exc:
        await second()
    assert exc.value.status_code == 409
    return task


@pytest.fixture
def gate():
    return asyncio.Event()


def test_restart_route_answers_409_to_a_second_click(monkeypatch, gate):
    calls = []

    async def fake_inner(request, session_uuid):
        calls.append(session_uuid)
        await gate.wait()
        return "restarted"

    monkeypatch.setattr(apply_routes, "_restart_session", fake_inner)
    request = SimpleNamespace()

    async def scenario():
        task = await _second_call_is_refused(
            lambda: apply_routes.restart_session(request, "row-43"),
            lambda: apply_routes.restart_session(request, "row-43"),
        )
        gate.set()
        assert await task == "restarted"
        assert await apply_routes.restart_session(request, "row-43") == "restarted"

    asyncio.run(scenario())
    assert calls == ["row-43", "row-43"], "the refused click reached create"


def test_restart_route_does_not_serialise_different_rows(monkeypatch, gate):

    async def fake_inner(request, session_uuid):
        if session_uuid == "row-a":
            await gate.wait()
        return session_uuid

    monkeypatch.setattr(apply_routes, "_restart_session", fake_inner)
    request = SimpleNamespace()

    async def scenario():
        task = asyncio.create_task(apply_routes.restart_session(request, "row-a"))
        await asyncio.sleep(0)
        assert await apply_routes.restart_session(request, "row-b") == "row-b"
        gate.set()
        assert await task == "row-a"

    asyncio.run(scenario())


def test_imported_restart_route_answers_409_to_a_second_click(monkeypatch, gate):

    async def fake_inner(request, body):
        await gate.wait()
        return "started"

    monkeypatch.setattr(imported_restart_routes, "_imported_restart", fake_inner)
    body = SimpleNamespace(session_uuid="row-9", agent_type="claude")

    async def scenario():
        task = await _second_call_is_refused(
            lambda: imported_restart_routes.imported_restart(None, body),
            lambda: imported_restart_routes.imported_restart(None, body),
        )
        gate.set()
        assert await task == "started"

    asyncio.run(scenario())


def test_recreate_route_answers_409_to_a_second_click(monkeypatch, gate):
    from src.api import recreate_action

    async def fake_recreate(session_uuid, agent_type, get_manager, account_id=None, account_pinned=None):
        await gate.wait()
        return "started"

    monkeypatch.setattr(recreate_action, "recreate_by_uuid", fake_recreate)
    body = SimpleNamespace(session_uuid="row-7", agent_type="claude", account_id=None, account_pinned=None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    async def scenario():
        task = await _second_call_is_refused(
            lambda: recreate_routes.recreate_session(request, body),
            lambda: recreate_routes.recreate_session(request, body),
        )
        gate.set()
        assert await task == "started"

    asyncio.run(scenario())


def test_a_restart_and_a_recreate_of_one_row_share_the_slot(monkeypatch, gate):
    from src.api import recreate_action

    async def fake_inner(request, session_uuid):
        await gate.wait()
        return "restarted"

    async def fake_recreate(session_uuid, agent_type, get_manager, account_id=None, account_pinned=None):
        return "started"

    monkeypatch.setattr(apply_routes, "_restart_session", fake_inner)
    monkeypatch.setattr(recreate_action, "recreate_by_uuid", fake_recreate)
    body = SimpleNamespace(session_uuid="row-5", agent_type="claude")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    async def scenario():
        task = await _second_call_is_refused(
            lambda: apply_routes.restart_session(request, "row-5"),
            lambda: recreate_routes.recreate_session(request, body),
        )
        gate.set()
        await task

    asyncio.run(scenario())


def test_a_burst_of_five_restarts_spawns_once(monkeypatch, gate):
    calls = []

    async def fake_inner(request, session_uuid):
        calls.append(session_uuid)
        await gate.wait()
        return "restarted"

    monkeypatch.setattr(apply_routes, "_restart_session", fake_inner)

    async def scenario():
        tasks = [
            asyncio.create_task(apply_routes.restart_session(None, "row-26"))
            for _ in range(5)
        ]
        await asyncio.sleep(0)
        gate.set()
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(scenario())
    assert calls == ["row-26"]
    assert results.count("restarted") == 1
    refused = [r for r in results if isinstance(r, HTTPException)]
    assert len(refused) == 4
    assert all(r.status_code == 409 for r in refused)
    assert all(r.detail["code"] == "restart_in_progress" for r in refused)
    assert not restart_inflight.in_flight("row-26")
