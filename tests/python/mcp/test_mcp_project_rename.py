
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
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")


class View:

    gate_waited = False


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    db = db_path_for(state)
    with closing(connect(db)) as conn:
        a = create_project(conn, name="alpha", path=str(tmp_path / "alpha"))
        b = create_project(conn, name="beta", path=str(tmp_path / "beta"))
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    return db, {"alpha": a["id"], "beta": b["id"]}


def _rows(db) -> dict:
    with closing(connect(db, create=False)) as conn:
        return {r["id"]: (r["display_name"], r["root"]) for r in conn.execute("SELECT * FROM projects")}


def _call(args: dict, caller: AgentCaller = PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, "project_rename", args))


def _approve_only() -> None:
    asyncio.run(pending.get_store().approve(pending.get_store().list()[0]["id"]))


def test_rename_waits_for_approval_then_changes_display_name_only(world):
    db, ids = world
    before = _rows(db)
    answer = _call({"project": ids["alpha"], "name": "  gamma  "})
    assert "pending" in str(answer)
    assert _rows(db) == before
    _approve_only()
    after = _rows(db)
    assert after[ids["alpha"]][0] == "gamma"
    assert after[ids["alpha"]][1] == before[ids["alpha"]][1]
    assert after[ids["beta"]] == before[ids["beta"]]
    assert set(after) == set(before)


def test_collision_unknown_project_and_bad_names_are_refused(world):
    db, ids = world
    before = _rows(db)
    for args in ({"project": 9999, "name": "x"}, {"project": ids["alpha"], "name": "   "},
                 {"project": ids["alpha"], "name": "x" * 256}, {"project": ids["alpha"], "name": "a\nb"},
                 {"project": "alpha", "name": "x"}, {"project": ids["alpha"], "name": "x", "path": "/tmp"}):
        assert _call(args)["isError"] is True
    assert not pending.get_store().list()

    _call({"project": ids["alpha"], "name": "beta"})
    _approve_only()
    assert _rows(db) == before


def test_read_only_token_cannot_call_it(world):
    _, ids = world
    assert _call({"project": ids["alpha"], "name": "x"}, READ_ONLY)["isError"] is True
    assert "project_rename" not in {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "project_rename" in {t["name"] for t in tools.tool_definitions(PANE)}


def test_archived_project_can_be_renamed_but_a_duplicate_name_is_still_refused(world):
    db, ids = world
    with closing(connect(db)) as conn:
        conn.execute("UPDATE projects SET archived_at = '2026-10-10T00:00:00Z' WHERE id = ?", (ids["alpha"],))
        conn.commit()
    before = _rows(db)

    _call({"project": ids["alpha"], "name": "beta"})
    _approve_only()
    assert _rows(db) == before

    _call({"project": ids["alpha"], "name": "living room"})
    _approve_only()
    after = _rows(db)
    assert after[ids["alpha"]] == ("living room", before[ids["alpha"]][1])
    with closing(connect(db, create=False)) as conn:
        archived = conn.execute("SELECT archived_at FROM projects WHERE id = ?", (ids["alpha"],)).fetchone()[0]
    assert archived is not None
