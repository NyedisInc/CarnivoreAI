
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import bookmark_rewind_routes as routes
from src.api import checkpoint_codex_note as note_mod
from src.api.checkpoint_revert_routes import require_owner
from src.core.bookmarks import locate
from src.core.checkpoints import bookmark_rewind as br
from src.core.checkpoints import capture as cap
from src.core.checkpoints import revert as rv
from src.core.checkpoints.store import CheckpointStore
from src.core.checkpoints.turns import codex_turn_number, newest_codex_turn
from tests.checkpoints.test_capture import git


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    state = tmp_path / "state"
    store = CheckpointStore(state / "bookmarks.db")
    (repo / "a.txt").write_text("a in turn 1\n")
    cp = cap.capture(repo, session_uuid="s1", conversation="c1", prompt_uuid="p1", store=store, state_root=state).checkpoint
    assert cp is not None
    (repo / "a.txt").write_text("a later\n")
    (repo / "new.py").write_text("x\n")
    calls: list = []
    mark = SimpleNamespace(id=7, session_uuid="s1", entry_uuid="p1", claude_session_uuid="c1",
                           as_dict=lambda: {"session_uuid": "s1", "entry_uuid": "p1", "claude_session_uuid": "c1"})
    row = SimpleNamespace(id=1, session_uuid="s1", working_dir=str(repo), tmux_name="t1", agent_type="claude")

    async def bookmark(_id):
        return mark

    async def blocked(*_a, **_k):
        return []

    async def conversation(_request, session_uuid, body):
        calls.append(("conversation", (repo / "a.txt").read_text()))
        return routes.RewindResponse(claude_session_uuid="copy", previous_claude_session_uuid="c1", killed_live_pane=True,
                                     resumed_copy=True, ok=True)

    real_revert = rv.revert

    def revert(*args):
        calls.append(("files", (repo / "a.txt").read_text()))
        return real_revert(*args)

    monkeypatch.setattr(routes, "_bookmark", bookmark)
    monkeypatch.setattr(routes.rows, "read_row", lambda _u: row)
    monkeypatch.setattr(routes, "get_store", lambda: store)
    monkeypatch.setattr(routes, "state_root", lambda: state)
    monkeypatch.setattr(routes, "_blocked_by", blocked)
    monkeypatch.setattr(routes, "rewind_point", conversation)
    monkeypatch.setattr(routes.revert_mod, "revert", revert)

    class Manager:

        def __getattr__(self, name):
            if name.startswith("send"):
                raise AssertionError(f"the pane was driven: {name}")
            raise AttributeError(name)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=Manager())))
    return SimpleNamespace(repo=repo, store=store, cp=cp, calls=calls, request=request, mark=mark, state=state)


def call(w, mode: str, confirm: bool = True) -> routes.RewindFilesResponse:
    return asyncio.run(routes.rewind_bookmark_files(w.request, 7, routes.RewindFilesRequest(mode=mode, confirm=confirm)))


def test_both_moves_the_conversation_first_then_the_files(world) -> None:
    out = call(world, "both")
    assert [c[0] for c in world.calls] == ["conversation", "files"]
    assert world.calls[0][1] == "a later\n", "no file moved before the conversation step"
    assert out.files_restored and out.conversation is not None and out.files_error is None
    assert (world.repo / "a.txt").read_text() == "a in turn 1\n" and not (world.repo / "new.py").exists()


def test_a_failed_file_step_says_so_and_keeps_the_snapshot(world, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a):
        world.calls.append(("files", None))
        raise OSError("disk went away")

    monkeypatch.setattr(routes.revert_mod, "revert", broken)
    out = call(world, "both")
    assert [c[0] for c in world.calls] == ["conversation", "files"]
    assert not out.files_restored and out.files_error == "conversation rewound, files not restored"
    assert out.conversation is not None and out.conversation.ok
    assert world.cp.id in [cp.id for cp in world.store.for_session("s1")], "the snapshot is kept"
    assert (world.repo / "a.txt").read_text() == "a later\n"


