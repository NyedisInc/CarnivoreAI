
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.huddle import board_port, wire as huddle_wire
from src.cplugs.reviewboard import document, publish, revisions, scan, store
from src.cplugs.reviewboard.errors import BadRequest
from src.cplugs.reviewboard.requests import ReviseBody
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.reviewboard.boards import PAGE, SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import BASE, OWN_PROJECT, Env, huddle_on, huddle_store, make_env

HTML = "<!doctype html><title>bar</title><div data-rb-anchor='send'>send</div><script>1</script>"
PROMPTS = [{"id": "layout", "kind": "choice", "label": "which button row", "options": [{"id": "a", "label": "one row"}, {"id": "b", "label": "two rows"}], "anchor": "buttons"},
           {"id": "padding", "kind": "check", "label": "padding looks right"}]
ANCHORS = [{"id": "send", "label": "send button"}, {"id": "buttons", "label": "button row"}]


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Env:
    made = make_env(tmp_path)
    huddle_on(made, monkeypatch)
    yield made
    board_port.unregister()


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


@pytest.fixture
def item(env: Env) -> int:
    return huddle_store(env).add("all", "redo the bottom bar", actor="claude", title="Part 3 bottom bar")["id"]


def create_body(item_id: int, **over):
    return {"slug_name": "bottom-bar", "title": "bottom bar", "task": {"item_id": item_id}, "summary": "first pass: icons only",
            "html": HTML, "viewport": 320, "prompts": PROMPTS, "anchors": ANCHORS, **over}


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def thread(env: Env, item_id: int) -> list:
    return [m for m in huddle_store(env).item(item_id)["thread"] if m.get("category") != "status"]


def made(client, item_id: int, **over):
    r = client.post(f"{BASE}/boards", json=create_body(item_id, **over))
    assert r.status_code == 200, r.text
    return r.json()



def test_create_writes_the_board_and_posts_the_card_and_asks_for_review(env: Env, client, item):
    answer = made(client, item)
    slug = answer["slug"]
    assert slug.endswith("-bottom-bar") and answer["revision"] == "r1" and answer["state"] == "your_turn"
    folder = env.board(slug)
    assert (folder / "r001.html").read_text() == HTML and answer["revision_dir"] == str(folder)
    result = scan.scan(env.root)
    assert result.exit_code == 0 and result.findings == (), result.findings
    sidecar = json.loads((folder / "sidecar.json").read_text())
    assert sidecar["task"]["item_id"] == item and sidecar["task"]["title_at_link"] == "Part 3 bottom bar" and sidecar["task"]["list"] == "all"
    assert sidecar["revisions"][0]["views"][0]["bytes"] == len(HTML.encode()) and sidecar["rounds"] == []
    assert document.etag((folder / "sidecar.json").read_bytes()) == answer["etag"]
    card = thread(env, item)[-1]
    assert card["author"] == "claude" and card["kind"] == "info" and card["text"] == "bottom bar r1: first pass: icons only"
    assert card["board"] == {"slug": slug, "revision": "r1", "title": "bottom bar", "summary": "first pass: icons only"}
    assert answer["card"]["posted"] is True and answer["card"]["review"] == {"requested": True, "moved": True, "reason": None}
    row = huddle_store(env).item(item)
    assert row["state"] == "review" and row["status"] == "review"
    assert row["review_summary"] == "bottom bar r1: first pass: icons only" and "which button row" in row["review_description"]
    assert env.published.count("cplug.reviewboard.boards") == 1


def test_request_review_false_posts_the_card_and_leaves_the_task_alone(env: Env, client, item):
    answer = made(client, item, request_review=False)
    assert answer["card"]["posted"] is True and answer["card"]["review"] == {"requested": False, "moved": False, "reason": None}
    assert huddle_store(env).item(item)["state"] == "open" and thread(env, item)[-1]["board"]["revision"] == "r1"


def test_a_task_that_cannot_move_keeps_its_state_and_says_why(env: Env, client, item):
    huddle_store(env).update(item, actor="joe", state="todo")
    answer = made(client, item)
    review = answer["card"]["review"]
    assert answer["card"]["posted"] is True and review["moved"] is False and "stays where it is" in review["reason"]
    assert huddle_store(env).item(item)["state"] == "todo"


def test_create_refuses_before_writing_when_the_task_is_missing_or_the_name_is_taken(env: Env, client, item):
    before = tree(env.root)
    missing = client.post(f"{BASE}/boards", json=create_body(9999))
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "reviewboard_no_task"
    assert tree(env.root) == before
    made(client, item)
    twice = client.post(f"{BASE}/boards", json=create_body(item))
    assert twice.status_code == 409 and twice.json()["detail"]["code"] == "reviewboard_exists"
    assert len([p for p in env.root.iterdir() if not p.name.startswith(".") and p.is_dir()]) == 1


