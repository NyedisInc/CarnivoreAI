
from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
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

from src.api import session_restart_apply_routes as apply_routes
from src.core import restart_live_gate, session_restart
from tests.socket_guard import TEST_SOCKET_NAME




@pytest.mark.parametrize(
    "raw, epoch, expected",
    [
        ("0|17|cloude_a", 17, True),
        ("0|17|cloude_a", None, True),
        ("1|17|cloude_a", 17, False),
        ("0|99|cloude_a", 17, False),
        ("0|17|cloude_a-2", 17, None),
        ("", 17, None),
        ("garbage", 17, None),
        ("0|x|cloude_a", 17, None),
    ],
)
def test_classify_probe(raw, epoch, expected):
    assert restart_live_gate.classify_probe(raw, "cloude_a", epoch) is expected




def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True
    )


@pytest.fixture
def live_session():
    name = f"cloude_t516_{uuid.uuid4().hex[:8]}-2"
    assert _tmux("new-session", "-d", "-s", name, "sleep 60").returncode == 0
    epoch = int(_tmux("display-message", "-p", "-t", f"={name}:",
                      "#{session_created}").stdout.strip())
    yield name, epoch
    _tmux("kill-session", "-t", f"={name}")


def test_probe_reads_the_exact_live_instance(live_session):
    name, epoch = live_session
    assert restart_live_gate._probe(name, epoch, TEST_SOCKET_NAME) is True
    assert restart_live_gate._probe(name, epoch + 1, TEST_SOCKET_NAME) is False


def test_probe_never_prefix_matches_a_newer_twin(live_session):
    name, epoch = live_session
    base = name[: -len("-2")]
    assert restart_live_gate._probe(base, None, TEST_SOCKET_NAME) is None


def test_bound_instance_running_reads_the_row(live_session, tmp_path):
    name, epoch = live_session
    db = tmp_path / "carnivore.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (session_uuid TEXT, tmux_socket TEXT, "
        "tmux_name TEXT, tmux_created_epoch INTEGER)"
    )
    conn.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        [("live", TEST_SOCKET_NAME, name, epoch),
         ("stale", TEST_SOCKET_NAME, name, epoch - 5),
         ("nameless", TEST_SOCKET_NAME, None, None)],
    )
    conn.commit()
    conn.close()
    run = restart_live_gate.bound_instance_running
    assert run(db, "live", "unused") is True
    assert run(db, "stale", "unused") is False
    assert run(db, "nameless", "unused") is None
    assert run(db, "absent", "unused") is None




def _route_fixture(monkeypatch, tmp_path, running):
    (tmp_path / "carnivore.db").write_bytes(b"")
    monkeypatch.setattr(type(apply_routes.settings), "get_state_dir", lambda self: tmp_path)
    monkeypatch.setattr(
        session_restart, "resolve_restart_source",
        lambda conn, session_uuid: session_restart.RestartSource(
            session_restart.RESTART_NO_CONVERSATION, parent_id=26,
            working_dir="/tmp", agent_type="claude", title="Storefront",
        ),
    )
    monkeypatch.setattr(
        restart_live_gate, "bound_instance_running", lambda *a: running
    )
    calls = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop after the spawn decision")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        session_manager=SimpleNamespace(create_session=fake_create))))
    return calls, request


def test_route_refuses_a_restart_of_a_running_row(monkeypatch, tmp_path):
    calls, request = _route_fixture(monkeypatch, tmp_path, True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(apply_routes.restart_session(request, "row-26"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "session_already_running"
    assert calls == []


@pytest.mark.parametrize("running", [False, None])
def test_route_restarts_when_not_measured_running(monkeypatch, tmp_path, running):
    calls, request = _route_fixture(monkeypatch, tmp_path, running)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(apply_routes.restart_session(request, "row-26"))
    assert exc.value.status_code == 500
    assert len(calls) == 1
