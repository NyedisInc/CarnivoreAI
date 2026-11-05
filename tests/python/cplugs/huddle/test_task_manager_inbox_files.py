
from __future__ import annotations

import errno
import os
import time
from pathlib import Path

from src.cplugs.huddle import inbox_files, rules
from tests.python.cplugs.huddle.test_task_manager_inbox import BASE, env, queue  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401


def thread_files(client, item_id: int, key: str = "12") -> list:
    row = next(i for i in client.get(f"{BASE}/lists/{key}").json()["items"] if i["id"] == item_id)
    return [f for m in row["thread"] for f in (m.get("files") or [])]


def stage(client, key: str = "12", name: str = "shot.txt", data: bytes = b"pasted bytes") -> dict:
    return client.post(f"{BASE}/lists/{key}/inbox/files", files={"file": (name, data, "application/octet-stream")}).json()


def test_a_staged_file_rides_the_entry_to_every_item_filed_from_it(client, env, app):
    staged = stage(client)
    assert set(staged) == {"id", "name", "mime", "size"} and staged["name"] == "shot.txt"
    answer = client.post(f"{BASE}/lists/12/inbox", json={"text": "backlog a and b", "file_ids": [staged["id"]]}).json()
    entry = answer["entry"]
    assert [f["name"] for f in entry["files"]] == ["shot.txt"]
    assert Path(entry["files"][0]["path"]).read_bytes() == b"pasted bytes"
    items = [{"title": "a", "text": "do a"}, {"title": "b", "text": "do b"}]
    filed = client.post(f"{BASE}/inbox/{entry['id']}/file", json={"items": items}).json()["items"]
    assert len(filed) == 2
    for item in filed:
        carried = thread_files(client, item["id"])
        assert [f["name"] for f in carried] == ["shot.txt"]
        got = client.get(f"{BASE}/items/{item['id']}/files/{carried[0]['id']}")
        assert got.status_code == 200 and got.content == b"pasted bytes"


def test_a_foreign_unknown_or_expired_id_is_refused_and_writes_nothing(client, env, app):
    staged = stage(client, key="12")
    other = client.post(f"{BASE}/lists/all/inbox", json={"text": "x", "file_ids": [staged["id"]]})
    assert other.status_code == 400
    assert client.post(f"{BASE}/lists/12/inbox", json={"text": "x", "file_ids": ["deadbeef"]}).status_code == 400
    assert client.post(f"{BASE}/lists/12/inbox", json={"text": "x", "file_ids": ["../../etc"]}).status_code == 400
    assert client.get(f"{BASE}/inbox").json()["entries"] == []
    folder = inbox_files.staged_dir(env.store.storage, "12")
    old = time.time() - inbox_files.STAGED_TTL_S - 60
    for path in folder.iterdir():
        os.utime(path, (old, old))
    assert client.post(f"{BASE}/lists/12/inbox", json={"text": "x", "file_ids": [staged["id"]]}).status_code == 400


def test_unclaimed_staged_files_expire_and_a_finished_entry_folder_goes(client, env):
    staged = stage(client)
    storage = env.store.storage
    folder = inbox_files.staged_dir(storage, "12")
    assert inbox_files.sweep(storage, set()) == 0 and any(folder.iterdir())
    assert inbox_files.sweep(storage, set(), now=time.time() + inbox_files.STAGED_TTL_S + 60) == 1
    assert not folder.exists() and staged["id"]


def test_a_switched_off_list_adds_the_item_at_once_with_the_files(client, env):
    client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": False})
    staged = stage(client)
    item = client.post(f"{BASE}/lists/12/inbox", json={"text": "plain add", "file_ids": [staged["id"]]}).json()["item"]
    carried = thread_files(client, item["id"])
    assert [f["name"] for f in carried] == ["shot.txt"]


def test_a_failed_copy_on_a_direct_add_keeps_the_only_copy(client, env, monkeypatch):
    client.put(f"{BASE}/lists/12/inbox-prefs", json={"file_through_session": False})
    staged = stage(client)

    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "no space left on device")

    monkeypatch.setattr(inbox_files.shutil, "copyfile", full)
    item = client.post(f"{BASE}/lists/12/inbox", json={"text": "plain add", "file_ids": [staged["id"]]}).json()["item"]
    kept = list(inbox_files.staged_dir(env.store.storage, "12").iterdir())
    assert [p.name.split("-", 1)[0] for p in kept] == [staged["id"]]
    row = next(i for i in client.get(f"{BASE}/lists/12").json()["items"] if i["id"] == item["id"])
    assert any("could not attach" in m["text"] and "shot.txt" in m["text"] for m in row["thread"])


def test_attaching_files_to_a_question_leaves_it_unanswered(client, env):
    staged = stage(client)
    entry = client.post(f"{BASE}/lists/12/inbox", json={"text": "ask x", "file_ids": [staged["id"]]}).json()["entry"]
    item = env.store.add("12", "which one?", actor=rules.CLAUDE, kind=rules.QUESTION)
    before = env.store.item(item["id"])["status"]
    env.inbox.link_item(entry["id"], item["id"])
    assert thread_files(client, item["id"]) and env.store.item(item["id"])["status"] == before == "question"


def test_an_old_entry_filed_now_keeps_its_files_for_every_item(client, env):
    staged = stage(client)
    entry = client.post(f"{BASE}/lists/12/inbox", json={"text": "backlog a and b", "file_ids": [staged["id"]]}).json()["entry"]
    old = time.time() - 3 * inbox_files.ENTRY_TTL_S
    folder = inbox_files.entry_dir(env.store.storage, entry["id"])
    os.utime(folder, (old, old))
    env.inbox.claim(entry["id"], "filed", env.store._clock())
    first = env.store.add("12", "do a", actor=rules.JOE)
    env.inbox.link_item(entry["id"], first["id"])
    stage(client, name="other.txt")
    second = env.store.add("12", "do b", actor=rules.JOE)
    env.inbox.link_item(entry["id"], second["id"])
    assert [f["name"] for f in thread_files(client, first["id"])] == ["shot.txt"]
    assert [f["name"] for f in thread_files(client, second["id"])] == ["shot.txt"]


def test_a_sweep_never_takes_an_entry_added_after_it_read_keep(client, env):
    storage = env.store.storage
    keep = env.inbox.keep_file_ids(time.time())
    staged = stage(client)
    entry = client.post(f"{BASE}/lists/12/inbox", json={"text": "added in the gap", "file_ids": [staged["id"]]}).json()["entry"]
    assert entry["id"] not in keep
    inbox_files.sweep(storage, keep)
    assert [f["name"] for f in inbox_files.listing(storage, entry["id"])] == ["shot.txt"]
