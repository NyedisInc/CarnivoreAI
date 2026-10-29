
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import board_port
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_on, task_manager_store
from tests.python.cplugs.reviewboard.test_attachments import MD, PDF, b64, board, client, env, sidecar  # noqa: F401


@pytest.fixture
def two(client, board) -> list:
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments",
                    json={"files": [{"name": "a.md", "content_base64": b64(MD)}, {"name": "b.pdf", "content_base64": b64(PDF)}], "request_review": False})
    assert r.status_code == 200, r.text
    return r.json()["attachments"]


def test_the_route_removes_a_file_and_the_index_keeps_a_tombstone(env, client, board, two):
    published = len(env.published)
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    gone = r.json()
    assert gone["file_id"] == two[0]["file_id"] and gone["removed_at"] and gone["etag"]
    entries = sidecar(env, board["slug"])["ext"]["attachments"]["files"]
    assert [e["name"] for e in entries] == ["a.md", "b.pdf"], "the entry stays in the index"
    assert entries[0]["removed_at"] == gone["removed_at"] and "removed_at" not in entries[1]
    assert {k: entries[0][k] for k in ("file_id", "item_id", "message_id", "name", "bytes", "sha256", "added_at")} == \
        {k: two[0][k] for k in ("file_id", "item_id", "message_id", "name", "bytes", "sha256", "added_at")}
    listed = client.get(f"{BASE}/boards/{board['slug']}/attachments").json()
    assert [a["name"] for a in listed["attachments"]] == ["b.pdf"]
    assert [(t["name"], t["removed_at"], "url" in t) for t in listed["removed"]] == [("a.md", gone["removed_at"], False)]
    assert [t for t in env.published[published:] if t.startswith("cplug.reviewboard.")] == ["cplug.reviewboard.boards"]


def test_an_unknown_or_already_removed_id_is_404_and_writes_nothing(env, client, board, two):
    url = f"{BASE}/boards/{board['slug']}/attachments"
    assert client.delete(f"{url}/{two[1]['file_id']}").status_code == 200
    before = sidecar(env, board["slug"])
    for file_id in (two[1]["file_id"], "00000000"):
        r = client.delete(f"{url}/{file_id}")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "reviewboard_no_attachment", (file_id, r.text)
    assert client.delete(f"{BASE}/boards/20261014-nope/attachments/{two[0]['file_id']}").status_code == 404
    assert sidecar(env, board["slug"]) == before


def test_a_malformed_file_id_is_422_on_both_doors_and_writes_nothing(env, client, board, two):
    before = sidecar(env, board["slug"])
    for file_id in ("not-a-file-id", "ABCDEF12", "abcdef1", "abcdef123"):
        r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{file_id}")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "reviewboard_invalid", (file_id, r.text)
        ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": file_id})
        assert not ok and "reviewboard_invalid" in text, (file_id, text)
    assert sidecar(env, board["slug"]) == before


def test_an_entry_with_any_removed_at_is_removed_everywhere(env, client, board, two):
    from src.cplugs.reviewboard import attachments  # noqa: PLC0415

    entry = {**two[0], "removed_at": None}
    entry.pop("url")
    assert attachments.REMOVED_AT in attachments.entries_of({"ext": {"attachments": {"v": 1, "files": [entry]}}})[0]
    path = env.board(board["slug"]) / "sidecar.json"
    doc = json.loads(path.read_text())
    doc["ext"]["attachments"]["files"][0]["removed_at"] = None
    path.write_text(json.dumps(doc))
    listed = client.get(f"{BASE}/boards/{board['slug']}/attachments").json()
    assert [a["name"] for a in listed["attachments"]] == ["b.pdf"] and [a["name"] for a in listed["removed"]] == ["a.md"]
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "reviewboard_no_attachment"


def test_a_malformed_entry_with_the_same_id_is_skipped_not_marked(env, client, board, two):
    path = env.board(board["slug"]) / "sidecar.json"
    doc = json.loads(path.read_text())
    doc["ext"]["attachments"]["files"].insert(0, {"file_id": two[0]["file_id"]})
    path.write_text(json.dumps(doc))
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    files = sidecar(env, board["slug"])["ext"]["attachments"]["files"]
    assert files[0] == {"file_id": two[0]["file_id"]} and files[1]["removed_at"] == r.json()["removed_at"] and r.json()["attachment"]["name"] == "a.md"


