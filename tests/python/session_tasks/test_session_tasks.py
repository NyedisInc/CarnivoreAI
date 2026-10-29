
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_tasks_routes import router
from src.core.resource_push.topics import RESOURCE_TOPICS, SESSION_TASKS
from src.core.session_tasks.reader import TaskReader, TranscriptUnreadable, fold_transcript
from src.core.session_tasks.watch import ALL_KEY, SessionTasksWatch, TICK_SECONDS


def use(block_id: str, name: str, args: Dict[str, Any], *, sidechain: bool = False) -> Dict[str, Any]:
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"content": [{"type": "tool_use", "id": block_id, "name": name, "input": args}]}}


def made(block_id: str, task_id: str) -> Dict[str, Any]:
    return {"type": "user", "toolUseResult": {"task": {"id": task_id}},
            "message": {"content": [{"type": "tool_result", "tool_use_id": block_id,
                                     "content": f"Task #{task_id} created successfully: x"}]}}


def write(path: Path, records: List[Dict[str, Any]], tail: str = "") -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n" + tail)
    return path


def test_taskcreate_and_taskupdate_fold_to_the_current_list(tmp_path: Path) -> None:
    path = write(tmp_path / "a.jsonl", [
        use("t1", "TaskCreate", {"subject": "write the reader", "activeForm": "writing the reader"}), made("t1", "1"),
        use("t2", "TaskCreate", {"subject": "write the route"}), made("t2", "2"),
        use("t3", "TaskCreate", {"subject": "drop me"}), made("t3", "3"),
        use("u1", "TaskUpdate", {"taskId": "1", "status": "completed"}),
        use("u2", "TaskUpdate", {"taskId": "2", "status": "in_progress"}),
        use("u3", "TaskUpdate", {"taskId": "3", "status": "deleted"}),
        use("s1", "TaskCreate", {"subject": "a subagent task"}, sidechain=True), made("s1", "9"),
    ], tail='{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "TaskUp')
    items = fold_transcript(path)
    assert [(i.id, i.status) for i in items] == [("1", "completed"), ("2", "in_progress")]
    assert items[0].active_form == "writing the reader"


def test_todowrite_replaces_the_whole_list(tmp_path: Path) -> None:
    path = write(tmp_path / "b.jsonl", [
        use("a", "TodoWrite", {"todos": [{"content": "old", "status": "pending", "activeForm": "old"}]}),
        use("b", "TodoWrite", {"todos": [{"content": "one", "status": "completed", "activeForm": "doing one"},
                                         {"content": "two", "status": "bogus", "activeForm": "doing two"}]}),
    ])
    assert [(i.subject, i.status) for i in fold_transcript(path)] == [("one", "completed"), ("two", "pending")]


def test_a_transcript_with_no_list_is_empty_and_a_missing_one_is_unreadable_never_empty(tmp_path: Path) -> None:
    assert fold_transcript(write(tmp_path / "c.jsonl", [{"type": "user", "message": {"content": "hi"}}])) == []
    with pytest.raises(TranscriptUnreadable):
        fold_transcript(tmp_path / "missing.jsonl")


def test_the_cache_refolds_only_when_the_file_moved(tmp_path: Path) -> None:
    path = write(tmp_path / "d.jsonl", [use("a", "TodoWrite", {"todos": [{"content": "x", "status": "pending"}]})])
    reader = TaskReader()
    first = reader.read(path)
    assert reader.read(path) is first
    write(path, [use("a", "TodoWrite", {"todos": [{"content": "x", "status": "completed"}]})])
    assert reader.read(path)[0].status == "completed"


def test_the_topic_is_advertised() -> None:
    assert SESSION_TASKS in RESOURCE_TOPICS


@pytest.mark.asyncio
async def test_the_watch_names_a_key_only_when_its_answer_moves_and_keeps_alive() -> None:
    from src.models.session_tasks import SessionTasks, TaskItem

    now, named, answer = [1000.0], [], [SessionTasks(state="empty", session_id="ses_1")]
    gate = asyncio.Semaphore(0)

    async def sleep(_: float) -> None:
        await gate.acquire()

    async def load() -> SessionTasks:
        return answer[0]

    watch = SessionTasksWatch(notify=named.append, sleep=sleep, clock=lambda: now[0])
    await watch.read("ses_1", load)

    async def step() -> None:
        now[0] += TICK_SECONDS
        gate.release()
        await asyncio.sleep(0.02)

    await step()
    assert named == []
    answer[0] = SessionTasks(state="ok", session_id="ses_1", tasks=[TaskItem(id="1", subject="x", status="pending")])
    await step()
    assert named == ["session_tasks:ses_1"]
    await watch.stop()
    assert not watch.running


def _app(infos: List[Any]) -> FastAPI:
    class Manager:
        _registry = None

        async def get_session_info(self, session_id):
            return next((i for i in infos if i.session.id == session_id), None)

        async def list_session_infos(self):
            return infos

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = Manager()
    return app


def _info(session_id: str, uuid: str, family: str = "claude") -> Any:
    return SimpleNamespace(session=SimpleNamespace(id=session_id, working_dir="/w"), label=f"name {session_id}",
                           tmux_session=None, claude_session_uuid=uuid, agent_family=family)


def test_routes_local_and_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.session_tasks import service
    from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT

    path = write(tmp_path / "u1.jsonl", [use("a", "TodoWrite", {"todos": [
        {"content": "ship it", "status": "in_progress", "activeForm": "shipping it"}]})])

    def locate(uuid, working_dir=None):
        return SimpleNamespace(outcome=CONVERSATION_PRESENT if uuid == "u1" else CONVERSATION_ABSENT,
                               path=path if uuid == "u1" else None)

    monkeypatch.setattr(service, "locate_transcript", locate)
    app = _app([_info("ses_1", "u1"), _info("ses_2", "u2"), _info("ses_3", "u3", family="codex")])
    with TestClient(app) as http:
        local = http.get("/api/v1/sessions/ses_1/tasks").json()
        assert local["state"] == "ok" and local["counts"]["in_progress"] == 1
        assert local["tasks"][0]["subject"] == "ship it"
        assert http.get("/api/v1/sessions/ses_2/tasks").json()["state"] == "empty"
        assert http.get("/api/v1/sessions/ses_3/tasks").json()["state"] == "unsupported"
        assert http.get("/api/v1/sessions/nope/tasks").status_code == 404
        everyone = http.get("/api/v1/session-tasks").json()
        assert [s["session_id"] for s in everyone["sessions"]] == ["ses_1"]
        assert everyone["sessions"][0]["label"] == "name ses_1"
    assert ALL_KEY == "*"
