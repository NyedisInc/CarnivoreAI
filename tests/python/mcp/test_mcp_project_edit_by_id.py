
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.mcp import pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.project_writes import create_project  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")


class View:

    gate_waited = False


@pytest.fixture()
def twins(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    db = db_path_for(state)
    with closing(connect(db)) as conn:
        first = create_project(conn, name="twin", path=str(tmp_path / "one"))
        second = create_project(conn, name="other", path=str(tmp_path / "two"))
        with conn:
            conn.execute("UPDATE projects SET display_name = 'twin' WHERE id = ?", (second["id"],))
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    return db, first["id"], second["id"]


def _approve_one() -> None:
    store = pending.get_store()
    asyncio.run(store.approve(store.list()[0]["id"]))


def test_a_rename_by_exact_id_succeeds_when_two_projects_share_the_name(twins):
    db, _one, two = twins
    asyncio.run(tools.call_tool(View(), PANE, "project_rename", {"project": two, "name": "renamed"}))
    _approve_one()
    with closing(connect(db, create=False)) as conn:
        names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM projects")}
    assert names[two] == "renamed" and "twin" in names.values()


def test_the_by_id_route_edits_one_of_two_same_named_projects(twins):
    from src.api.projects.by_id_routes import update_project_by_id
    from src.models import UpdateProjectRequest

    _db, _one, two = twins
    row = asyncio.run(update_project_by_id(two, UpdateProjectRequest(short_description="the second")))
    assert row.id == two and row.short_description == "the second"


def test_the_by_id_delete_removes_one_of_two_same_named_projects(twins, monkeypatch):
    from types import SimpleNamespace

    from src.core.session_roles import check as session_roles_check
    from src.api.projects.by_id_routes import delete_project_by_id

    async def _no_check(_state) -> None:
        return None

    monkeypatch.setattr(session_roles_check, "after_change", _no_check)
    db, one, two = twins
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    answer = asyncio.run(delete_project_by_id(two, request))
    with closing(connect(db, create=False)) as conn:
        left = [r["id"] for r in conn.execute("SELECT id FROM projects")]
    assert answer.success is True and left == [one]


def test_an_action_parked_before_a_rename_still_lands_after_it(twins):
    from src.api.projects.by_id_routes import update_project_by_id
    from src.models import UpdateProjectRequest

    db, _one, two = twins
    asyncio.run(tools.call_tool(View(), PANE, "project_archive", {"project": two}))
    asyncio.run(update_project_by_id(two, UpdateProjectRequest(new_name="renamed-while-parked")))
    _approve_one()
    with closing(connect(db, create=False)) as conn:
        row = conn.execute("SELECT display_name, archived_at FROM projects WHERE id = ?", (two,)).fetchone()
    assert row["display_name"] == "renamed-while-parked" and row["archived_at"]