def _pane_attach(env, tmp_path, slug: str, **extra) -> dict:
    path = tmp_path / "pane-note.md"
    path.write_bytes(MD)
    ok, answer = env.call("task_manager_board_attachment_add", {"board": slug, "file_paths": [str(path)], "request_review": False, **extra})
    assert ok, answer
    return answer["attachments"][0]


def test_the_mcp_tool_removes_the_same_way(env, client, board, tmp_path):
    entry = _pane_attach(env, tmp_path, board["slug"])
    ok, answer = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": entry["file_id"]})
    assert ok, answer
    assert answer["file_id"] == entry["file_id"] and answer["removed_at"] and "attached_by" not in answer["attachment"]
    entries = sidecar(env, board["slug"])["ext"]["attachments"]["files"]
    assert entries[0]["removed_at"] == answer["removed_at"]
    ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": entry["file_id"]})
    assert not ok and "reviewboard_no_attachment" in text


def test_the_mcp_tool_refuses_unknown_arguments_and_a_missing_id(env, board, two):
    before = sidecar(env, board["slug"])
    ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"]})
    assert not ok and "file_id" in text
    ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": two[0]["file_id"], "force": True})
    assert not ok and "unknown argument" in text
    assert sidecar(env, board["slug"]) == before


def test_a_tombstone_survives_a_later_attach(env, client, board, two):
    client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "c.md", "content_base64": b64(MD)}]})
    assert r.status_code == 200, r.text
    entries = sidecar(env, board["slug"])["ext"]["attachments"]["files"]
    assert [(e["name"], "removed_at" in e) for e in entries] == [("a.md", True), ("b.pdf", False), ("c.md", False)]


def test_an_agent_removing_from_another_projects_task_needs_cross_project(env, client, tmp_path):
    theirs = task_manager_store(env).add("13", "another project's task", actor="claude", title="theirs")["id"]
    made = client.post(f"{BASE}/boards", json={"slug_name": "theirs", "title": "theirs", "task": {"item_id": theirs}, "summary": "s",
                                               "html": "<!doctype html><p>x</p>", "viewport": 320, "request_review": False})
    slug = made.json()["slug"]
    file_id = _pane_attach(env, tmp_path, slug, cross_project=True)["file_id"]
    before = sidecar(env, slug)
    ok, text = env.call("task_manager_board_attachment_remove", {"board": slug, "file_id": file_id})
    assert not ok and "cross_project" in text and sidecar(env, slug) == before
    ok, answer = env.call("task_manager_board_attachment_remove", {"board": slug, "file_id": file_id, "cross_project": True})
    assert ok and answer["removed_at"], answer


def test_a_tombstone_still_counts_toward_the_index_cap(env, client, board, two, monkeypatch):
    from src.cplugs.reviewboard import attachments  # noqa: PLC0415

    monkeypatch.setattr(attachments, "MAX_ATTACHMENTS", 3)
    assert client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}").status_code == 200
    before = sidecar(env, board["slug"])
    r = client.post(f"{BASE}/boards/{board['slug']}/attachments",
                    json={"files": [{"name": "c.md", "content_base64": b64(MD)}, {"name": "d.md", "content_base64": b64(MD)}]})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "reviewboard_too_large", r.text
    assert sidecar(env, board["slug"]) == before
    assert client.post(f"{BASE}/boards/{board['slug']}/attachments", json={"files": [{"name": "c.md", "content_base64": b64(MD)}]}).status_code == 200


def _bytes_on_disk(env, item_id: int) -> list:
    folder = env.host.storage("huddle").path / "files" / str(item_id)
    return sorted(p.name for p in folder.glob("*")) if folder.is_dir() else []


def _message(env, item_id: int, message_id: int) -> dict:
    return [m for m in task_manager_store(env).item(item_id)["thread"] if m["id"] == message_id][0]


def _other_message_parts(entry: dict) -> dict:
    from src.cplugs.huddle import files as task_manager_files  # noqa: PLC0415

    own = {k: entry[k] for k in ("id", "name", "mime", "size", "path")}
    return {"plain": task_manager_files.parts_of([own]),
            "quote": json.dumps({"quote": {"id": None, "text": "which file?"}, "files": [own]}),
            "freeform": json.dumps({"v": 2, "answers_to": 1, "freeform": True, "files": [own]})}


