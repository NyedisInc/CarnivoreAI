
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest

from tests.python.federation.test_peer_listing import Reply, macs  # noqa: F401

# ruff: noqa: E402, F811
from src.api.session_record_payload import _session_record_payload
from src.core import session_sleep, session_store
from src.core.federation import peer_hosts, peer_listing, peer_serve, shadow_rows
from src.core.hosts.remote_project import bind_remote_project
from src.core.pack.machines import capabilities
from src.core.project_lineage.parents import parent_project_ids
from src.core.project_lineage.peer_parents import read_peer_project_parents
from tests.lifecycle_helpers import add_row

UID_PARENT = "11111111111111111111111111111111"
UID_CHILD = "22222222222222222222222222222222"
UID_ASLEEP = "33333333333333333333333333333333"
UID_WT = "44444444444444444444444444444444"


def _add_project(conn, *, root: str, name: str, uid: str | None, host_key: str = "local") -> int:
    now = "2026-11-26T00:00:00Z"
    return int(
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, "
            "created_at, updated_at, last_opened_at, uid) VALUES (?, ?, ?, 'user', 'present', ?, ?, ?, ?, ?)",
            (root, root, name, host_key, now, now, now, uid),
        ).lastrowid
    )


def _wire_client(mac_a, monkeypatch) -> None:

    class Client:

        def __init__(self, other) -> None:
            self.other = other

        async def request(self, method: str, path: str, **_kw):
            if path == "/sessions/asleep":
                body = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.other.open_db)
            elif path == "/sessions/list-and-asleep":
                live_body = [i.model_dump(mode="json") for i in await self.other.list_body(as_peer=True)]
                asleep_body = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.other.open_db)
                body = {"list": live_body, "asleep": asleep_body}
            else:
                body = [i.model_dump(mode="json") for i in await self.other.list_body(as_peer=True)]
            return Reply(json.loads(json.dumps(body)))

    monkeypatch.setattr(type(mac_a), "client", lambda self, _id: Client(self.other))


def test_asleep_peer_session_preserves_project_uid_timestamps_and_adopts_stub(macs, monkeypatch) -> None:
    a, b = macs
    work_stamp = "2026-11-26T15:30:00Z"
    asleep_epoch = 1795610000
    with closing(b.open_db()) as conn:
        parent_id = _add_project(conn, root="/work/B/org", name="Org", uid=UID_PARENT)
        asleep_pid = _add_project(conn, root="/work/B/org/asleep-only", name="Asleep Only", uid=UID_ASLEEP)
        rid = add_row(conn, uuid="B-uuid-sleeper", name="carnivore_sleeper", epoch=asleep_epoch, origin="created", socket="carnivore")
        conn.execute(
            "UPDATE sessions SET working_dir = ?, project_id = ?, lifecycle = 'stopped', "
            "lifecycle_source = ?, title = ?, last_work_at = ? WHERE id = ?",
            ("/work/B/org/asleep-only", asleep_pid, session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER, "Sleeper", work_stamp, rid),
        )
        conn.commit()
    assert parent_id > 0

    served = peer_serve.serve_asleep_to_peer(b.open_db)
    assert len(served) == 1
    row = served[0]
    assert row["project_uid"] == UID_ASLEEP
    assert row["parent_project_uid"] == UID_PARENT
    assert row["last_work_at"] == work_stamp
    assert row["tmux_created_epoch"] == asleep_epoch

    sync_shape = peer_listing._asleep_sync_row(row)
    assert sync_shape["project_uid"] == UID_ASLEEP
    assert sync_shape["parent_project_uid"] == UID_PARENT
    assert sync_shape["last_work_at"] == work_stamp
    assert sync_shape["tmux_created_epoch"] == asleep_epoch

    with closing(a.open_db()) as conn:
        stub_id = _add_project(
            conn,
            root=f"peer://{b.install_id}/{UID_ASLEEP}",
            name="Asleep Only (Synced)",
            uid=UID_ASLEEP,
            host_key=peer_hosts.host_key_for(b.install_id),
        )
        conn.commit()

    _wire_client(a, monkeypatch)
    asyncio.run(a.list_body(as_peer=False))

    with closing(a.open_db()) as conn:
        matching_projects = conn.execute(
            "SELECT id, root, uid FROM projects WHERE uid = ? OR root LIKE '%asleep-only%'",
            (UID_ASLEEP,),
        ).fetchall()
        assert len(matching_projects) == 1
        assert int(matching_projects[0]["id"]) == stub_id
        assert matching_projects[0]["uid"] == UID_ASLEEP

        asleep_rows = [r for r in session_store.list_sessions(conn, lifecycle="stopped", include_archived=False) if session_sleep.is_asleep(r)]
        assert len(asleep_rows) == 1
        payload = _session_record_payload(asleep_rows[0])
        assert payload.project_id == stub_id
        assert payload.last_work_at == work_stamp
        assert payload.tmux_created_epoch == asleep_epoch
        assert read_peer_project_parents(conn).get(UID_ASLEEP) == UID_PARENT


