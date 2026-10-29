
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.api import session_conversations_routes as routes


class FakeManager:

    async def create_session(self, **kwargs):
        return SimpleNamespace(tmux_session="carnivore_child", model_dump=lambda: {"id": "ses_child"})

    def tmux_socket_name(self) -> str:
        return "carnivore"


def test_resume_survives_a_locked_database_when_stamping_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {"id": 7, "agent_type": "claude", "launch_record": None, "working_dir": "/tmp", "title": "t",
              "tmux_name": "carnivore_src", "model": None}

    async def threadpool(fn, *args, **kwargs):
        return source if fn is routes._read else fn(*args, **kwargs)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(routes, "run_in_threadpool", threadpool)
    monkeypatch.setattr(routes, "connect", locked)
    monkeypatch.setattr(routes, "_db_path", lambda: "/nonexistent.db")
    monkeypatch.setattr("src.api.launch_profile_errors.refuse_gone_profile", lambda *a, **k: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=FakeManager())))
    response = asyncio.run(routes.resume_conversation(request, "uuid-1", "conv-1"))
    assert response.lineage_recorded is False
    assert response.detail



def test_fork_survives_a_locked_database_when_stamping_lineage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.api import session_fork_routes as fork_routes
    from src.core import session_fork

    (tmp_path / "carnivore.db").write_bytes(b"")
    source = session_fork.ForkSource(outcome=session_fork.FORK_READY, parent_id=7, claude_session_uuid="u",
                                     working_dir="/tmp", label="parent")

    async def threadpool(fn, *args, **kwargs):
        return source if fn.__name__ == "_resolve" else fn(*args, **kwargs)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(fork_routes, "run_in_threadpool", threadpool)
    monkeypatch.setattr(fork_routes, "refuse_remote", lambda *a, **k: None)
    monkeypatch.setattr(fork_routes, "settings", SimpleNamespace(get_state_dir=lambda: tmp_path))
    monkeypatch.setattr("src.core.db.db_path_for", lambda state_dir: tmp_path / "carnivore.db")
    monkeypatch.setattr("src.api.launch_profile_errors.refuse_gone_profile", lambda *a, **k: None)
    monkeypatch.setattr(session_fork, "stamp_fork_child", locked)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=FakeManager())))
    response = asyncio.run(fork_routes.fork_session(request, "carnivore_src"))
    assert response.lineage_recorded is False
    assert response.detail