def test_removing_an_attachment_deletes_its_bytes_and_unlinks_the_thread(env, client, board, two):
    assert len(_bytes_on_disk(env, board["item"])) == 2
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"] == {"deleted": True, "shared": False, "redacted": True, "failed": False, "reason": None}
    left = _bytes_on_disk(env, board["item"])
    assert len(left) == 1 and left[0].startswith(two[1]["file_id"])
    info = _message(env, board["item"], two[0]["message_id"])
    assert [f["name"] for f in info["files"]] == ["b.pdf"] and info["text"].count("was removed]") == 1 and info["text"].endswith("[a.md was removed]")
    assert client.get(f"/api/v1/cplugs/huddle/items/{board['item']}/files/{two[0]['file_id']}").status_code == 404
    assert client.get(f"/api/v1/cplugs/huddle/items/{board['item']}/files/{two[1]['file_id']}").status_code == 200


@pytest.mark.parametrize("shape", ["plain", "quote", "freeform"])
def test_bytes_another_message_still_carries_survive_the_removal(env, client, board, two, shape):
    store = task_manager_store(env)
    entry = _message(env, board["item"], two[0]["message_id"])["files"][0]
    posted = store.post(board["item"], "also this one", actor="joe", kind="reply", parts=_other_message_parts(entry)[shape])["message"]
    other_before = _message(env, board["item"], posted["id"])
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"]["deleted"] is False and r.json()["bytes"]["shared"] is True and r.json()["bytes"]["redacted"] is True
    on_disk = env.host.storage("huddle").path / entry["path"]
    assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == two[0]["sha256"]
    assert _message(env, board["item"], posted["id"]) == other_before, "the other message is untouched"
    board_msg = _message(env, board["item"], two[0]["message_id"])
    assert [f["name"] for f in board_msg["files"]] == ["b.pdf"] and board_msg["text"].count("was removed]") == 1
    assert client.get(f"/api/v1/cplugs/huddle/items/{board['item']}/files/{two[0]['file_id']}").status_code == 200


def test_another_task_recording_the_same_path_keeps_the_bytes(env, client, board, two):
    store = task_manager_store(env)
    from src.cplugs.huddle import files as task_manager_files  # noqa: PLC0415

    entry = _message(env, board["item"], two[0]["message_id"])["files"][0]
    absolute = str((env.host.storage("huddle").path / entry["path"]).resolve())
    other = store.add(store.item(board["item"])["list"], "other task", actor="joe")["id"]
    store.post(other, "imported", actor="joe", parts=task_manager_files.parts_of([{**{k: entry[k] for k in ("id", "name", "mime", "size")}, "path": absolute}]))
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200 and r.json()["bytes"]["shared"] is True and r.json()["bytes"]["deleted"] is False
    assert client.get(f"/api/v1/cplugs/huddle/items/{other}/files/{entry['id']}").status_code == 200


def test_two_removals_from_one_message_both_land(env, client, board, two):
    import threading  # noqa: PLC0415

    store = task_manager_store(env)
    item, mid = board["item"], two[0]["message_id"]
    real = type(store)._next_seq
    fired = []

    def interleave(conn):
        if not fired:
            fired.append(1)
            other = threading.Thread(target=lambda: task_manager_store(env).forget_file(item, mid, two[1]["file_id"]))
            other.start()
            other.join(timeout=0.5)
        return real(conn)

    type(store)._next_seq = staticmethod(interleave)
    try:
        store.forget_file(item, mid, two[0]["file_id"])
    finally:
        type(store)._next_seq = staticmethod(real)
    import time  # noqa: PLC0415

    for _ in range(50):
        if not _message(env, item, mid).get("files"):
            break
        time.sleep(0.1)
    done = _message(env, item, mid)
    assert not done.get("files") and done["text"].count("was removed]") == 2, done


def test_a_file_the_message_never_carried_survives(env, client, board, two):
    from src.cplugs.huddle import files as task_manager_files  # noqa: PLC0415
    from src.cplugs.reviewboard.ports import get as port  # noqa: PLC0415

    saved = task_manager_files.save(env.host.storage("huddle"), board["item"], "owner-paste.png", b"\x89PNG fake")
    record = two[1]
    out = asyncio.run(port().delete_file(board["item"], two[0]["message_id"], saved["id"], name=record["name"], size=record["bytes"], sha256=record["sha256"]))
    assert out["deleted"] is False and out["redacted"] is False and "not the one the board recorded" in out["reason"]
    assert any(n.startswith(saved["id"]) for n in _bytes_on_disk(env, board["item"]))


