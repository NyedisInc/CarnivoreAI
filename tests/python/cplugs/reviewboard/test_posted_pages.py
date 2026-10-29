
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.core.browser_pages import open_pages, page_tab
from src.core import row_looks
from src.cplugs.huddle import artifact_port as huddle_artifact_port, artifact_post, board_port
from src.cplugs.reviewboard import artifact_port, migrate, scan, service
from tests.python.cplugs.reviewboard.harness import Env, huddle_on, huddle_store, make_env

PAGE = "<!doctype html><title>x</title><h1>hello</h1>"


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    open_pages.reset_for_test()
    made = make_env(tmp_path)
    made.huddle_ctx = huddle_on(made, monkeypatch)
    made.board_ctx = made.host.context("reviewboard")
    yield made
    board_port.unregister()
    artifact_port.unregister()
    huddle_artifact_port.unregister()
    open_pages.reset_for_test()


@pytest.fixture
def item(env: Env) -> int:
    return huddle_store(env).add("all", "show the layouts", actor="claude", title="Layouts")["id"]


def post(env: Env, item_id: int, title: str = "Layout A", html: str = PAGE, **over):
    return env.call("task_manager_artifact_add", {"item": item_id, "title": title, "description": "two columns", "html": html, **over})


def board_rows(env: Env) -> list:
    return service.boards(env.root)["boards"]


def thread(env: Env, item_id: int) -> list:
    return [m for m in huddle_store(env).item(item_id)["thread"] if m.get("category") != "status"]



def test_a_posted_page_becomes_a_one_page_board_on_the_task(env, item):
    artifact_port.register(env.board_ctx)
    ok, answer = post(env, item)
    assert ok, answer
    assert answer["title"] == "Layout A" and answer["size"] == len(PAGE.encode()) and answer["revision"] == "r1" and answer["board"].endswith("-layout-a")
    assert isinstance(answer["message_id"], int) and answer["item_id"] == item
    rows = board_rows(env)
    assert [(r["slug"], r["title"], r["revisions"], r["task"]["item_id"]) for r in rows] == [(answer["board"], "Layout A", 1, item)]
    sidecar = service.board(env.root, answer["board"])["sidecar"]
    revision = sidecar["revisions"][0]
    assert revision["prompts"] == [] and not revision.get("payload_mode") and revision["summary"] == "two columns"
    assert (env.board(answer["board"]) / "r001.html").read_text() == PAGE
    assert scan.scan(env.root).findings == ()
    cards = thread(env, item)
    assert [m.get("artifact") for m in cards] == [None] * len(cards) and cards[-1]["board"]["slug"] == answer["board"]
    assert huddle_store(env).item(item)["state"] == "open"


def test_the_same_title_on_the_same_task_adds_a_revision(env, item):
    artifact_port.register(env.board_ctx)
    first = post(env, item, "Layout A")[1]
    again = post(env, item, "  layout   a ", PAGE + "2")[1]
    assert again["board"] == first["board"] and again["revision"] == "r2"
    other = post(env, item, "Layout B")[1]
    assert other["board"] != first["board"] and other["revision"] == "r1"
    assert [r["revisions"] for r in sorted(board_rows(env), key=lambda r: r["title"])] == [2, 1]
    elsewhere = huddle_store(env).add("all", "another", actor="claude")["id"]
    assert post(env, elsewhere, "Layout A")[1]["board"] not in (first["board"], other["board"])


def test_board_off_or_unset_keeps_the_old_artifact_path(env, item):
    ok, answer = post(env, item)
    assert ok and "board" not in answer and "revision" not in answer
    assert thread(env, item)[-1]["artifact"]["title"] == "Layout A" and board_rows(env) == []
    artifact_port.register(env.board_ctx)
    env.set_root(None)
    ok, answer = post(env, item, "Layout B")
    assert ok and "board" not in answer and thread(env, item)[-1]["artifact"]["title"] == "Layout B"


