
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.core.session_move import apply as ma
from src.core.session_project_binding import resolve_project_binding
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence
from tests.session_move.helpers import (
    CONVERSATION,
    FakeSettings,
    add_project,
    add_session,
    migrated_state,
    open_conn,
    resumable,
    write_transcript,
)


class FakeManager:

    def __init__(self, pane_state: str = "dead") -> None:
        self.pane_state = pane_state
        self.respawns: List[Dict[str, Any]] = []
        self._registry = SimpleNamespace(backends={}, sessions={})

    async def restart_preview(self, name: str, *, socket_name: Any = None) -> Any:
        return resumable(self.pane_state)

    async def respawn_session(self, name: str, **kwargs: Any) -> dict:
        self.respawns.append({"name": name, **kwargs})
        return {"ok": True, "detail": "resumed", "conversation": "resumed", "killed_live_pane": False}


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    temp_root = tmp_path / "carnivore-projects"
    source = temp_root / "ses_ab12"
    (source / "src").mkdir(parents=True)
    (source / "notes.md").write_text("hello", encoding="utf-8")
    (source / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (source / ".cc.theme").write_text("matrix", encoding="utf-8")
    project = temp_root / "app"
    project.mkdir()
    corpus = tmp_path / "claude-projects"
    transcript = write_transcript(corpus, source)
    monkeypatch.setattr("src.core.claude_transcript_correlate.default_projects_dir", lambda: corpus)
    state = migrated_state(tmp_path)
    with closing(open_conn(state)) as conn:
        project_id = add_project(conn, project, "app")
        uuid = add_session(conn, source)
    return {"temp_root": temp_root, "source": source, "project": project, "project_id": project_id,
            "state": state, "uuid": uuid, "corpus": corpus, "transcript": transcript,
            "settings": FakeSettings(working_dir=temp_root, state_dir=state)}


def _run(world: dict, manager: FakeManager, monkeypatch: pytest.MonkeyPatch, *, pane_in: Any = "destination",
         project: bool = True, new_folder: Any = None, confirm: bool = False) -> dict:
    def _measured(tmux_name: str, socket_name: str) -> Any:
        if pane_in != "destination":
            return pane_in
        return manager.respawns[-1]["start_directory"] if manager.respawns else None

    monkeypatch.setattr(ma, "pane_folder", _measured)
    return asyncio.run(ma.apply_move(
        manager, lambda: open_conn(world["state"]), world["uuid"],
        project_id=world["project_id"] if project else None, new_folder=new_folder,
        settings=world["settings"], confirm_restart_live=confirm))


def _row(world: dict) -> tuple:
    with closing(open_conn(world["state"])) as conn:
        return tuple(conn.execute("SELECT working_dir, project_id FROM sessions WHERE session_uuid = ?",
                                  (world["uuid"],)).fetchone())


def test_a_move_carries_the_files_restarts_there_and_writes_the_row(world: dict, monkeypatch) -> None:
    manager = FakeManager()
    answer = _run(world, manager, monkeypatch)
    dest = str(world["project"].resolve())
    assert answer["done"]["files_moved"] == 2
    assert (world["project"] / "src" / "app.py").exists() and not (world["source"] / "notes.md").exists()
    assert (world["source"] / ".cc.theme").exists() and not (world["project"] / ".cc.theme").exists()
    [call] = manager.respawns
    assert call["start_directory"] == dest and call["require_agent_resume"] is True
    assert call["live_restart_confirmed"] is False
    assert _row(world) == (dest, world["project_id"])
    with closing(open_conn(world["state"])) as conn:
        assert resolve_project_binding(conn, dest).project_id == world["project_id"]
    assert len(list(Path(answer["done"]["backup"], "files").rglob("*.py"))) == 1


def test_the_resume_finds_the_conversation_where_it_was_and_nothing_is_copied(world: dict, monkeypatch) -> None:
    _run(world, FakeManager(), monkeypatch)
    presence = conversation_presence(CONVERSATION, working_dir=str(world["project"].resolve()))
    assert presence.outcome == CONVERSATION_PRESENT
    assert presence.path == world["transcript"]
    assert [p.name for p in world["corpus"].rglob("*.jsonl")] == [f"{CONVERSATION}.jsonl"]


def test_a_pane_that_did_not_land_in_the_destination_puts_the_files_back(world: dict, monkeypatch) -> None:
    with pytest.raises(ma.SessionMoveFailed) as caught:
        _run(world, FakeManager(), monkeypatch, pane_in=str(world["source"].resolve()))
    assert caught.value.step == "restart" and caught.value.undo_errors == []
    assert (world["source"] / "notes.md").exists() and (world["source"] / "src" / "app.py").exists()
    assert not (world["project"] / "notes.md").exists()
    assert _row(world) == (str(world["source"]), None)


def test_a_live_pane_is_not_touched_without_the_confirmation(world: dict, monkeypatch) -> None:
    manager = FakeManager(pane_state="alive")
    with pytest.raises(ma.SessionMoveRefused) as caught:
        _run(world, manager, monkeypatch)
    assert caught.value.code == ma.LIVE_NEEDS_CONFIRM
    assert manager.respawns == [] and (world["source"] / "notes.md").exists()


def test_a_live_pane_with_the_confirmation_passes_the_permission_forward(world: dict, monkeypatch) -> None:
    manager = FakeManager(pane_state="alive")
    _run(world, manager, monkeypatch, confirm=True)
    assert manager.respawns[0]["live_restart_confirmed"] is True


def test_a_new_folder_is_created_and_becomes_the_session_s_project(world: dict, monkeypatch) -> None:
    target = world["temp_root"] / "fresh-app"
    answer = _run(world, FakeManager(), monkeypatch, project=False, new_folder=str(target))
    assert target.is_dir() and (target / "notes.md").exists()
    working_dir, project_id = _row(world)
    assert working_dir == str(target.resolve()) and project_id not in (None, world["project_id"])
    assert answer["done"]["project_created"] is True


def test_the_route_answers_a_refusal_as_409_with_the_reason(world: dict, monkeypatch) -> None:
    from src.api import session_move_routes as routes
    from src.models.session_move import SessionMoveRequest

    async def _refuse(*args: Any, **kwargs: Any) -> dict:
        raise ma.SessionMoveRefused(None, "collision", "the destination already has notes.md")

    monkeypatch.setattr(routes, "apply_move", _refuse)
    monkeypatch.setattr(routes.projects_service, "guard_writable", lambda settings: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=FakeManager())))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.move_session_folder(world["uuid"], SessionMoveRequest(project_id=1, apply=True), request))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "collision"