def test_a_stored_file_that_is_not_the_boards_record_is_kept(env, client, board, two):
    store_path = env.host.storage("huddle").path / "files" / str(board["item"])
    victim = next(store_path.glob(f"{two[0]['file_id']}-*"))
    victim.write_bytes(b"# changed after it was attached\n")
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"]["deleted"] is False and "not the one the board recorded" in r.json()["bytes"]["reason"]
    assert victim.exists() and r.json()["bytes"]["redacted"] is True


def test_files_sharing_an_id_prefix_are_told_apart(env, client, board, two):
    folder = env.host.storage("huddle").path / "files" / str(board["item"])
    decoy = folder / f"{two[0]['file_id']}-A-decoy.md"
    decoy.write_bytes(b"decoy")
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert decoy.exists() and r.json()["bytes"]["deleted"] is False and "not the one the board recorded" in r.json()["bytes"]["reason"]


def test_missing_bytes_still_redact_the_thread(env, client, board, two):
    folder = env.host.storage("huddle").path / "files" / str(board["item"])
    next(folder.glob(f"{two[0]['file_id']}-*")).unlink()
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"]["deleted"] is False and r.json()["bytes"]["redacted"] is True and "already gone" in r.json()["bytes"]["reason"]
    assert [f["name"] for f in _message(env, board["item"], two[0]["message_id"])["files"]] == ["b.pdf"]


def test_a_deleted_task_has_its_own_reason(env, client, board, two):
    task_manager_store(env).delete(board["item"], actor="joe")
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"]["reason"] == "the task was deleted" and r.json()["bytes"]["deleted"] is False


def test_with_the_task_manager_off_nothing_is_half_removed(env, client, board, two):
    board_port.unregister()
    before = sidecar(env, board["slug"])
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_no_task_manager", r.text
    assert sidecar(env, board["slug"]) == before


OTHER = AgentCaller("ses_2", "cloude_b", "ses_2")


def test_the_owner_may_remove_an_agents_attachment(env, client, board, tmp_path):
    entry = _pane_attach(env, tmp_path, board["slug"])
    assert client.delete(f"{BASE}/boards/{board['slug']}/attachments/{entry['file_id']}").status_code == 200


def test_the_attaching_agent_may_remove_its_own_file(env, client, board, tmp_path):
    entry = _pane_attach(env, tmp_path, board["slug"])
    ok, answer = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": entry["file_id"]})
    assert ok and answer["bytes"]["deleted"] is True, answer


def test_another_agent_may_not_remove_it_and_nothing_is_touched(env, client, board, tmp_path):
    entry = _pane_attach(env, tmp_path, board["slug"])
    before, disk = sidecar(env, board["slug"]), _bytes_on_disk(env, board["item"])
    for extra in ({}, {"cross_project": True}):
        ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": entry["file_id"], **extra}, caller=OTHER)
        assert not ok and "reviewboard_not_attacher" in text, text
    assert sidecar(env, board["slug"]) == before and _bytes_on_disk(env, board["item"]) == disk


def test_an_owner_attached_file_is_owners_alone(env, client, board, two):
    before = sidecar(env, board["slug"])
    ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": two[0]["file_id"]})
    assert not ok and "reviewboard_not_attacher" in text and sidecar(env, board["slug"]) == before
    assert "attached_by" not in json.dumps(client.get(f"{BASE}/boards/{board['slug']}/attachments").json()), "the key is never listed back"


def test_a_failed_unlink_answers_503_records_nothing_and_a_retry_deletes(env, client, board, two, monkeypatch):
    from pathlib import Path  # noqa: PLC0415

    real, calls = Path.unlink, []

    def flaky(self, *args, **kwargs):
        calls.append(self)
        if len(calls) == 1:
            raise PermissionError("simulated")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky)
    url = f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}"
    first = client.delete(url)
    assert first.status_code == 503 and first.json()["detail"]["code"] == "reviewboard_bytes_not_removed", first.text
    assert "removed_at" not in sidecar(env, board["slug"])["ext"]["attachments"]["files"][0], "no tombstone while the bytes are stranded"
    second = client.delete(url)
    assert second.status_code == 200 and second.json()["bytes"]["deleted"] is True and second.json()["bytes"]["redacted"] is False, second.text
    assert [n for n in _bytes_on_disk(env, board["item"]) if n.startswith(two[0]["file_id"])] == []
    assert "removed_at" in sidecar(env, board["slug"])["ext"]["attachments"]["files"][0]


