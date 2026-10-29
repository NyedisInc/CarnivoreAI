
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.cplugs.huddle import github_issue
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
URL = "https://github.com/Harbor666/CarnivoreAIDev/issues/1571"


def test_a_rung_29_file_gains_the_github_issue_column_and_keeps_its_rows(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:29]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, "
                     "seq) VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 29")
    store = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None)
    items = store.list_items("all")["items"]
    assert [i["text"] for i in items] == ["old row"] and "github_issue" not in items[0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert "github_issue" in [r[1] for r in conn.execute("PRAGMA table_info(items)")]


def test_a_good_url_is_kept_canonical_a_bad_one_is_refused_and_empty_clears():
    assert github_issue.clean_field(None) == {}
    assert github_issue.clean_field(f" {URL}/ ") == {"github_issue": URL}
    assert github_issue.clean_field("") == {"github_issue": None}
    assert github_issue.clean_field("   ") == {"github_issue": None}
    for bad in ("http://github.com/a/b/issues/1", "https://evil.com/a/b/issues/1", "https://github.com.evil.com/a/b/issues/1",
                "https://user@github.com/a/b/issues/1", "https://github.com:8443/a/b/issues/1", "https://github.com/a/b/pull/1",
                "https://github.com/a/b/issues/", "https://github.com/a/b/issues/x", "javascript:alert(1)", "1571"):
        with pytest.raises(TaskManagerInvalid):
            github_issue.clean_field(bad)
    with pytest.raises(TaskManagerInvalid):
        github_issue.clean_field(1571)


def test_the_route_and_the_mcp_tools_round_trip_the_link(client, setup):
    manager = setup.manager
    item = add(client, "all", "link me")
    assert "github_issue" not in client.get(f"{BASE}/lists/all").json()["items"][0]
    patched = client.patch(f"{BASE}/items/{item}", json={"github_issue": URL})
    assert patched.status_code == 200 and patched.json()["github_issue"] == URL
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["github_issue"] == URL
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert ok and listed["items"][0]["github_issue"] == URL
    refused = client.patch(f"{BASE}/items/{item}", json={"github_issue": "https://example.com/x"})
    assert refused.status_code in (400, 422) and "github_issue" in str(refused.json())
    assert client.get(f"{BASE}/lists/all").json()["items"][0]["github_issue"] == URL
    ok, cleared = call(manager, "task_manager_update", {"item": item, "github_issue": ""})
    assert ok and "github_issue" not in cleared
    ok, set_by_claude = call(manager, "task_manager_update", {"item": item, "github_issue": URL})
    assert ok and set_by_claude["github_issue"] == URL
    ok, added = call(manager, "task_manager_add", {"list": "all", "text": "claude item", "github_issue": URL})
    assert ok and added["github_issue"] == URL
    ok, bad = call(manager, "task_manager_add", {"list": "all", "text": "bad", "github_issue": "http://github.com/a/b/issues/1"})
    assert not ok
    assert client.patch(f"{BASE}/items/{item}", json={"github_issue": ""}).json().get("github_issue") is None
