
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard import layout, root_port, scan
from src.cplugs.sdk import task_folders
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board, sidecar
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env

HTML = "<!doctype html><title>bar</title><p>hi</p>"


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    made = make_env(tmp_path)
    task_manager_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def body(item_id: int, name: str = "bottom-bar") -> dict:
    return {"slug_name": name, "title": "bottom bar", "task": {"item_id": item_id}, "summary": "first pass", "html": HTML, "viewport": 320}


def create(client, item_id: int, name: str = "bottom-bar") -> dict:
    r = client.post(f"{BASE}/boards", json=body(item_id, name))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_new_board_is_filed_under_its_project_and_task(env: Env, client):
    item = task_manager_store(env).add("12", "redo the bar", actor="claude", title="Part 3: bottom bar!")["id"]
    answer = create(client, item)
    expected = env.root / "carnivore-12" / f"part-3-bottom-bar-{item}" / "boards" / answer["slug"]
    assert answer["revision_dir"] == str(expected) and (expected / "r001.html").read_text() == HTML
    assert task_folders.read_marker(expected.parent.parent, task_folders.TASK_MARKER)["item_id"] == item
    assert task_folders.read_marker(env.root / "carnivore-12", task_folders.PROJECT_MARKER)["list"] == "12"
    listed = client.get(f"{BASE}/boards").json()
    assert [b["slug"] for b in listed["boards"]] == [answer["slug"]] and listed["clean"] is True, listed["problems"]
    got = client.get(f"{BASE}/boards/{answer['slug']}").json()
    assert got["revision_dir"] == str(expected) and got["status"] == "ok"
    revised = client.post(f"{BASE}/boards/{answer['slug']}/revisions", json={"summary": "second", "html": HTML + "2", "viewport": 320})
    assert revised.status_code == 200, revised.text
    assert (expected / "r002.html").read_text() == HTML + "2"


def test_an_item_on_no_project_list_goes_under_no_project(env: Env, client):
    item = task_manager_store(env).add("all", "a personal thing", actor="claude", title="personal")["id"]
    answer = create(client, item)
    assert Path(answer["revision_dir"]).parent.parent == env.root / "no-project" / f"personal-{item}"


def test_a_renamed_task_keeps_its_first_folder(env: Env, client):
    store = task_manager_store(env)
    item = store.add("12", "redo the bar", actor="claude", title="first name")["id"]
    first = Path(create(client, item, "one")["revision_dir"]).parent.parent
    store.update(item, actor="claude", title="a completely different name")
    second = Path(create(client, item, "two")["revision_dir"]).parent.parent
    assert first == second == env.root / "carnivore-12" / f"first-name-{item}"


def test_a_flat_board_made_before_keeps_working_beside_nested_ones(env: Env, client):
    flat = make_board(env.root)
    item = task_manager_store(env).add("12", "redo the bar", actor="claude", title="bar")["id"]
    nested = create(client, item, "other-bar")["slug"]
    result = scan.scan(env.root)
    assert result.exit_code == 0 and not [f for f in result.findings if f.code == "unknown_entry"], result.findings
    assert sorted(r.slug for r in result.boards) == sorted([flat.name, nested])
    assert layout.board_dir(env.root, flat.name) == flat
    assert client.get(f"{BASE}/boards/{flat.name}").json()["revision_dir"] == str(flat)
    assert client.get(f"{BASE}/boards/{flat.name}").json()["status"] == "ok"


def test_a_slug_is_one_board_across_the_folder(env: Env, client):
    item = task_manager_store(env).add("12", "redo the bar", actor="claude", title="bar")["id"]
    slug = create(client, item)["slug"]
    again = client.post(f"{BASE}/boards", json=body(item))
    assert again.status_code == 409
    nested = layout.board_dir(env.root, slug)
    copy = make_board(env.root, sidecar(board={**SIDECAR["board"], "slug": slug}))
    found = scan.scan(env.root)
    assert any(f.code == "duplicate_slug" and f.level == "error" for f in found.findings), found.findings
    assert copy.exists() and nested.exists()


def test_a_project_folder_without_a_marker_is_not_walked_and_a_symlinked_task_is_refused(env: Env, tmp_path: Path):
    stray = env.root / "notes-12"
    stray.mkdir()
    findings = scan.scan(env.root).findings
    assert any(f.code == "bad_folder" and f.board == "notes-12" for f in findings)
    project = task_folders.ensure_project(env.root, "12", "carnivore")
    outside = tmp_path / "outside-7"
    (outside / "boards" / "20261013-x").mkdir(parents=True)
    (outside / task_folders.TASK_MARKER).write_text(json.dumps({"item_id": 7}))
    (project / "outside-7").symlink_to(outside)
    assert task_folders.find_task(env.root, 7) is None and layout.board_dir(env.root, "20261013-x") is None


def test_the_root_port_answers_the_checked_folder_or_none(env: Env):
    port = root_port.RootPort(env.host.context("reviewboard"))
    assert port.root() == env.root
    env.set_root("relative/path")
    assert port.root() is None
    env.set_root(None)
    assert port.root() is None