def test_create_refuses_a_bad_request_and_leaves_nothing(env: Env, client, item):
    before = tree(env.root)
    for over in ({"viewport": 100}, {"slug_name": "Bad Name"}, {"prompts": [{"id": "a", "kind": "choice", "label": "x"}, {"id": "a", "kind": "check", "label": "y"}]},
                 {"anchors": [{"id": "send", "label": "x"}], "prompts": [{"id": "p", "kind": "check", "label": "x", "anchor": "nope"}]},
                 {"html": ""}, {"views": [{"id": "main", "label": "x", "html": "<p>x</p>"}]}, {"unknown_field": 1}):
        r = client.post(f"{BASE}/boards", json=create_body(item, **over))
        assert r.status_code == 422, (over, r.text)
    assert tree(env.root) == before
    assert not list(env.root.glob(".new-*"))


def test_a_page_over_the_limit_is_refused_before_any_write(env: Env, client, item):
    before = tree(env.root)
    r = client.post(f"{BASE}/boards", json=create_body(item, html="x" * (2 * 1024 * 1024 + 1)))
    assert r.status_code == 422 and tree(env.root) == before


def test_extra_views_are_written_as_their_own_pages(env: Env, client, item):
    answer = made(client, item, views=[{"id": "journeys", "label": "journeys", "html": "<p>j</p>"}])
    folder = env.board(answer["slug"])
    assert sorted(p.name for p in folder.iterdir()) == ["r001--journeys.html", "r001.html", "sidecar.json"]
    assert scan.scan(env.root).exit_code == 0



def test_revise_appends_and_never_touches_an_earlier_page(env: Env, client, item):
    first = made(client, item)
    slug = first["slug"]
    page1 = (env.board(slug) / "r001.html").read_bytes()
    r = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2: two rows", "html": HTML + "<!--2-->", "prompts": PROMPTS, "anchors": ANCHORS, "base_etag": first["etag"]})
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["revision"] == "r2" and answer["etag"] != first["etag"]
    assert (env.board(slug) / "r001.html").read_bytes() == page1 and (env.board(slug) / "r002.html").read_text().endswith("<!--2-->")
    sidecar = json.loads((env.board(slug) / "sidecar.json").read_text())
    assert [r["id"] for r in sidecar["revisions"]] == ["r1", "r2"] and sidecar["revisions"][1]["viewport"] == 320
    assert scan.scan(env.root).exit_code == 0
    assert answer["card"]["posted"] is True and answer["card"]["review"]["reason"] == "already in review"
    assert [m["board"]["revision"] for m in thread(env, item) if "board" in m] == ["r1", "r2"]


def test_a_stale_etag_is_409_and_leaves_the_sidecar_byte_identical(env: Env, client, item):
    first = made(client, item)
    slug = first["slug"]
    client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2", "html": HTML + "2"})
    before = tree(env.root)
    stale = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r3", "html": HTML + "3", "base_etag": first["etag"]})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "reviewboard_stale" and len(detail["etag"]) == 64 and detail["sidecar"]["revisions"][-1]["id"] == "r2"
    assert tree(env.root) == before
    assert [m["board"]["revision"] for m in thread(env, item) if "board" in m] == ["r1", "r2"]


def test_a_bad_revision_is_refused_before_any_file_is_written(env: Env, client, item):
    slug = made(client, item)["slug"]
    before = tree(env.root)
    for body in ({"summary": "x", "html": HTML, "answers_round": "n7"},
                 {"summary": "x", "html": HTML, "prompts": PROMPTS + [PROMPTS[0]]},
                 {"summary": "x", "html": HTML, "views": [{"id": "a", "label": "a", "html": "x"}, {"id": "a", "label": "b", "html": "y"}]},
                 {"summary": "x", "html": ""}, {"summary": "", "html": HTML}):
        r = client.post(f"{BASE}/boards/{slug}/revisions", json=body)
        assert r.status_code == 422, (body, r.text)
        assert tree(env.root) == before, body


def test_revise_needs_a_board_that_exists_and_validates(env: Env, client, item):
    assert client.post(f"{BASE}/boards/20261013-nope/revisions", json={"summary": "x", "html": HTML}).status_code == 404
    folder = make_board(env.root)
    raw = json.loads((folder / "sidecar.json").read_text())
    raw["schema_version"] = 9
    (folder / "sidecar.json").write_text(json.dumps(raw))
    before = tree(env.root)
    r = client.post(f"{BASE}/boards/20261013-bottom-bar/revisions", json={"summary": "x", "html": HTML, "viewport": 320})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_read_only" and tree(env.root) == before


