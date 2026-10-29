
from __future__ import annotations

from contextlib import closing

from src.api import pack_migrate_env  # noqa: F401
from src.core import session_sleep
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack.migrate import live_agents, manifest


def _session(conn, uuid, name, lifecycle, companion_of=None):
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, working_dir, title, origin, lifecycle, lifecycle_source, "
        "agent_type, project_id, created_at, updated_at) VALUES (?, 'cloude', ?, '/tmp/p', ?, 'created', ?, 'tmux_list', 'claude', 1, "
        "'2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')", (uuid, name, name, lifecycle))
    if companion_of is not None:
        conn.execute("UPDATE sessions SET companion_of = ? WHERE id = ?", (companion_of, cur.lastrowid))
    return int(cur.lastrowid)


def test_companion_rows_are_not_exported_blocked_on_or_free_names(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                     "VALUES ('/tmp/p', '/tmp/p', 'p', 'created', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')")
        agent = _session(conn, "u-agent", "carnivore_agent", "running")
        _session(conn, "u-shell-run", "carnivore_sh-1", "running", companion_of=agent)
        _session(conn, "u-shell-stop", "carnivore_sh-2", "stopped", companion_of=agent + 100)
        conn.commit()
        project = dict(conn.execute("SELECT * FROM projects WHERE id = 1").fetchone())
        exported = manifest.collect(conn, project, str(tmp_path))["sessions"]
        assert [s["session_uuid"] for s in exported] == ["u-agent"]
        agents, blockers = live_agents.read(conn, 1)
        assert [a.session_uuid for a in agents] == ["u-agent"] and blockers == []
        assert session_sleep.companion_names(conn) == {"carnivore_sh-1", "carnivore_sh-2"}
    reserved = session_sleep.reserved_names(set())
    assert "carnivore_sh-2" in reserved and "carnivore_agent" not in reserved


def test_receive_running_check_ignores_a_companion_row(tmp_path, monkeypatch):
    import pytest

    from src.core.pack.machines import restrictions as restrict
    from src.core.pack.migrate import receive
    from src.core.pack.transport import blobs

    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    root = tmp_path / "proj"
    root.mkdir()
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at, uid, pack_state, home_install_id) "
                     "VALUES (?, ?, 'p', 'created', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'uid-1', 'replica', 'sender-1')",
                     (str(root), str(root)))
        agent = _session(conn, "u-agent", "carnivore_agent", "stopped")
        _session(conn, "u-shell-run", "carnivore_sh-1", "running", companion_of=agent)
        conn.commit()

    def env():
        return receive.TargetEnv(
            open_db=lambda: connect(db_path_for(tmp_path), create=False), state_dir=str(tmp_path), inbox=blobs.Inbox(tmp_path / "inbox"),
            install_id="me", restrictions=restrict.Restrictions, projects_dir=str(tmp_path))

    body = {"op_id": "op-1", "project_uid": "uid-1", "name": "p", "bytes_needed": 0, "dry_run": True}
    assert receive.prepare(env(), "sender-1", body)["case"] == "replica"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("UPDATE sessions SET lifecycle = 'running' WHERE session_uuid = 'u-agent'")
        conn.commit()
    with pytest.raises(receive.MigrateRefused) as refused:
        receive.prepare(env(), "sender-1", body)
    assert refused.value.code == "project_live_here"


def test_receive_name_check_ignores_a_peer_mirror_but_not_a_real_project(tmp_path, monkeypatch):
    import pytest

    from src.config import settings
    from src.core.pack.machines import restrictions as restrict
    from src.core.pack.migrate import receive
    from src.core.pack.transport import blobs

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, host_key, created_at, updated_at, uid) "
                     "VALUES ('peer://peer-ab12/Users/a/mailSorter', 'x', 'mailSorter', 'adoption', 'peer-ab12', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'mirror-uid')")
        conn.commit()

    def env():
        return receive.TargetEnv(
            open_db=lambda: connect(db_path_for(tmp_path), create=False), state_dir=str(tmp_path), inbox=blobs.Inbox(tmp_path / "inbox"),
            install_id="me", restrictions=lambda: restrict.Restrictions(may_receive_projects=True), projects_dir=str(tmp_path / "projects"))

    body = {"op_id": "op-1", "project_uid": "real-uid", "name": "mailSorter", "bytes_needed": 0, "dry_run": True}
    assert receive.prepare(env(), "sender-1", body)["case"] == "new"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                     "VALUES ('/tmp/er', '/tmp/er', 'mailSorter', 'created', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')")
        conn.commit()
    with pytest.raises(receive.MigrateRefused) as refused:
        receive.prepare(env(), "sender-1", body)
    assert refused.value.code == "project_name_taken"
