
from __future__ import annotations

import asyncio
import json
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
        return {r["id"]: (r["display_name"], r["root"], r["archived_at"]) for r in conn.execute("SELECT * FROM projects")}


def _call(name: str, args: dict, caller: AgentCaller = PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _approve_only() -> None:
    store = pending.get_store()
    assert len(store.list()) == 1
    asyncio.run(store.approve(store.list()[0]["id"]))


def _listed(include_archived: bool) -> set:
    answer = _call("projects_list", {"include_archived": include_archived})
    return {p["name"] for p in json.loads(answer["content"][0]["text"])["projects"]}


def test_archive_then_unarchive_wait_for_approval_and_touch_only_archived_at(world, tmp_path):
    db, ids = world
    (tmp_path / "alpha").mkdir()
    before = _rows(db)

    assert "pending" in str(_call("project_archive", {"project": ids["alpha"]}))
    assert _rows(db) == before
    _approve_only()
    archived = _rows(db)
    assert archived[ids["alpha"]][2] is not None
    assert archived[ids["alpha"]][:2] == before[ids["alpha"]][:2]
    assert archived[ids["beta"]] == before[ids["beta"]]
    assert (tmp_path / "alpha").is_dir()
    assert _listed(False) == {"beta"}
    assert _listed(True) == {"alpha", "beta"}

    assert "pending" in str(_call("project_unarchive", {"project": ids["alpha"]}))
    assert _rows(db)[ids["alpha"]][2] is not None
    _approve_only()
    assert _rows(db) == before
    assert _listed(False) == {"alpha", "beta"}


def test_bad_arguments_unknown_project_and_read_only_callers_are_refused(world):
    _db, ids = world
    for name in ("project_archive", "project_unarchive"):
        for args in ({}, {"project": 0}, {"project": True}, {"project": 9999}, {"project": ids["alpha"], "name": "x"}):
            assert _call(name, args)["isError"] is True
        assert _call(name, {"project": ids["alpha"]}, READ_ONLY)["isError"] is True
        assert name not in {t["name"] for t in tools.tool_definitions(READ_ONLY)}
        assert name in {t["name"] for t in tools.tool_definitions(PANE)}
    assert _call("projects_list", {"include_archived": "yes"})["isError"] is True
    assert not pending.get_store().list()
