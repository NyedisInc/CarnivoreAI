
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import runtime
from src.cplugs.huddle import files, routes as huddle_routes, service, task_files
from src.cplugs.huddle.store import TaskManagerStore
from src.config.uploads import UploadsConfig
from src.cplugs.huddle import routes_artifacts  # noqa: F401
from src.cplugs.sdk import ports, signed_links, task_folders, uploads as sdk_uploads
from tests.python.cplugs.owner import turn_on

BASE = "/api/v1/cplugs/huddle"
PAGE = "<!doctype html><title>a</title><p>page</p>"


@pytest.fixture(autouse=True)
def no_config(monkeypatch):
    monkeypatch.setattr(sdk_uploads, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(uploads=UploadsConfig())))
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


@pytest.fixture
def app(tmp_path: Path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "Carnivore"})
    app = FastAPI()
    app.include_router(huddle_routes.router, prefix="/api/v1")
    host = runtime.install(app, tmp_path / "state")
    host.publish = lambda topic: None
    turn_on(host)
    return app


@pytest.fixture
def client(app: FastAPI):
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        yield test_client


class FakeRoot:

    def __init__(self, value):
        self.value = value

    def root(self):
        return self.value


@pytest.fixture
def root(tmp_path: Path):
    folder = tmp_path / "tm"
    folder.mkdir()
    port = FakeRoot(folder)
    ports.register(task_files.ROOT_PORT, port)
    yield folder
    ports.unregister(task_files.ROOT_PORT)


def plugin_folder(app: FastAPI) -> Path:
    return runtime.host_for(app).storage("huddle").path


