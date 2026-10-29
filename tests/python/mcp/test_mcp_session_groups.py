
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.mcp import pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")


class View:

    gate_waited = False

    def __init__(self, names):
        self.app = SimpleNamespace(state=SimpleNamespace())
        self._names = names

    async def list_infos(self):
        return [SimpleNamespace(tmux_session=n, host_key="local", session=SimpleNamespace(id=f"ses_{n}"),
                                session_row_id=i) for i, n in enumerate(self._names, 1)]

    async def list_peer_infos(self):
        return []


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings
    from src.core import session_change_notice

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    db = db_path_for(state)
    notices: list = []
    monkeypatch.setattr(session_change_notice, "publish", lambda app_state, frame: notices.append(frame))
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    from src.core.mcp import common
    view = View(["cloude_a", "cloude_b"])

    async def local(manager):
        return await manager.list_infos()

    monkeypatch.setattr(common, "_local_infos", local)
    monkeypatch.setattr("src.core.mcp.group_tools._local_infos", local)
    return db, view, notices


def _seed_sessions(db) -> dict:
    out = {}
    with closing(connect(db, create=False)) as conn, conn:
        for name in ("cloude_a", "cloude_b"):
            out[name] = f"uuid-{name}"
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, "
                "created_at, updated_at) VALUES (?, 'cloude', ?, 1, 'created', 'running', "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (out[name], name))
    return out


def _call(view, name, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(view, caller, name, args))


def _text(answer: dict) -> str:
    return str(answer)


def test_create_move_list_then_delete_refusal_and_success(world):
    db, view, notices = world
    _seed_sessions(db)
    made = _call(view, "session_group_create", {"name": "  infra  "})
    assert not made.get("isError"), made
    assert "infra" in _text(made)
    assert notices, "the create must publish the groups push"
    moved = _call(view, "session_group_move", {"targets": ["cloude_a", "ses_cloude_b"], "group": "INFRA"})
    assert not moved.get("isError"), moved
    listed = _call(view, "session_groups_list", {})
    assert "cloude_a" in _text(listed) and "ses_cloude_b" in _text(listed)
    refused = _call(view, "session_group_delete", {"group": "infra"})
    assert refused["isError"] is True and "still has members" in _text(refused)
    assert not _call(view, "session_group_move", {"targets": ["cloude_a", "cloude_b"], "group": None}).get("isError")
    assert not _call(view, "session_group_rename", {"group": "infra", "name": "ops"}).get("isError")
    gone = _call(view, "session_group_delete", {"group": "ops"})
    assert not gone.get("isError"), gone
    from src.api import session_groups_routes as routes
    assert asyncio.run(routes.list_session_groups()).groups == []


def test_membership_is_by_uuid_and_survives_a_tmux_rename(world):
    db, view, _ = world
    uuids = _seed_sessions(db)
    _call(view, "session_group_create", {"name": "keep"})
    _call(view, "session_group_move", {"targets": ["cloude_a"], "group": "keep"})
    with closing(connect(db, create=False)) as conn:
        conn.execute("UPDATE sessions SET tmux_name = 'cloude_renamed' WHERE session_uuid = ?", (uuids["cloude_a"],))
        conn.commit()
    from src.api import session_groups_routes as routes
    groups = asyncio.run(routes.list_session_groups()).groups
    assert groups[0].members == ["cloude_renamed"]
    assert groups[0].member_session_uuids == [uuids["cloude_a"]]


def test_bad_inputs_move_nothing_and_unknown_group_is_refused(world):
    db, view, _ = world
    _seed_sessions(db)
    _call(view, "session_group_create", {"name": "one"})
    for args in ({"targets": ["cloude_a", "nope"], "group": "one"}, {"targets": ["cloude_a"], "group": "missing"},
                 {"targets": [], "group": "one"}, {"targets": ["cloude_a"]}, {"targets": ["cloude_a"], "group": "one", "x": 1}):
        assert _call(view, "session_group_move", args)["isError"] is True
    from src.api import session_groups_routes as routes
    assert asyncio.run(routes.list_session_groups()).groups[0].members == []


def test_read_only_token_sees_only_the_list_tool(world):
    _, view, _ = world
    names = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "session_groups_list" in names
    assert not names & {"session_group_create", "session_group_move", "session_group_rename", "session_group_delete"}
    assert _call(view, "session_group_create", {"name": "x"}, READ_ONLY)["isError"] is True


def test_routes_require_auth():
    from src.api import session_groups_routes as routes

    deps = {r.path + ":" + ",".join(sorted(r.methods)): [d.dependency.__name__ for d in r.dependencies] for r in routes.router.routes}
    assert deps and all("require_auth" in v for v in deps.values())
