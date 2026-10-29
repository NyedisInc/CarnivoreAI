
from __future__ import annotations

from contextlib import closing

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_forward, peer_hosts, shadow_rows

NAME = "carnivore_api"


def row(uuid, row_id, **extra):
    return {"session_uuid": uuid, "row_id": row_id, "name": NAME, "working_dir": "/w", "label": "api", **extra}


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as c:
        yield c


def peers(conn):
    a = peer_hosts.upsert(conn, install_id="iid-a", label="studio", grant_id="g", fid="f", initiator=True)
    b = peer_hosts.upsert(conn, install_id="iid-b", label="lab", grant_id="g2", fid="f2", initiator=True)
    return a, b


def test_two_peers_with_one_name_get_two_rows_two_uuids_and_two_wire_ids(conn):
    a, b = peers(conn)
    sa = shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[row("u-1", 1)])
    sb = shadow_rows.sync_peer(conn, host_key=b.key, peer_install_id="iid-b", complete=True, rows=[row("u-1", 1)])
    assert sa[NAME].session_id != sb[NAME].session_id
    uuids = [r[0] for r in conn.execute("SELECT session_uuid FROM sessions WHERE origin = 'peer'")]
    assert len(set(uuids)) == 2
    ta, tb = (peer_forward.resolve(conn, f"remote:{p.key}:{NAME}") for p in (a, b))
    assert ta.peer.key == a.key and tb.peer.key == b.key
    for peer, shadow in ((a, sa), (b, sb)):
        via_uuid = peer_forward.resolve(conn, conn.execute(
            "SELECT session_uuid FROM sessions WHERE id = ?", (shadow[NAME].session_id,)).fetchone()[0])
        assert via_uuid.peer.key == peer.key


def test_a_resync_or_a_stop_on_one_peer_never_touches_the_other(conn):
    a, b = peers(conn)
    shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[row("u-a", 1)])
    sb = shadow_rows.sync_peer(conn, host_key=b.key, peer_install_id="iid-b", complete=True, rows=[row("u-b", 2)])
    shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[])
    states = dict(conn.execute("SELECT host_key, lifecycle FROM sessions WHERE origin = 'peer'").fetchall())
    assert states[a.key] == "stopped" and states[b.key] == "running"
    assert conn.execute("SELECT working_dir, id FROM sessions WHERE id = ?", (sb[NAME].session_id,)).fetchone()[0] == "/w"


def test_a_moved_session_lands_in_the_project_it_left_not_a_suffixed_peer_project(conn):
    a, _ = peers(conn)
    home = conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at) "
                        "VALUES ('/w', '/w', 'api', 'adoption', 'present', 't', 't')").lastrowid
    conn.execute("INSERT INTO sessions (session_uuid, project_id, working_dir, tmux_socket, tmux_name, origin, lifecycle, "
                 "host_key, created_at, updated_at) VALUES ('u-moved', ?, '/w', 'cloude', 'carnivore_api', 'created', "
                 "'stopped', 'local', 't', 't')", (home,))
    shadow = shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[row("u-moved", 1)])
    assert shadow[NAME].project_id == home and shadow[NAME].project_name == "api"
    assert conn.execute("SELECT COUNT(*) FROM projects WHERE root LIKE 'peer://%'").fetchone()[0] == 0


def test_a_stale_shadow_held_only_by_a_torn_down_swarm_agent_is_pruned_not_retried_forever(conn):
    a, _ = peers(conn)
    sid = shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[row("u-a", 1)])[NAME].session_id
    conn.execute("INSERT INTO swarm_agents (slug, rank, display_name, job, repo_dir, memory_scope, effort, character_seed, color_slot, thread_key, session_row_id, host_key, state, torn_down_at, created_at, updated_at) "
                 "VALUES ('gone', 'task', 'gone', 'j', '/r', 'local', 'medium', 1, 1, 'agent:gone', ?, ?, 'torn_down', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                 (sid, a.key))
    shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[])
    conn.execute("UPDATE sessions SET updated_at = '2026-01-01T00:00:00Z' WHERE id = ?", (sid,))
    shadow_rows.sync_peer(conn, host_key=a.key, peer_install_id="iid-a", complete=True, rows=[])
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (sid,)).fetchone()[0] == 0
    assert conn.execute("SELECT session_row_id FROM swarm_agents WHERE slug = 'gone'").fetchone()[0] is None
