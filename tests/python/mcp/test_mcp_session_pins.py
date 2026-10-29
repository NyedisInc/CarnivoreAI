
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import os
import tempfile
import uuid
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

OTHER = "11111111-1111-4111-8111-111111111111"
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
    from src.core.ui_preferences_store import UiPreferencesStore

    state = tmp_path / "state"
    state.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(cfg), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    notices: list = []
    monkeypatch.setattr(session_change_notice, "publish", lambda app_state, frame: notices.append(frame))
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    view = View(["cloude_a", "cloude_b"])
    view.app.state.ui_preferences_store = UiPreferencesStore(lambda: Path(cfg))

    class Sockets:

        async def broadcast(self, text):
            return None

    view.app.state.connection_manager = Sockets()

    async def everyone(manager):
        return await manager.list_infos()

    monkeypatch.setattr("src.core.mcp.pin_tools._all_infos", everyone)
    monkeypatch.setattr("src.core.mcp.common._all_infos", everyone)
    return db_path_for(state), view, notices


def _seed_sessions(db) -> dict:
    out = {}
    with closing(connect(db, create=False)) as conn, conn:
        for name in ("cloude_a", "cloude_b"):
            out[name] = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, "
                "created_at, updated_at) VALUES (?, 'cloude', ?, 1, 'created', 'running', "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (out[name], name))
    return out


def _call(view, name, args, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(view, caller, name, args))


def _text(answer: dict) -> str:
    return str(answer)


def _arrangement(view) -> dict:
    return view.app.state.ui_preferences_store.read()["values"].get("drawer_arrangement") or {}


def test_pin_and_unpin_by_uuid_keep_other_fields(world):
    db, view, notices = world
    uuids = _seed_sessions(db)
    store = view.app.state.ui_preferences_store
    keep = {"v": 1, "pinned": [], "order": ["x", "y"], "bands": {"g:1": ["a"]}, "collapsed": ["rogue"], "projects_open": True}
    assert store.update({"drawer_arrangement": keep}).status == "committed"
    done = _call(view, "session_pin", {"target": "cloude_a"})
    assert not done.get("isError"), done
    assert _arrangement(view)["pinned"] == [uuids["cloude_a"]]
    assert not _call(view, "session_pin", {"target": "ses_cloude_a"}).get("isError")
    assert _arrangement(view)["pinned"] == [uuids["cloude_a"]], "pinning twice must not duplicate"
    _call(view, "session_pin", {"target": "cloude_b"})
    listed = _call(view, "session_pins_list", {})
    assert "cloude_a" in _text(listed) and "cloude_b" in _text(listed)
    assert not _call(view, "session_unpin", {"target": "cloude_a"}).get("isError")
    arr = _arrangement(view)
    assert arr["pinned"] == [uuids["cloude_b"]]
    for field in ("order", "bands", "collapsed", "projects_open"):
        assert arr[field] == keep[field]
    assert notices and notices[-1]["type"] == "preferences.changed" and "drawer_arrangement" in notices[-1]["changed"]


def test_a_409_rereads_and_retries_once(world, monkeypatch):
    db, view, _ = world
    uuids = _seed_sessions(db)
    store = view.app.state.ui_preferences_store
    real = store.update
    calls = {"n": 0}

    def racing(changes, expected_revision=None):
        calls["n"] += 1
        if calls["n"] == 1:
            real({"drawer_arrangement": {"v": 1, "pinned": [OTHER]}})
        return real(changes, expected_revision)

    monkeypatch.setattr(store, "update", racing)
    assert not _call(view, "session_pin", {"target": "cloude_a"}).get("isError")
    assert calls["n"] == 2
    assert _arrangement(view)["pinned"] == [OTHER, uuids["cloude_a"]]


def test_pin_survives_a_tmux_rename(world):
    db, view, _ = world
    uuids = _seed_sessions(db)
    _call(view, "session_pin", {"target": "cloude_a"})
    with closing(connect(db, create=False)) as conn:
        conn.execute("UPDATE sessions SET tmux_name = 'cloude_renamed' WHERE session_uuid = ?", (uuids["cloude_a"],))
        conn.commit()
    assert _arrangement(view)["pinned"] == [uuids["cloude_a"]]
    assert "cloude_renamed" in _text(_call(view, "session_pins_list", {}))


def test_bad_inputs_change_nothing(world):
    db, view, _ = world
    _seed_sessions(db)
    for name, args in (("session_pin", {"target": "nope"}), ("session_pin", {}), ("session_pin", {"target": "cloude_a", "x": 1}),
                       ("session_unpin", {"target": "nope"})):
        assert _call(view, name, args)["isError"] is True
    assert _arrangement(view) == {}


def test_read_only_token_sees_only_the_list_tool(world):
    _, view, _ = world
    names = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "session_pins_list" in names and not names & {"session_pin", "session_unpin"}
    assert _call(view, "session_pin", {"target": "cloude_a"}, READ_ONLY)["isError"] is True


def test_pin_tools_are_ungated_for_a_pane_and_the_route_requires_auth():
    assert {"session_pin", "session_unpin"} <= tools._UNGATED_WRITES
    from src.api import preferences_routes as routes

    deps = {r.path + ":" + ",".join(sorted(r.methods)): [d.dependency.__name__ for d in r.dependencies] for r in routes.router.routes}
    assert deps and all("require_auth" in v for v in deps.values())


def _seed_gone(db, name: str) -> str:
    return _seed_stopped(db, name, archived=True)


def _seed_stopped(db, name: str, archived: bool = False) -> str:
    row_uuid = str(uuid.uuid4())
    with closing(connect(db, create=False)) as conn, conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, "
            "lifecycle_source, created_at, updated_at, archived_at) VALUES (?, 'cloude', ?, 1, 'created', 'stopped', "
            "'slept_by_user', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)",
            (row_uuid, name, "2026-01-02T00:00:00Z" if archived else None))
    return row_uuid


def test_an_asleep_session_pins_by_tmux_name_and_lists_as_asleep(world):
    db, view, _ = world
    _seed_sessions(db)
    nap = _seed_stopped(db, "cloude_nap")
    done = _call(view, "session_pin", {"target": "cloude_nap"})
    assert not done.get("isError"), done
    assert json.loads(done["content"][0]["text"])["state"] == "asleep"
    listed = json.loads(_call(view, "session_pins_list", {})["content"][0]["text"])["pinned"]
    assert [(p["session_uuid"], p["state"], p["id"]) for p in listed] == [(nap, "asleep", None)]


@pytest.mark.parametrize("by_name", [False, True])
def test_an_orphaned_pin_is_listed_and_unpins_by_uuid_or_old_name(world, by_name):
    db, view, _ = world
    uuids = _seed_sessions(db)
    gone = _seed_gone(db, "carnivore_switch")
    store = view.app.state.ui_preferences_store
    assert store.update({"drawer_arrangement": {"v": 1, "pinned": [uuids["cloude_a"], gone]}}).status == "committed"
    listed = json.loads(_call(view, "session_pins_list", {})["content"][0]["text"])["pinned"]
    assert [(p["session_uuid"], p["state"], p["orphaned"]) for p in listed] == [
        (uuids["cloude_a"], "live", False), (gone, "orphaned", True)]
    assert _call(view, "session_pin", {"target": gone})["isError"] is True, "pinning a gone session is refused"
    done = _call(view, "session_unpin", {"target": "carnivore_switch" if by_name else gone})
    assert not done.get("isError"), done
    assert json.loads(done["content"][0]["text"])["state"] == "orphaned"
    assert _arrangement(view)["pinned"] == [uuids["cloude_a"]]