def test_revise_replaces_the_orphan_page_of_a_crashed_write(env: Env, client, item):
    slug = made(client, item)["slug"]
    (env.board(slug) / "r002.html").write_text("left by a crash")
    assert any(f.code == "orphan" for f in scan.scan(env.root).findings)
    r = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2", "html": HTML + "2"})
    assert r.status_code == 200 and (env.board(slug) / "r002.html").read_text() == HTML + "2"
    assert scan.scan(env.root).findings == ()


def test_a_card_that_cannot_be_posted_never_undoes_the_revision(env: Env, client, item, monkeypatch):
    slug = made(client, item)["slug"]
    monkeypatch.setattr(publish, "local_computer", lambda: "some-other-mac")
    sidecar_path = env.board(slug) / "sidecar.json"
    raw = json.loads(sidecar_path.read_text())
    raw["task"]["computer"] = "hostb"
    sidecar_path.write_text(document.canonical_text(document.parse_sidecar(raw)))
    r = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r2", "html": HTML + "2"})
    assert r.status_code == 200 and r.json()["revision"] == "r2"
    assert r.json()["card"] == {"posted": False, "reason": "the task is on hostb"}
    assert [m["board"]["revision"] for m in thread(env, item) if "board" in m] == ["r1"]
    huddle_store(env).delete(item, actor="joe")
    monkeypatch.setattr(publish, "local_computer", lambda: "hostb")
    gone = client.post(f"{BASE}/boards/{slug}/revisions", json={"summary": "r3", "html": HTML + "3"})
    assert gone.status_code == 200 and gone.json()["card"]["posted"] is False and "no longer exists" in gone.json()["card"]["reason"]


def test_the_board_cannot_be_written_while_the_huddle_is_off(env: Env, client, item):
    board_port.unregister()
    before = tree(env.root)
    r = client.post(f"{BASE}/boards", json=create_body(item))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reviewboard_no_task_manager" and tree(env.root) == before



def build_next(current, body_html="<p>x</p>"):
    body = ReviseBody(summary="s", html=body_html)
    from datetime import datetime
    return revisions.next_document(current, body, datetime(2026, 10, 14, 1, 2, 3), {"actor": "claude"})


def test_a_failure_while_writing_the_sidecar_leaves_it_byte_identical_and_never_names_a_missing_page(env: Env, tmp_path: Path, monkeypatch):
    folder = make_board(env.root)
    state = tmp_path / "state"
    before = tree(env.root)
    real = store.write_atomic

    def fail_on_sidecar(path: Path, data: bytes) -> None:
        if path.name == "sidecar.json":
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(store, "write_atomic", fail_on_sidecar)
    with pytest.raises(OSError):
        store.append(env.root, state, folder.name, None, build_next)
    after = tree(env.root)
    assert after[f"{folder.name}/sidecar.json"] == before[f"{folder.name}/sidecar.json"]
    assert set(after) - set(before) == {f"{folder.name}/r002.html"}
    assert scan.scan(env.root).exit_code == 0 and any(f.code == "orphan" for f in scan.scan(env.root).findings)


def test_a_failed_create_leaves_no_board_and_no_staging_folder(env: Env, tmp_path: Path, monkeypatch):
    real = store.write_atomic

    def fail_on_sidecar(path: Path, data: bytes) -> None:
        if path.name == "sidecar.json":
            raise OSError("disk full")
        real(path, data)

    raw = copy.deepcopy(SIDECAR)
    monkeypatch.setattr(store, "write_atomic", fail_on_sidecar)
    before = tree(env.root)
    with pytest.raises(OSError):
        store.create(env.root, tmp_path / "state", raw["board"]["slug"], lambda _none: (raw, {"r001.html": PAGE}))
    assert tree(env.root) == before and [p.name for p in env.root.iterdir()] == [".boards-root"]


def test_two_writers_of_one_board_wait_for_each_other(env: Env, tmp_path: Path):
    folder = make_board(env.root)
    state = tmp_path / "state"
    results, errors = [], []

    def slow_build(current):
        time.sleep(0.15)
        return build_next(current, f"<p>{threading.get_ident()}</p>")

    def run():
        try:
            results.append(store.append(env.root, state, folder.name, None, slow_build)[1])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(set(results)) == 2
    sidecar = json.loads((folder / "sidecar.json").read_text())
    assert [r["id"] for r in sidecar["revisions"]] == ["r1", "r2", "r3"]
    assert scan.scan(env.root).exit_code == 0