def add(client, list_key: str, title: str) -> int:
    r = client.post(f"{BASE}/lists/{list_key}/items", json={"text": "look", "title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def paste(client, item_id: int, name: str = "shot.txt", data: bytes = b"hello") -> dict:
    r = client.post(f"{BASE}/items/{item_id}/files", files={"file": (name, data, "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def reply(client, item_id: int, ids: list) -> dict:
    r = client.post(f"{BASE}/items/{item_id}/messages", json={"files": ids})
    assert r.status_code == 200, r.text
    return r.json()["message"]


def stored_parts(app: FastAPI, message_id: int) -> dict:
    with runtime.host_for(app).storage("huddle").connect(False) as conn:
        return json.loads(conn.execute("SELECT parts FROM work_messages WHERE id = ?", (message_id,)).fetchone()["parts"])


def test_with_no_folder_everything_is_as_before(client, app):
    item = add(client, "12", "no root")
    f = paste(client, item)
    message = reply(client, item, [f["id"]])
    path = stored_parts(app, message["id"])["files"][0]["path"]
    assert path == f"files/{item}/{f['id']}-shot.txt"
    assert (plugin_folder(app) / path).read_bytes() == b"hello"
    assert client.get(f"{BASE}/items/{item}/files/{f['id']}").content == b"hello"


def test_a_refused_folder_is_the_same_as_none(client, app):
    ports.register(task_files.ROOT_PORT, FakeRoot(None))
    try:
        item = add(client, "12", "refused")
        f = paste(client, item)
        message = reply(client, item, [f["id"]])
        assert stored_parts(app, message["id"])["files"][0]["path"] == f"files/{item}/{f['id']}-shot.txt"
    finally:
        ports.unregister(task_files.ROOT_PORT)


def test_an_attached_paste_moves_into_the_task_pastes_folder(client, app, root):
    item = add(client, "12", "Watch what Alex changed")
    f = paste(client, item)
    staged = plugin_folder(app) / "files" / str(item) / f"{f['id']}-shot.txt"
    assert staged.exists() and not any(root.iterdir())
    message = reply(client, item, [f["id"]])
    target = root / "carnivore-12" / f"watch-what-alex-changed-{item}" / "pastes" / f"{f['id']}-shot.txt"
    assert target.read_bytes() == b"hello" and not staged.exists()
    assert stored_parts(app, message["id"])["files"][0]["path"] == str(target)
    assert files.for_agent(plugin_folder(app), message["files"])[0]["path"] == str(target.resolve())
    assert client.get(f"{BASE}/items/{item}/files/{f['id']}").content == b"hello"


def test_a_personal_item_goes_under_no_project(client, root):
    item = add(client, "all", "groceries")
    f = paste(client, item)
    reply(client, item, [f["id"]])
    assert (root / "no-project" / f"groceries-{item}" / "pastes" / f"{f['id']}-shot.txt").exists()


def test_a_file_is_still_served_after_the_setting_changes(client, app, root, tmp_path):
    item = add(client, "12", "moved root")
    f = paste(client, item)
    reply(client, item, [f["id"]])
    ports.register(task_files.ROOT_PORT, FakeRoot(None))
    assert client.get(f"{BASE}/items/{item}/files/{f['id']}").content == b"hello"
    other = tmp_path / "other"
    other.mkdir()
    ports.register(task_files.ROOT_PORT, FakeRoot(other))
    assert client.get(f"{BASE}/items/{item}/files/{f['id']}").content == b"hello"


def test_a_file_an_earlier_message_names_is_not_moved(client, app, root):
    ports.register(task_files.ROOT_PORT, FakeRoot(None))
    item = add(client, "12", "twice")
    f = paste(client, item)
    first = reply(client, item, [f["id"]])
    ports.register(task_files.ROOT_PORT, FakeRoot(root))
    second = reply(client, item, [f["id"]])
    legacy = f"files/{item}/{f['id']}-shot.txt"
    assert stored_parts(app, first["id"])["files"][0]["path"] == stored_parts(app, second["id"])["files"][0]["path"] == legacy
    assert (plugin_folder(app) / legacy).exists()


def test_a_retry_after_a_failed_post_finds_the_moved_file(client, app, root, monkeypatch):
    item = add(client, "12", "retry")
    f = paste(client, item)
    real_post = TaskManagerStore.post
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return real_post(self, *args, **kwargs)

    monkeypatch.setattr(TaskManagerStore, "post", flaky)
    failed = client.post(f"{BASE}/items/{item}/messages", json={"files": [f["id"]]})
    assert failed.status_code >= 500 and calls["n"] == 1
    message = reply(client, item, [f["id"]])
    assert stored_parts(app, message["id"])["files"][0]["path"].startswith(str(root))


def test_an_artifact_is_written_to_the_task_artifacts_folder_and_served(client, app, root):
    item = add(client, "12", "Layout A")
    r = client.post(f"{BASE}/items/{item}/artifacts", json={"title": "Layout A", "html": PAGE})
    assert r.status_code == 200, r.text
    message = r.json()["message"]
    folder = root / "carnivore-12" / f"layout-a-{item}" / "artifacts"
    pages = list(folder.glob("*-artifact.html"))
    assert len(pages) == 1 and pages[0].read_text() == PAGE
    assert stored_parts(app, message["id"])["files"][0]["path"] == str(pages[0])
    url = client.post(f"{BASE}/items/{item}/artifacts/{message['artifact']['id']}/ticket").json()["url"]
    assert client.get(url).text == PAGE


def marker_store(folder: Path):
    return task_folders.task_store_of(folder)


def store_id_of(app: FastAPI):
    from src.cplugs.huddle import store_identity

    with runtime.host_for(app).storage("huddle").connect(False) as conn:
        return store_identity.read(conn)


def test_a_new_task_folder_carries_this_stores_id_and_a_legacy_one_stays_unmarked(client, app, root):
    item = add(client, "12", "Marked")
    reply(client, item, [paste(client, item)["id"]])
    folder = next(root.glob(f"*/*-{item}"))
    mine = store_id_of(app)
    assert mine and marker_store(folder) == mine
    marker = folder / task_folders.TASK_MARKER
    legacy = json.loads(marker.read_text())
    del legacy["store"]
    marker.write_text(json.dumps(legacy))
    reply(client, item, [paste(client, item)["id"]])
    assert marker_store(folder) is None and len(list(root.glob(f"*/*-{item}*"))) == 1


def test_a_folder_stamped_by_another_store_is_never_written_into(client, app, root):
    item = add(client, "12", "Shared")
    reply(client, item, [paste(client, item)["id"]])
    first = next(root.glob(f"*/*-{item}"))
    marker = first / task_folders.TASK_MARKER
    foreign = json.loads(marker.read_text())
    foreign["store"] = "0f0f0f0f0f0f0f0f"
    marker.write_text(json.dumps(foreign))
    message = reply(client, item, [paste(client, item, "second.txt")["id"]])
    own = Path(stored_parts(app, message["id"])["files"][0]["path"]).parent.parent
    assert own != first and marker_store(own) == store_id_of(app) and marker_store(first) == "0f0f0f0f0f0f0f0f"
    reply(client, item, [paste(client, item, "third.txt")["id"]])
    assert len(list(own.glob("pastes/*-third.txt"))) == 1


def test_the_store_id_is_read_before_it_is_written(client, app, root, monkeypatch):
    from src.cplugs.huddle import store_identity

    item = add(client, "12", "Once")
    reply(client, item, [paste(client, item)["id"]])
    calls = []
    real = store_identity.ensure
    monkeypatch.setattr(store_identity, "ensure", lambda conn: calls.append(1) or real(conn))
    reply(client, item, [paste(client, item, "again.txt")["id"]])
    assert calls == []


def test_a_store_id_that_cannot_be_made_does_not_fail_the_reply_and_the_file_stays_in_the_plugin_folder(client, app, root, monkeypatch):
    import sqlite3

    from src.cplugs.huddle import store_identity

    def broken(conn):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store_identity, "ensure", broken)
    monkeypatch.setattr(store_identity, "read", lambda conn: None)
    item = add(client, "12", "Locked")
    message = reply(client, item, [paste(client, item)["id"]])
    path = stored_parts(app, message["id"])["files"][0]["path"]
    assert path == f"files/{item}/{path.rsplit('/', 1)[1]}" and not any(root.iterdir())