def test_asleep_only_project_without_stub_mints_with_project_uid(macs, monkeypatch) -> None:
    a, b = macs
    with closing(b.open_db()) as conn:
        asleep_pid = _add_project(conn, root="/work/B/solo-sleep", name="Solo Sleep", uid=UID_ASLEEP)
        rid = add_row(conn, uuid="B-uuid-solo", name="carnivore_solo", epoch=1795610111, origin="created", socket="carnivore")
        conn.execute(
            "UPDATE sessions SET working_dir = ?, project_id = ?, lifecycle = 'stopped', "
            "lifecycle_source = ?, last_work_at = ? WHERE id = ?",
            ("/work/B/solo-sleep", asleep_pid, session_sleep.LIFECYCLE_SOURCE_SLEPT, "2026-11-26T16:00:00Z", rid),
        )
        conn.commit()

    _wire_client(a, monkeypatch)
    asyncio.run(a.list_body(as_peer=False))

    with closing(a.open_db()) as conn:
        proj = conn.execute("SELECT root, uid FROM projects WHERE root LIKE '%solo-sleep'").fetchone()
        assert proj is not None
        assert proj["uid"] == UID_ASLEEP


@pytest.mark.parametrize("mesh_on", [False, True])
def test_live_and_asleep_shadow_rows_preserve_last_work_at_and_epoch_and_clear_epoch_when_stopped(
    macs, monkeypatch, mesh_on: bool
) -> None:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", mesh_on)
    a, b = macs
    live_work = "2026-11-26T17:45:00Z"
    live_epoch = 1795620000
    with closing(b.open_db()) as conn:
        parent_id = _add_project(conn, root="/work/B", name="Work B", uid=UID_PARENT)
        child_id = _add_project(conn, root="/work/B/sub", name="Work B Sub", uid=UID_CHILD)
        conn.execute(
            "UPDATE sessions SET project_id = ?, working_dir = '/work/B/sub', last_work_at = ?, tmux_created_epoch = ? "
            "WHERE tmux_name = 'bravo'",
            (child_id, live_work, live_epoch),
        )
        conn.commit()
    assert parent_id > 0
    b.own[0] = b.own[0].model_copy(
        update={
            "project_id": child_id,
            "session": b.own[0].session.model_copy(update={"working_dir": "/work/B/sub"}),
        }
    )

    served_live = peer_serve.serve_to_peer(b.own, b.open_db)
    assert len(served_live) == 1
    assert served_live[0].project_uid == UID_CHILD
    assert served_live[0].parent_project_uid == UID_PARENT
    assert served_live[0].last_work_at == live_work
    assert served_live[0].session.tmux_created_epoch == live_epoch

    _wire_client(a, monkeypatch)
    asyncio.run(a.list_body(as_peer=False))

    with closing(a.open_db()) as conn:
        shadow = conn.execute(
            "SELECT * FROM sessions WHERE origin = 'peer' AND tmux_name = 'bravo'"
        ).fetchone()
        assert shadow is not None
        assert shadow["last_work_at"] == live_work
        assert shadow["tmux_created_epoch"] == live_epoch
        assert session_sleep.is_closed(dict(shadow)) is False

    newer_work = "2026-11-26T18:15:00Z"
    with closing(b.open_db()) as conn:
        conn.execute("UPDATE sessions SET last_work_at = ? WHERE tmux_name = 'bravo'", (newer_work,))
        conn.commit()
    peer_listing.reset()
    asyncio.run(a.list_body(as_peer=False))
    with closing(a.open_db()) as conn:
        updated = conn.execute(
            "SELECT last_work_at, tmux_created_epoch FROM sessions WHERE origin = 'peer' AND tmux_name = 'bravo'"
        ).fetchone()
        assert updated["last_work_at"] == newer_work
        assert updated["tmux_created_epoch"] == live_epoch

    b.own = []
    peer_listing.reset()
    asyncio.run(a.list_body(as_peer=False))
    with closing(a.open_db()) as conn:
        stopped = conn.execute(
            "SELECT * FROM sessions WHERE origin = 'peer' AND tmux_name = 'bravo'"
        ).fetchone()
        assert stopped["lifecycle"] == "stopped"
        assert stopped["tmux_created_epoch"] is None
        assert session_sleep.is_closed(dict(stopped)) is False


@pytest.mark.parametrize("mesh_on", [False, True])
def test_duplicate_peer_tmux_epoch_does_not_abort_sync(macs, monkeypatch, mesh_on: bool) -> None:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", mesh_on)
    a, b = macs
    host_key = peer_hosts.host_key_for(b.install_id)
    rows = [
        {"session_uuid": "u1", "row_id": 1, "name": "dup_name", "working_dir": "/work/B", "tmux_created_epoch": 1795630000},
        {"session_uuid": "u2", "row_id": 2, "name": "dup_name", "working_dir": "/work/B", "tmux_created_epoch": 1795630000},
    ]
    with closing(a.open_db()) as conn:
        shadows = shadow_rows.sync_peer(conn, host_key=host_key, peer_install_id=b.install_id, rows=rows, complete=True)
        assert "dup_name" in shadows
        epochs = sorted(
            r[0]
            for r in conn.execute("SELECT tmux_created_epoch FROM sessions WHERE origin = 'peer' AND tmux_name = 'dup_name'")
            if r[0] is not None
        )
        assert epochs == [1795630000]


