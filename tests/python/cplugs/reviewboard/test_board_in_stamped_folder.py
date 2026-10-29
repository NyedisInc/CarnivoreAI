
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle import task_files
from src.cplugs.sdk import ports, task_folders
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_store
from tests.python.cplugs.reviewboard.test_attachments import HTML, client, env  # noqa: F401

HUDDLE = "/api/v1/cplugs/huddle"


class OwnRoot:

    def __init__(self, folder: Path):
        self.folder = folder

    def root(self) -> Path:
        return self.folder


@pytest.fixture(autouse=True)
def root_port(env):
    ports.register(task_folders.ROOT_PORT, OwnRoot(env.root))
    yield
    ports.unregister(task_folders.ROOT_PORT)


def paste_into(client, item: int) -> Path:
    uploaded = client.post(f"{HUDDLE}/items/{item}/files", files={"file": ("shot.txt", b"hello", "text/plain")})
    assert uploaded.status_code == 200, uploaded.text
    sent = client.post(f"{HUDDLE}/items/{item}/messages", json={"files": [uploaded.json()["id"]]})
    assert sent.status_code == 200, sent.text
    return Path(sent.json()["message"]["files"][0]["path"]).parent.parent


def publish(client, item: int, name: str = "bottom-bar") -> str:
    r = client.post(f"{BASE}/boards", json={"slug_name": name, "title": name, "task": {"item_id": item}, "summary": "first", "html": HTML,
                                            "viewport": 320, "request_review": False})
    assert r.status_code == 200, r.text
    return r.json()["slug"]


def test_a_board_goes_beside_the_pastes_in_the_stamped_task_folder(env, client):
    item = task_manager_store(env).add("12", "redo the bottom bar", actor="claude", title="bottom bar task")["id"]
    folder = paste_into(client, item)
    assert task_folders.task_store_of(folder) is not None
    slug = publish(client, item)
    assert env.board(slug).parent.parent == folder
    assert len(task_folders.tasks_for(env.root, item)) == 1


def test_a_board_made_first_is_found_by_the_pastes_that_follow(env, client):
    item = task_manager_store(env).add("12", "boards first", actor="claude", title="boards first")["id"]
    slug = publish(client, item)
    folder = paste_into(client, item)
    assert env.board(slug).parent.parent == folder and len(task_folders.tasks_for(env.root, item)) == 1


def test_a_task_whose_store_id_cannot_be_read_gets_its_board_in_an_unstamped_folder(env, client, monkeypatch):
    item = task_manager_store(env).add("12", "no id", actor="claude", title="no id")["id"]
    folder = paste_into(client, item)
    monkeypatch.setattr(task_files, "own_store_id", lambda ctx: None)
    slug = publish(client, item)
    placed = env.board(slug).parent.parent
    assert placed != folder and task_folders.task_store_of(placed) is None