def test_a_refused_conversation_moves_no_file(world, monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(*_a):
        world.calls.append(("conversation", None))
        raise HTTPException(409, "not_live")

    monkeypatch.setattr(routes, "rewind_point", refused)
    with pytest.raises(HTTPException):
        call(world, "both")
    assert [c[0] for c in world.calls] == ["conversation"]
    assert (world.repo / "a.txt").read_text() == "a later\n" and (world.repo / "new.py").exists()


def test_files_only_leaves_the_conversation_alone(world) -> None:
    out = call(world, "files")
    assert [c[0] for c in world.calls] == ["files"] and out.conversation is None and out.files_restored
    assert (world.repo / "a.txt").read_text() == "a in turn 1\n"


def test_no_confirm_moves_nothing(world) -> None:
    with pytest.raises(HTTPException) as caught:
        call(world, "both", confirm=False)
    assert caught.value.status_code == 400 and world.calls == []


def test_a_mid_turn_bookmark_gets_the_conversation_only_and_says_why(world, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = tmp_path / "c1.jsonl"
    records = [{"type": "user", "uuid": "p1", "parentUuid": None, "sessionId": "c1", "timestamp": "2026-10-30T10:00:00Z",
                "message": {"role": "user", "content": "fix it"}},
               {"type": "assistant", "uuid": "a1", "parentUuid": "p1", "sessionId": "c1",
                "timestamp": "2026-10-30T10:00:01Z",
                "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "on it"}]}}]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    monkeypatch.setattr(locate, "find_transcript", lambda *_a, **_k: transcript)
    marks = br.annotate(world.store, [{"session_uuid": "s1", "entry_uuid": "p1", "claude_session_uuid": "c1"},
                                      {"session_uuid": "s1", "entry_uuid": "a1", "claude_session_uuid": "c1"}], None)
    assert (marks[0]["files_checkpoint_id"], marks[0]["files_unavailable"]) == (world.cp.id, None)
    assert (marks[1]["files_checkpoint_id"], marks[1]["files_unavailable"]) == (None, br.MID_TURN)
    world.mark.entry_uuid = "a1"
    with pytest.raises(HTTPException) as caught:
        call(world, "both")
    assert caught.value.status_code == 409 and world.calls == [], "refused before the conversation moved"


def test_the_files_route_is_the_owners_alone() -> None:
    route = next(r for r in routes.router.routes if r.path == "/bookmarks/{bookmark_id}/rewind/files")
    assert any(d.call is require_owner for d in route.dependant.dependencies)
    from src.core.mcp.registry import core_sessions

    assert "rewind/files" not in repr(vars(core_sessions)), "no MCP path"


def test_codex_files_go_back_with_a_note_naming_turn_n(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [{"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}},
             {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t1"}},
             {"type": "event_msg", "payload": {"type": "user_message", "message": "edit"}},
             {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
             {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t2"}}]
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text("".join(json.dumps(r) + "\n" for r in lines))
    turn = newest_codex_turn(lines)
    assert (turn.prompt_uuid, turn.used_tools) == ("t2", True)
    assert codex_turn_number(rollout.read_text().splitlines(), "t2") == 2
    sent: list = []

    class Manager:
        _registry = SimpleNamespace(registered_ids_for_tmux_name=lambda _n: ["ses_1"])

        async def send_command(self, text, session_id):
            sent.append((session_id, text))

    async def clear(_app, _sid):
        return "clear"

    monkeypatch.setattr(note_mod, "codex_rollout", lambda _t: str(rollout))
    monkeypatch.setattr("src.core.approvals.dialog_gate.dialog_verdict", clear)
    monkeypatch.setattr("src.core.approvals.dialog_gate.CLEAR", "clear")
    cp = SimpleNamespace(conversation="thread", prompt_uuid="t2")
    row = SimpleNamespace(agent_type="codex", tmux_name="t")
    assert asyncio.run(note_mod.tell_codex(Manager(), None, row, cp)) == (True, None)
    assert sent[0][0] == "ses_1" and "end of turn 2" in sent[0][1]
    claude = SimpleNamespace(agent_type="claude", tmux_name="t")
    assert asyncio.run(note_mod.tell_codex(Manager(), None, claude, cp)) == (False, None) and len(sent) == 1
