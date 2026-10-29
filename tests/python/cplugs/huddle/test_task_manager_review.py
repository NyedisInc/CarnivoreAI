
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.core.mcp import tools
from src.cplugs.huddle import review
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
NONE = {"review_description": None, "review_summary": None, "review_link": None, "review_where": None, "review_action": None}


def test_a_rung_eight_file_gains_the_review_columns_and_keeps_its_rows(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:8]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 8")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    items = store.list_items("all")["items"]
    assert [(i["text"], i["number"], {k: i[k] for k in review.FIELDS}) for i in items] == [("old row", 1, NONE)]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 9


@pytest.mark.parametrize("link", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x", "//evil.example/x",
                                  "/\\evil.example", "ftp://host/x", "http://", "https://a b", "relative/path"])
def test_a_link_that_is_not_an_app_path_or_web_url_is_refused(link):
    with pytest.raises(review.TaskManagerInvalid):
        review.clean_field("review_link", link)


@pytest.mark.parametrize("link", ["/#/huddle", "/static/x.html?a=1", "http://localhost:5001/a", "https://example.com/p#q"])
def test_an_app_path_or_web_url_is_kept(link):
    assert review.clean_field("review_link", f"  {link} ") == link


def test_the_route_round_trips_the_fields_validates_and_pushes(client, setup):
    item = add(client, "all", "ship it")
    assert {k: client.get(f"{BASE}/lists/all").json()["items"][0][k] for k in review.FIELDS} == NONE
    setup.published.clear()
    sent = {"review_description": "check the new block", "review_summary": "block done", "review_where": "huddle tab", "review_link": "/#/huddle", "review_action": "push"}
    answer = client.patch(f"{BASE}/items/{item}", json={"state": "review", **sent})
    assert answer.status_code == 200 and {k: answer.json()[k] for k in review.FIELDS} == sent
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]
    assert {k: client.get(f"{BASE}/lists/all").json()["items"][0][k] for k in review.FIELDS} == sent
    refused = client.patch(f"{BASE}/items/{item}", json={"review_link": "javascript:alert(1)"})
    assert refused.status_code == 400
    assert client.patch(f"{BASE}/items/{item}", json={"review_description": "x" * 4001}).status_code == 400
    kept = client.patch(f"{BASE}/items/{item}", json={"review_where": ""}).json()
    assert (kept["review_description"], kept["review_link"], kept["review_where"]) == ("check the new block", "/#/huddle", None)
    assert client.patch(f"{BASE}/items/{item}", json={"review_action": "go"}).status_code == 400
    assert client.patch(f"{BASE}/items/{item}", json={"review_description": "y" * 3000}).status_code == 200
    added = client.post(f"{BASE}/lists/all/items", json={"text": "with review", "review_description": "look"})
    assert added.status_code == 200 and added.json()["review_description"] == "look"
    assert client.post(f"{BASE}/lists/all/items", json={"text": "bad", "review_link": "data:x"}).status_code == 400


def test_the_mcp_tools_take_the_optional_fields_with_review(client, setup):
    manager = setup.manager
    ok, made = call(manager, "task_manager_add", {"list": "all", "text": "built it", "review_description": "see the row"})
    assert ok and made["review_description"] == "see the row" and "review_link" not in made
    ok, summed = call(manager, "task_manager_update", {"item": made["id"], "review_summary": "built it", "state": "review"})
    assert ok and summed["review_summary"] == "built it"
    setup.published.clear()
    ok, done = call(manager, "task_manager_update", {"item": made["id"], "state": "review",
                                               "review_description": "open the sidebar", "review_where": "huddle tab",
                                               "review_link": "https://example.com/pr/1"})
    assert ok and done["status"] == "review"
    assert (done["review_description"], done["review_where"], done["review_link"]) == (
        "open the sidebar", "huddle tab", "https://example.com/pr/1")
    assert setup.published == ["cplug.huddle.list:all", "cplug.huddle.cards:all"]
    ok, text = call(manager, "task_manager_update", {"item": made["id"], "review_link": "javascript:alert(1)"})
    assert not ok and "review_link" in text
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all", "fields": ["review"]})
    assert listed["items"][0]["review_link"] == "https://example.com/pr/1"
    ok, plain = call(manager, "task_manager_update", {"item": made["id"], "state": "open"})
    assert ok and plain["state"] == "open"
    for name in ("task_manager_add", "task_manager_update"):
        spec = next(d for d in tools.tool_definitions() if d["name"] == name)
        assert set(review.FIELDS) <= set(spec["inputSchema"]["properties"])
        assert not set(review.FIELDS) & set(spec["inputSchema"].get("required", []))


def test_a_rung_thirty_two_file_gains_review_summary_and_existing_rows_read_null(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:32]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, review_description) "
                     "VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1, 'was reviewed')")
        conn.execute("PRAGMA user_version = 32")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    item = store.list_items("all")["items"][0]
    assert item["review_summary"] is None and item["review_description"] == "was reviewed"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_review_summary_is_one_bounded_line():
    assert review.clean_field("review_summary", "  did it\n and more ") == "did it and more"
    assert review.clean_field("review_summary", "  ") is None
    with pytest.raises(review.TaskManagerInvalid):
        review.clean_field("review_summary", "x" * (review.MAX_SUMMARY + 1))
