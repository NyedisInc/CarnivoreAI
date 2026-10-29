
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port
from src.cplugs.reviewboard import relink_port
from src.cplugs.sdk import ports
from src.cplugs.sdk import crate_import as sdk_import
from src.cplugs.sdk.computer import local_computer
from tests.python.cplugs.reviewboard.harness import BASE, Env, task_manager_on, task_manager_store, make_env
from tests.python.cplugs.reviewboard.test_publish import create_body


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    env = make_env(tmp_path)
    task_manager_on(env, monkeypatch)
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as client:
        relink_port.register(env.host.context("reviewboard", background=True))
        yield env, client
        relink_port.unregister()
    board_port.unregister()


def sidecar_of(env: Env, slug: str) -> dict:
    return json.loads((env.board(slug) / "sidecar.json").read_text())


def test_the_sdk_asks_for_the_name_the_board_registers() -> None:
    assert sdk_import.RELINK_PORT == relink_port.NAME


def test_the_import_env_relinks_a_board_through_the_boards_own_writer(world) -> None:
    env, client = world
    old = task_manager_store(env).add("all", "the task the crate had", actor="claude", title="Old")["id"]
    slug = client.post(f"{BASE}/boards", json=create_body(old)).json()["slug"]
    restored = task_manager_store(env).add("all", "the restored task", actor="claude", title="Restored")["id"]
    relink_board = sdk_import.relink_board_of()
    assert relink_board(slug, restored) is True
    task = sidecar_of(env, slug)["task"]
    assert task["item_id"] == restored and task["computer"] == local_computer()
    assert task["history"][-1]["from"] == old and task["history"][-1]["item_id"] == restored
    assert relink_board(slug, restored) is True


def test_a_task_this_computer_does_not_have_is_not_a_relink(world) -> None:
    env, client = world
    old = task_manager_store(env).add("all", "t", actor="claude", title="Old")["id"]
    slug = client.post(f"{BASE}/boards", json=create_body(old)).json()["slug"]
    assert sdk_import.relink_board_of()(slug, 99999) is False
    assert sidecar_of(env, slug)["task"]["item_id"] == old
    assert sdk_import.relink_board_of()("no-such-board", old) is False


def test_with_the_board_plugin_off_the_hook_answers_false() -> None:
    assert ports.get(sdk_import.RELINK_PORT) is None
    assert sdk_import.relink_board_of()("any", 1) is False