def test_a_locked_thread_write_answers_503_and_records_nothing(env, client, board, two, monkeypatch):
    import sqlite3  # noqa: PLC0415

    from src.cplugs.huddle.store import TaskManagerStore  # noqa: PLC0415

    real = TaskManagerStore.forget_file

    def locked(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(TaskManagerStore, "forget_file", locked)
    url = f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}"
    before, disk = sidecar(env, board["slug"]), _bytes_on_disk(env, board["item"])
    r = client.delete(url)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "reviewboard_bytes_not_removed", r.text
    assert sidecar(env, board["slug"]) == before and _bytes_on_disk(env, board["item"]) == disk
    monkeypatch.setattr(TaskManagerStore, "forget_file", real)
    assert client.delete(url).status_code == 200


def test_a_crash_after_the_file_step_is_finished_by_the_retry(env, client, board, two):
    from src.cplugs.reviewboard.ports import get as port  # noqa: PLC0415

    done = asyncio.run(port().delete_file(board["item"], two[0]["message_id"], two[0]["file_id"], name=two[0]["name"], size=two[0]["bytes"], sha256=two[0]["sha256"]))
    assert done["deleted"] is True
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200 and r.json()["bytes"]["failed"] is False and "removed_at" in sidecar(env, board["slug"])["ext"]["attachments"]["files"][0]


ROWS = {"ses_1": (101, "uuid-one"), "ses_2": (102, "uuid-two"), "ses_9": (101, "uuid-one")}


def _two_agents_in_project_12(env, monkeypatch, live: list) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from src.cplugs.host import capabilities  # noqa: PLC0415

    async def infos() -> list:
        return [SimpleNamespace(tmux_session=None, label=None, session=SimpleNamespace(id=sid), project_id=12, host_key="local",
                                session_row_id=ROWS[sid][0]) for sid in live]

    monkeypatch.setattr(capabilities, "session_uuids", lambda row_ids: {rid: uuid for rid, uuid in (ROWS[s] for s in ROWS) if rid in row_ids})
    board_port.unregister()
    task_manager_on(env, monkeypatch, infos=infos)


def test_two_agents_in_one_project_only_the_attacher_removes_and_a_rebind_keeps_the_right(env, client, board, tmp_path, monkeypatch):
    one, two_ = AgentCaller("ses_1", "cloude_a", "ses_1"), AgentCaller("ses_2", "cloude_b", "ses_2")
    _two_agents_in_project_12(env, monkeypatch, ["ses_1", "ses_2"])

    def attach(caller: AgentCaller, name: str) -> dict:
        path = tmp_path / name
        path.write_bytes(MD + name.encode())
        ok, answer = env.call("task_manager_board_attachment_add", {"board": board["slug"], "file_paths": [str(path)], "request_review": False}, caller=caller)
        assert ok, answer
        return answer["attachments"][0]

    own = attach(two_, "two.md")
    ok, answer = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": own["file_id"]}, caller=two_)
    assert ok, answer
    theirs = attach(one, "one.md")
    before, disk = sidecar(env, board["slug"]), _bytes_on_disk(env, board["item"])
    ok, text = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": theirs["file_id"]}, caller=two_)
    assert not ok and "reviewboard_not_attacher" in text, text
    assert sidecar(env, board["slug"]) == before and _bytes_on_disk(env, board["item"]) == disk
    _two_agents_in_project_12(env, monkeypatch, ["ses_9", "ses_2"])
    ok, answer = env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": theirs["file_id"]},
                          caller=AgentCaller("ses_1", "cloude_a", "ses_9"))
    assert ok and answer["bytes"]["deleted"] is True, answer


def test_a_file_unlinked_by_a_concurrent_removal_is_not_a_failure(env, client, board, two, monkeypatch):
    from pathlib import Path  # noqa: PLC0415

    real = Path.unlink

    def raced(self, *args, **kwargs):
        real(self)
        raise FileNotFoundError(2, "No such file or directory", str(self))

    monkeypatch.setattr(Path, "unlink", raced)
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["bytes"]["failed"] is False and "already gone" in r.json()["bytes"]["reason"]
    assert "removed_at" in sidecar(env, board["slug"])["ext"]["attachments"]["files"][0]