def test_a_refused_page_is_refused_by_the_same_limits(env, item):
    artifact_port.register(env.board_ctx)
    ok, text = post(env, item, html="x" * (2 * 1024 * 1024 + 1))
    assert not ok and "limit" in text
    ok, text = post(env, item, title="   ")
    assert not ok and "title" in text



def seed(env: Env, item: int) -> None:
    for title, html in (("Layout A", PAGE + "1"), ("layout a", PAGE + "2"), ("Layout B", PAGE + "3")):
        artifact_post.post(env.huddle_ctx, item, title, "d", html)


def test_the_copy_makes_a_board_per_title_with_a_revision_per_version_and_posts_nothing(env, item):
    seed(env, item)
    before = [m["id"] for m in thread(env, item)]
    huddle_artifact_port.register(env.huddle_ctx)
    done = asyncio.run(migrate.run(env.board_ctx))
    assert done == {"boards": 2, "revisions": 3, "rows_moved": 0}
    rows = {r["title"]: r for r in board_rows(env)}
    assert rows["Layout A"]["revisions"] == 2 and rows["Layout B"]["revisions"] == 1
    a = service.board(env.root, rows["Layout A"]["slug"])["sidecar"]
    assert [r["summary"] for r in a["revisions"]] == ["d", "d"]
    assert [(env.board(rows["Layout A"]["slug"]) / f"r00{n}.html").read_text() for n in (1, 2)] == [PAGE + "1", PAGE + "2"]
    assert [m["id"] for m in thread(env, item)] == before
    assert (env.root / migrate.MARKER_FILE).exists() and scan.scan(env.root).findings == ()


def test_the_copy_runs_once(env, item):
    seed(env, item)
    huddle_artifact_port.register(env.huddle_ctx)
    assert asyncio.run(migrate.run(env.board_ctx)) is not None
    snapshot = {str(p): p.read_bytes() for p in sorted(env.root.rglob("*")) if p.is_file()}
    assert asyncio.run(migrate.run(env.board_ctx)) is None
    assert {str(p): p.read_bytes() for p in sorted(env.root.rglob("*")) if p.is_file()} == snapshot


def test_the_copy_waits_without_a_boards_folder_or_the_huddle(env, item):
    seed(env, item)
    assert asyncio.run(migrate.run(env.board_ctx)) is None
    huddle_artifact_port.register(env.huddle_ctx)
    env.set_root(None)
    assert asyncio.run(migrate.run(env.board_ctx)) is None and board_rows(env) == []
    env.set_root(env.root)
    assert asyncio.run(migrate.run(env.board_ctx))["boards"] == 2


def test_the_copy_replaces_an_open_artifact_row_with_the_board_row_and_keeps_its_look(env, item):
    message = artifact_post.post(env.huddle_ctx, item, "Layout A", "d", PAGE)["message"]["artifact"]
    page = page_tab.artifact_page("/api/v1/cplugs/huddle/artifact-view/t", item, message["id"])
    row = open_pages.open_page(page["key"], page["frame"], "Layout A", ref={"item": item, "artifact": message["id"]}, src=None)
    row_looks.apply_on_open(row.id, "green", "star")
    huddle_artifact_port.register(env.huddle_ctx)
    assert asyncio.run(migrate.run(env.board_ctx))["rows_moved"] == 1
    listed = open_pages.listing()
    assert [p.key for p in listed if p.key.startswith("huddle_artifact:")] == [] and open_pages.get(row.id) is None
    (moved,) = listed
    assert moved.key.startswith("app:/static/popout.html?tab=reviewboard&board=") and moved.title == "Layout A"
    held = row_looks.listing()[moved.id]
    assert (held.color, held.icon) == ("green", "star") and row.id not in row_looks.listing()


def test_the_marker_is_not_a_board(env, item):
    seed(env, item)
    huddle_artifact_port.register(env.huddle_ctx)
    asyncio.run(migrate.run(env.board_ctx))
    assert json.loads((env.root / migrate.MARKER_FILE).read_text())["boards"] == 2
    assert all(not r["slug"].startswith(".") for r in board_rows(env))
