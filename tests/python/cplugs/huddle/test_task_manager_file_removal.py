
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import files, store_identity
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.sdk import ports, task_folders
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.huddle.test_task_manager_files import BASE, app, caps, client, folder, item, upload  # noqa: F401
from tests.python.cplugs.reviewboard.test_attachment_removal_race import FailingCommit

ATTACHER = AgentCaller("ses_1", "cloude_a", "ses_1")
OTHER_AGENT = AgentCaller("ses_2", "cloude_b", "ses_2")
REMOVE = "task_manager_file_remove"


class FakeRoot:

    def __init__(self, path: Path):
        self.path = path

    def root(self) -> Path:
        return self.path


def store_of(app) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)


def owner_reply(client, item_id: int, name: str = "a.txt", data: bytes = b"hello") -> dict:
    stored = upload(client, item_id, name, data).json()
    message = client.post(f"{BASE}/items/{item_id}/messages", json={"text": "see", "files": [stored["id"]]}).json()["message"]
    return {"file": stored, "message": message}


def agent_reply(app, item_id: int, name: str = "mine.txt", key: str = "ses_1") -> dict:
    storage = runtime.host_for(app).storage("huddle")
    saved = files.save(storage, item_id, name, b"agent bytes")
    store_of(app).post(item_id, "here", actor="claude", kind="info", author_key=key, parts=files.parts_of([files.describe(storage, item_id, saved["id"])]))
    return saved


def agent_remove(app, caller: AgentCaller, item_id: int, file_id: str) -> dict:
    return asyncio.run(tools.call_tool(app.state.session_manager, caller, REMOVE, {"item": item_id, "file_id": file_id}))


def thread(client, item_id: int) -> list:
    return client.get(f"{BASE}/items/{item_id}").json()["thread"]


def on_disk(app, item_id: int, file_id: str) -> list:
    return list((folder(app) / "files" / str(item_id)).glob(f"{file_id}-*"))


@pytest.fixture
def task_root(tmp_path: Path):
    path = tmp_path / "tm"
    path.mkdir()
    ports.register(task_folders.ROOT_PORT, FakeRoot(path))
    yield path
    ports.unregister(task_folders.ROOT_PORT)


def test_the_owner_deletes_one_file(client, app, item):
    sent = owner_reply(client, item)
    kept = owner_reply(client, item, "other.txt", b"stay")
    r = client.delete(f"{BASE}/items/{item}/files/{sent['file']['id']}")
    assert r.status_code == 200, r.text
    assert r.json() == {"item": item, "file": sent["file"]["id"], "name": "a.txt", "redacted": True, "bytes": "deleted"}
    assert not on_disk(app, item, sent["file"]["id"]) and on_disk(app, item, kept["file"]["id"]), "only that file's bytes went"
    assert client.get(f"{BASE}/items/{item}/files/{sent['file']['id']}").status_code == 404
    first = next(m for m in thread(client, item) if m["id"] == sent["message"]["id"])
    assert "[a.txt was removed]" in first["text"] and not first.get("files"), "the message keeps a record that it was removed"


def test_the_attaching_agent_deletes_its_own_file(client, app, item):
    saved = agent_reply(app, item)
    result = agent_remove(app, ATTACHER, item, saved["id"])
    assert not result.get("isError"), result
    assert json.loads(result["content"][0]["text"])["bytes"] == "deleted"
    assert not on_disk(app, item, saved["id"])


def test_another_agent_is_refused_and_nothing_changes(client, app, item):
    saved = agent_reply(app, item)
    before = thread(client, item)
    result = agent_remove(app, OTHER_AGENT, item, saved["id"])
    assert result.get("isError") and "task_manager_not_attacher" in result["content"][0]["text"]
    assert on_disk(app, item, saved["id"]) and thread(client, item) == before


def test_an_agent_may_not_delete_the_owners_file_or_a_file_no_message_names(client, app, item):
    owners = owner_reply(client, item)["file"]
    stranded = upload(client, item, "loose.txt", b"x").json()
    for file_id in (owners["id"], stranded["id"]):
        result = agent_remove(app, ATTACHER, item, file_id)
        assert result.get("isError") and "task_manager_not_attacher" in result["content"][0]["text"]
        assert on_disk(app, item, file_id)


def test_the_owner_can_finish_stranded_bytes_no_message_names(client, app, item):
    stranded = upload(client, item, "loose.txt", b"x").json()
    r = client.delete(f"{BASE}/items/{item}/files/{stranded['id']}")
    assert r.status_code == 200 and r.json()["bytes"] == "deleted" and r.json()["redacted"] is False
    assert not on_disk(app, item, stranded["id"])