def test_bind_remote_project_adopts_peer_stub_and_retags_null_uid(macs) -> None:
    a, b = macs
    host_key = peer_hosts.host_key_for(b.install_id)
    with closing(a.open_db()) as conn:
        stub_id = _add_project(conn, root=f"peer://{b.install_id}/{UID_CHILD}", name="Child Stub", uid=UID_CHILD, host_key=host_key)
        bound = bind_remote_project(
            conn, host_key, "/work/B/child", root=f"peer://{host_key}/work/B/child", project_uid=UID_CHILD
        )
        assert bound.project_id == stub_id
        assert bound.created_project is False

        legacy_id = _add_project(conn, root=f"peer://{host_key}/work/B/legacy", name="Legacy", uid=None, host_key=host_key)
        retagged = bind_remote_project(
            conn, host_key, "/work/B/legacy", root=f"peer://{host_key}/work/B/legacy", project_uid=UID_WT
        )
        assert retagged.project_id == legacy_id
        assert conn.execute("SELECT uid FROM projects WHERE id = ?", (legacy_id,)).fetchone()[0] == UID_WT


def test_peer_project_lineage_path_nesting_uid_parents_and_cycle_guards() -> None:
    rows = [
        {"id": 1, "root": "/org", "host_key": "local"},
        {"id": 2, "root": "peer://peer-a/org", "host_key": "peer-a"},
        {"id": 3, "root": "peer://peer-a/org/sub", "host_key": "peer-a"},
        {"id": 4, "root": "peer://peer-a/org/sub/deep", "host_key": "peer-a"},
        {"id": 5, "root": "peer://peer-a/orgx", "host_key": "peer-a"},
        {"id": 6, "root": "peer://peer-b/org/sub", "host_key": "peer-b"},
    ]
    assert parent_project_ids(rows) == {1: None, 2: None, 3: 2, 4: 3, 5: None, 6: None}

    stub_rows = [
        {"id": 10, "root": "/Users/demo/Org", "host_key": "local", "uid": UID_PARENT},
        {"id": 11, "root": f"peer://iid-b/{UID_CHILD}", "host_key": "peer-b", "uid": UID_CHILD},
        {"id": 12, "root": "peer://peer-b/Users/demo/dev-worktrees/feat", "host_key": "peer-b", "uid": UID_WT},
    ]
    assert parent_project_ids(stub_rows, uid_parents={UID_CHILD: UID_PARENT, UID_WT: UID_CHILD}) == {
        10: None,
        11: 10,
        12: 11,
    }

    archived_rows = [
        {"id": 20, "root": "peer://peer-b/p", "host_key": "peer-b", "uid": UID_PARENT, "archived_at": "2026-11-01"},
        {"id": 21, "root": "peer://peer-b/c", "host_key": "peer-b", "uid": UID_CHILD, "parent_project_uid": UID_PARENT},
    ]
    assert parent_project_ids(archived_rows) == {20: None, 21: None}

    self_loop = [{"id": 30, "root": "peer://peer-b/a", "host_key": "peer-b", "uid": UID_PARENT, "parent_project_uid": UID_PARENT}]
    assert parent_project_ids(self_loop) == {30: None}

    two_cycle = [
        {"id": 31, "root": "peer://peer-b/a", "host_key": "peer-b", "uid": UID_PARENT},
        {"id": 32, "root": "peer://peer-b/b", "host_key": "peer-b", "uid": UID_CHILD},
    ]
    assert parent_project_ids(two_cycle, uid_parents={UID_PARENT: UID_CHILD, UID_CHILD: UID_PARENT}) == {31: None, 32: None}

    three_cycle = [
        {"id": 41, "root": "peer://peer-b/a", "host_key": "peer-b", "uid": UID_PARENT},
        {"id": 42, "root": "peer://peer-b/b", "host_key": "peer-b", "uid": UID_CHILD},
        {"id": 43, "root": "peer://peer-b/c", "host_key": "peer-b", "uid": UID_WT},
    ]
    assert parent_project_ids(
        three_cycle, uid_parents={UID_PARENT: UID_CHILD, UID_CHILD: UID_WT, UID_WT: UID_PARENT}
    ) == {41: None, 42: None, 43: None}

    mixed_cycle = [
        {"id": 51, "root": "peer://peer-b/org", "host_key": "peer-b", "uid": UID_PARENT},
        {"id": 52, "root": "peer://peer-b/org/sub", "host_key": "peer-b", "uid": UID_CHILD},
    ]
    assert parent_project_ids(mixed_cycle, uid_parents={UID_PARENT: UID_CHILD}) == {51: None, 52: 51}
