
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.project_writes import create_project, delete_project
from src.plugins.host import runtime
from src.plugins.huddle import groups as groups_mod, project_port
from src.plugins.huddle.rules import JOE
from src.plugins.sdk import ports
from src.plugins.sdk.project_lists import NAME
from tests.python.cplugs.huddle.test_task_manager_routes import app  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import store_of
from tests.test_project_authority import state_dir  # noqa: F401


def test_clear_removes_the_projects_items_and_groups_and_no_one_elses(app):
    store = store_of(app)
    writer = groups_mod.GroupWriter(store)
    group = writer.create("102", "Handcheck", actor=JOE)
    mine = store.add("102", "old work", actor=JOE, group=group["id"])
    other = store.add("103", "keep me", actor=JOE)
    ctx = runtime.host_for(app).context("huddle", background=True)

    result = project_port.ProjectListsPort(ctx).clear(102)

    assert result == {"list": "102", "items": 1, "groups": 1}
    assert store.live_item_ids("102") == []
    assert store.live_group_ids("102") == []
    assert store.live_item_ids("103") == [other["id"]]
    assert mine["id"] not in store.live_item_ids("102")


def test_deleting_a_project_calls_the_port_with_its_id(state_dir):
    calls = []

    class Spy:
        def clear(self, project_id):
            calls.append(project_id)
            return {"list": str(project_id), "items": 0, "groups": 0}

    ports.register(NAME, Spy())
    try:
        with closing(connect(db_path_for(state_dir))) as conn:
            row = create_project(conn, name="p", path=str(state_dir / "p"))
            delete_project(conn, row["id"])
    finally:
        ports.unregister(NAME)
    assert calls == [row["id"]]


def test_a_failing_port_does_not_undo_the_delete(state_dir):
    class Broken:
        def clear(self, project_id):
            raise OSError("datastore gone")

    ports.register(NAME, Broken())
    try:
        with closing(connect(db_path_for(state_dir))) as conn:
            row = create_project(conn, name="p", path=str(state_dir / "p"))
            assert delete_project(conn, row["id"])["id"] == row["id"]
    finally:
        ports.unregister(NAME)