def test_unknown_and_malformed_ids_are_404(client, item):
    assert client.delete(f"{BASE}/items/{item}/files/deadbeef").status_code == 404
    assert client.delete(f"{BASE}/items/{item}/files/not-an-id").status_code == 404
    assert client.delete(f"{BASE}/items/999999/files/deadbeef").status_code == 404


def test_a_reply_that_had_located_the_file_is_refused_409_after_the_delete(client, app, item):
    sent = owner_reply(client, item)
    storage = runtime.host_for(app).storage("huddle")
    again = owner_reply(client, item, "b.txt")
    located = files.parts_of(files.attach(storage, item, [again["file"]["id"]]))
    assert client.delete(f"{BASE}/items/{item}/files/{again['file']['id']}").status_code == 200
    with pytest.raises(TaskManagerError) as refused:
        store_of(app).post(item, "see b", actor="joe", kind="reply", parts=located)
    assert refused.value.code == "task_manager_file_removed" and refused.value.status == 409
    assert client.post(f"{BASE}/items/{item}/messages", json={"files": [sent["file"]["id"], again["file"]["id"]]}).status_code == 404, "a fresh reply naming a deleted id finds no such file"


def test_a_symlink_is_refused_and_its_target_is_untouched(client, app, item, tmp_path):
    sent = owner_reply(client, item)
    target = tmp_path / "precious.txt"
    target.write_text("hello")
    [stored] = on_disk(app, item, sent["file"]["id"])
    stored.unlink()
    stored.symlink_to(target)
    before = thread(client, item)
    r = client.delete(f"{BASE}/items/{item}/files/{sent['file']['id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_manager_file_unsafe"
    assert target.read_text() == "hello" and stored.is_symlink()
    assert thread(client, item) == before, "nothing changed"


def task_file(app, root: Path, item_id: int, store_id: str | None) -> Path:
    task = task_folders.ensure_task(root, item_id, "all", None, "look at this", store_id=store_id)
    path = task_folders.kind_dir(task, task_folders.PASTES) / "abcd1234-note.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, b"note")
    os.close(fd)
    entry = {"id": "abcd1234", "name": "note.txt", "mime": "text/plain", "size": 4, "path": str(path)}
    store_of(app).post(item_id, "in the folder", actor="joe", kind="reply", parts=files.parts_of([entry]))
    return path


def own_store_id(app) -> str:
    with closing(runtime.host_for(app).storage("huddle").connect(True)) as conn, conn:
        return store_identity.ensure(conn)


def test_a_file_in_this_stores_task_folder_is_deleted(client, app, item, task_root):
    path = task_file(app, task_root, item, own_store_id(app))
    r = client.delete(f"{BASE}/items/{item}/files/abcd1234")
    assert r.status_code == 200 and r.json()["bytes"] == "deleted" and not path.exists()
    assert path.parent.is_dir(), "only the file went, not the folder"


def test_a_folder_another_store_made_is_never_touched(client, app, item, task_root):
    path = task_file(app, task_root, item, "ffffffffffffffff")
    before = thread(client, item)
    r = client.delete(f"{BASE}/items/{item}/files/abcd1234")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_manager_file_unsafe"
    assert path.read_bytes() == b"note" and thread(client, item) == before


def test_a_file_another_task_names_is_refused_and_nothing_changes(client, app, item):
    sent = owner_reply(client, item)
    other = client.post(f"{BASE}/lists/all/items", json={"text": "other"}).json()["id"]
    storage = runtime.host_for(app).storage("huddle")
    store_of(app).post(other, "same bytes", actor="joe", kind="reply", parts=files.parts_of([files.describe(storage, item, sent["file"]["id"])]))
    before = (thread(client, item), thread(client, other))
    r = client.delete(f"{BASE}/items/{item}/files/{sent['file']['id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_manager_file_shared"
    assert on_disk(app, item, sent["file"]["id"]) and (thread(client, item), thread(client, other)) == before


def name_again(app, item_id: int, saved: dict, actor: str = "joe", key: str = "") -> None:
    storage = runtime.host_for(app).storage("huddle")
    store_of(app).post(item_id, "again", actor=actor, kind="reply" if actor == "joe" else "info", author_key=key, parts=files.parts_of([files.describe(storage, item_id, saved["id"])]))


def test_an_agent_is_refused_when_another_author_also_names_the_file_but_the_owner_strips_every_message(client, app, item):
    saved = agent_reply(app, item)
    name_again(app, item, saved)
    before = thread(client, item)
    result = agent_remove(app, ATTACHER, item, saved["id"])
    assert result.get("isError") and "task_manager_file_shared" in result["content"][0]["text"]
    assert on_disk(app, item, saved["id"]) and thread(client, item) == before
    assert client.delete(f"{BASE}/items/{item}/files/{saved['id']}").status_code == 200
    texts = [m["text"] for m in thread(client, item) if "[mine.txt was removed]" in m["text"]]
    assert len(texts) == 2 and not on_disk(app, item, saved["id"]), "the owner's delete stripped both messages"


def test_an_agent_strips_all_of_its_own_messages(client, app, item):
    saved = agent_reply(app, item)
    name_again(app, item, saved, actor="claude", key="ses_1")
    assert not agent_remove(app, ATTACHER, item, saved["id"]).get("isError")
    assert sum("[mine.txt was removed]" in m["text"] for m in thread(client, item)) == 2


def test_bytes_only_another_tasks_message_names_survive_the_orphan_sweep(client, app, item):
    stored = upload(client, item, "a.txt", b"hello").json()
    other = client.post(f"{BASE}/lists/all/items", json={"text": "other"}).json()["id"]
    storage = runtime.host_for(app).storage("huddle")
    store_of(app).post(other, "names A's bytes", actor="joe", kind="reply", parts=files.parts_of([files.describe(storage, item, stored["id"])]))
    for path in on_disk(app, item, stored["id"]):
        os.utime(path, (time.time() - 3 * 86400,) * 2)
    assert files.sweep_orphans(storage) == 0 and on_disk(app, item, stored["id"])


def test_a_reply_posted_while_the_delete_is_paused_before_its_unlink_never_dangles(client, app, item, monkeypatch):
    sent = owner_reply(client, item)
    victim = sent["file"]["id"]
    storage = runtime.host_for(app).storage("huddle")
    attached = files.parts_of(files.attach(storage, item, [victim]))
    at_unlink, resume, answers = threading.Event(), threading.Event(), {}
    real_unlink = Path.unlink

    def paused_unlink(self, *args, **kwargs):
        if victim in self.name:
            at_unlink.set()
            assert resume.wait(timeout=10)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", paused_unlink)
    remover = threading.Thread(target=lambda: answers.update(removed=client.delete(f"{BASE}/items/{item}/files/{victim}")))
    remover.start()
    assert at_unlink.wait(timeout=10), "the delete never reached its unlink"
    try:
        answers["reply"] = store_of(app).post(item, "see that", actor="joe", kind="reply", parts=attached)
    except TaskManagerError as exc:
        answers["refused"] = exc
    resume.set()
    remover.join(timeout=20)
    assert answers["removed"].status_code == 200
    if "reply" in answers:
        assert on_disk(app, item, victim) or not any(f["id"] == victim for f in (answers["reply"]["message"].get("files") or [])), "the reply links bytes that were deleted"
    else:
        assert answers["refused"].code == "task_manager_file_removed"


def test_a_failed_commit_puts_the_bytes_back_and_a_retry_finishes(client, app, item, monkeypatch):
    sent = owner_reply(client, item)
    victim = sent["file"]["id"]
    before = thread(client, item)
    real = TaskManagerStore._connect
    monkeypatch.setattr(TaskManagerStore, "_connect", lambda self, write: FailingCommit(real(self, write)) if write else real(self, write))
    r = client.delete(f"{BASE}/items/{item}/files/{victim}")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "task_manager_bytes_not_removed"
    assert on_disk(app, item, victim) and thread(client, item) == before, "the bytes are back and the thread is unchanged"
    monkeypatch.setattr(TaskManagerStore, "_connect", real)
    assert client.delete(f"{BASE}/items/{item}/files/{victim}").json()["bytes"] == "deleted"


def test_a_failed_unlink_is_finished_by_repeating_the_call(client, app, item, monkeypatch):
    sent = owner_reply(client, item)
    victim = sent["file"]["id"]
    real_unlink, failing = Path.unlink, [True]

    def stubborn(self, *args, **kwargs):
        if victim in self.name and failing:
            failing.clear()
            raise PermissionError("denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stubborn)
    first = client.delete(f"{BASE}/items/{item}/files/{victim}")
    assert first.status_code == 503 and first.json()["detail"]["code"] == "task_manager_bytes_not_removed"
    assert "[a.txt was removed]" in next(m for m in thread(client, item) if m["id"] == sent["message"]["id"])["text"], "the thread already says it"
    retry = client.delete(f"{BASE}/items/{item}/files/{victim}")
    assert retry.status_code == 200 and retry.json()["bytes"] == "deleted" and retry.json()["redacted"] is False
    assert not any(p for p in (folder(app) / "files" / str(item)).glob(f"*{victim}-*")), "no bytes under any name"


def test_the_tool_is_registered_with_its_description():
    described = {d["name"]: d["description"] for d in tools.tool_definitions()}
    assert REMOVE in described and "attached" in described[REMOVE]
