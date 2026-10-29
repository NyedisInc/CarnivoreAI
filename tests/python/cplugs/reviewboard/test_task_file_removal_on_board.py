
from __future__ import annotations

import pytest

from src.cplugs.reviewboard import attachments_port
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_store
from tests.python.cplugs.reviewboard.test_attachment_removal import _pane_attach, two  # noqa: F401
from tests.python.cplugs.reviewboard.test_attachments import board, client, env, sidecar  # noqa: F401

TM = "/api/v1/cplugs/huddle"


@pytest.fixture(autouse=True)
def board_lists_files(env):
    attachments_port.register(env.host.context("reviewboard"))
    yield
    attachments_port.unregister()


def test_the_owner_and_an_agent_are_refused_a_file_a_board_lists(env, client, board, two):
    item, victim = board["item"], two[0]["file_id"]
    before = sidecar(env, board["slug"])
    r = client.delete(f"{TM}/items/{item}/files/{victim}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_manager_file_on_board"
    assert "task_manager_board_attachment_remove" in r.json()["detail"]["detail"]
    assert sidecar(env, board["slug"]) == before
    assert client.get(f"{TM}/items/{item}/files/{victim}").status_code == 200, "the bytes and the paperclip link are intact"


def test_the_agent_that_attached_it_through_the_board_is_refused_too(env, client, board, tmp_path):
    entry = _pane_attach(env, tmp_path, board["slug"])
    before = sidecar(env, board["slug"])
    ok, text = env.call("task_manager_file_remove", {"item": board["item"], "file_id": entry["file_id"]})
    assert not ok and "task_manager_file_on_board" in text
    assert sidecar(env, board["slug"]) == before and client.get(f"{TM}/items/{board['item']}/files/{entry['file_id']}").status_code == 200
    assert env.call("task_manager_board_attachment_remove", {"board": board["slug"], "file_id": entry["file_id"]})[0], "the board's own remove still works"


def test_after_the_board_removes_it_the_file_is_gone_and_a_loose_file_is_still_deletable(env, client, board, two):
    item = board["item"]
    assert client.delete(f"{BASE}/boards/{board['slug']}/attachments/{two[0]['file_id']}").status_code == 200
    assert client.get(f"{TM}/items/{item}/files/{two[0]['file_id']}").status_code == 404
    r = client.delete(f"{TM}/items/{item}/files/{two[1]['file_id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "task_manager_file_on_board", "the second one is still listed"


def test_the_two_port_names_agree():
    from src.cplugs.reviewboard import attachments_port  # noqa: PLC0415
    from src.cplugs.sdk import board_files  # noqa: PLC0415

    assert attachments_port.NAME == board_files.PORT


def test_a_board_deleted_mid_scan_is_skipped_not_a_refusal(env, client, board, two, monkeypatch):
    from src.cplugs.reviewboard import service  # noqa: PLC0415

    real = service.boards
    monkeypatch.setattr(service, "boards", lambda root, task=None: {**real(root, task), "boards": [{"slug": "20261014-vanished"}, *real(root, task)["boards"]]})
    item = board["item"]
    assert client.delete(f"{TM}/items/{item}/files/{two[0]['file_id']}").json()["detail"]["code"] == "task_manager_file_on_board"
    loose = client.post(f"{TM}/items/{item}/files", files={"file": ("loose.txt", b"x", "text/plain")}).json()
    assert client.delete(f"{TM}/items/{item}/files/{loose['id']}").status_code == 200