def test_a_slug_or_root_trick_never_leaves_the_boards_folder(env: Env, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (env.root / "20261013-link").symlink_to(outside)
    for slug in ("../outside", "20261013-link", "20261013-a/../../x"):
        with pytest.raises(Exception) as caught:
            store.append(env.root, tmp_path / "state", slug, None, build_next)
        assert getattr(caught.value, "code", "") == "reviewboard_not_found", slug
    assert list(outside.iterdir()) == []


def test_the_page_name_follows_the_revision_number():
    assert revisions.file_name(2, "main") == "r002.html" and revisions.file_name(12, "journeys") == "r012--journeys.html"
    assert revisions.file_name(1000, "main") == "r1000.html"
    with pytest.raises(BadRequest):
        from src.cplugs.reviewboard.requests import RevisionBody
        revisions._pages(RevisionBody(summary="s", html="x", views=[{"id": "a", "label": "a", "html": "y"}, {"id": "a", "label": "b", "html": "z"}]), 1)



def test_the_agent_tools_publish_from_a_file_and_apply_the_own_list_guard(env: Env, tmp_path: Path):
    huddle = huddle_store(env)
    mine = huddle.add("12", "my task", actor="claude")["id"]
    theirs = huddle.add("13", "another project's task", actor="claude")["id"]
    page = tmp_path / "page.html"
    page.write_text(HTML)
    args = {"name": "bottom-bar", "title": "bottom bar", "task": mine, "summary": "first pass", "file_path": str(page), "viewport": 320, "prompts": PROMPTS, "anchors": ANCHORS}
    ok, created = env.call("task_manager_board_create", args)
    assert ok, created
    slug = created["slug"]
    assert (env.board(slug) / "r001.html").read_text() == HTML and created["card"]["posted"] is True
    assert json.loads((env.board(slug) / "sidecar.json").read_text())["revisions"][0]["by"] == {"actor": "claude", "session": "ses_1"}
    ok, revised = env.call("task_manager_board_revision_add", {"board": slug, "summary": "r2", "html": HTML + "2", "answers_round": None, "base_etag": created["etag"]})
    assert ok, revised
    assert revised["revision"] == "r2"
    before = tree(env.root)
    ok, text = env.call("task_manager_board_create", {**args, "name": "other", "task": theirs})
    assert not ok and "cross_project" in text and tree(env.root) == before
    ok, crossed = env.call("task_manager_board_create", {**args, "name": "other", "task": theirs, "cross_project": True})
    assert ok and crossed["card"]["cross_project"] == {"from": "carnivore", "to": "blog"}
    assert any("written from another project" in m["text"] for m in thread(env, theirs))


def test_the_tools_refuse_a_bad_page_argument(env: Env, tmp_path: Path):
    huddle = huddle_store(env)
    mine = huddle.add("12", "my task", actor="joe")["id"]
    page = tmp_path / "page.html"
    page.write_text(HTML)
    link = tmp_path / "link.html"
    link.symlink_to(page)
    base = {"name": "bottom-bar", "title": "bottom bar", "task": mine, "summary": "x", "viewport": 320}
    for extra, expected in (({}, "exactly one of html"), ({"html": HTML, "file_path": str(page)}, "exactly one of html"),
                            ({"file_path": "relative.html"}, "absolute path"), ({"file_path": str(link)}, "symlink"),
                            ({"html": HTML, "viewport": 10}, "reviewboard_invalid"), ({"html": HTML, "bogus": 1}, "bogus")):
        ok, text = env.call("task_manager_board_create", {**base, **extra})
        assert not ok and expected in text, (extra, text)
    assert [p.name for p in env.root.iterdir()] == [".boards-root"]
    ok, text = env.call("task_manager_board_revision_add", {"summary": "x", "html": HTML})
    assert not ok and "board is required" in text


def test_a_read_token_does_not_see_the_write_tools(env: Env):
    from src.core.mcp import tools
    read = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    full = {d["name"] for d in tools.tool_definitions()}
    assert {"task_manager_board_create", "task_manager_board_revision_add"} <= full
    assert not read & {"task_manager_board_create", "task_manager_board_revision_add"}



def test_the_board_card_is_a_plain_message_to_every_other_reader(env: Env, client, item):
    made(client, item)
    row = huddle_store(env).item(item)
    card = thread(env, item)[-1]
    assert card["board"]["revision"] == "r1" and "artifact" not in card and "files" not in card and "form" not in card
    assert huddle_wire.board.wire('{"files": [], "artifact": {}}') is None and huddle_wire.board.wire("") is None
    assert huddle_wire.board.wire('{"board": "damaged"') is None
    assert board_port.NAME == "huddle.board"
    assert OWN_PROJECT == 12
