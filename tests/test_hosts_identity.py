
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest
from pydantic import create_model

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.activity_persist import write_state
from src.core.db import connect
from src.core.db_steps import STEPS
from src.core.hosts.ddl import host_scope
from src.core.session_instance_index import build_instance_index
from src.core.session_lineage import LINEAGE_FORKED, LINEAGE_UNRESOLVED, record_claude_session
from src.core.session_restart import REBIND_CONFLICT, REBIND_DONE, rebind_instance
from src.core.session_store import get_instance
from src.models.sessions import Session, SessionInfo
from tests.layouts_helpers import migrated

SOCKET, NAME, EPOCH = "carnivore", "carnivore_api", 1790000200


def _row(conn, uuid: str, host_key: str, *, name: str = NAME, epoch: int = EPOCH,
         claude_uuid=None) -> int:
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, "
        "lifecycle, host_key, claude_session_uuid, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'created', 'running', ?, ?, 'now', 'now')",
        (uuid, SOCKET, name, epoch, host_key, claude_uuid))
    return int(cur.lastrowid)


@pytest.fixture()
def conn(tmp_path):
    path = migrated(tmp_path / "state")
    with closing(connect(path, create=False)) as c:
        _row(c, "here", "local", claude_uuid="c-here")
        _row(c, "there", "hosta", claude_uuid="c-there")
        yield c


def _v39_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("BEGIN")
    for version in range(0, 39):
        STEPS[version](c)
    c.commit()
    return c


def test_the_scope_names_the_host_and_degrades_before_v40(conn):
    assert host_scope(conn, "hosta") == (" AND host_key = ?", ("hosta",))
    old = _v39_conn()
    assert host_scope(old) == ("", ())
    assert host_scope(old, "hosta") == (" AND 0", ())
    old.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, "
        "lifecycle, created_at, updated_at) VALUES ('v39', ?, ?, ?, 'created', 'running', 'n', 'n')",
        (SOCKET, NAME, EPOCH))
    assert get_instance(old, socket=SOCKET, name=NAME, epoch=EPOCH)["session_uuid"] == "v39"
    assert get_instance(old, socket=SOCKET, name=NAME, epoch=EPOCH, host_key="hosta") is None


def test_get_instance_answers_for_its_own_host(conn):
    assert get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)["session_uuid"] == "here"
    assert get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH,
                        host_key="hosta")["session_uuid"] == "there"
    assert get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH, host_key="nope") is None


def test_an_activity_write_stamps_only_its_hosts_row(conn):
    assert write_state(conn, NAME, "working", EPOCH, tmux_socket=SOCKET, now="t1") is True
    states = dict(conn.execute("SELECT session_uuid, activity_state FROM sessions").fetchall())
    assert states == {"here": "working", "there": None}


def test_a_restart_rebind_clashes_only_on_its_own_host(conn):
    spare = _row(conn, "spare", "local", name="carnivore_spare", epoch=1)
    blocked = rebind_instance(conn, row_id=spare, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert blocked.outcome == REBIND_CONFLICT
    conn.execute("DELETE FROM sessions WHERE session_uuid = 'here'")
    moved = rebind_instance(conn, row_id=spare, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert moved.outcome == REBIND_DONE, moved.detail


def test_the_listing_index_reads_only_its_hosts_rows(conn):
    here_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'here'").fetchone()[0]
    there_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'there'").fetchone()[0]
    conn.execute("UPDATE sessions SET title = 'remote title' WHERE id = ?", (there_id,))
    local = build_instance_index(conn, socket=SOCKET, names=[NAME])
    assert local.complete and local.identity(NAME, EPOCH)["id"] == here_id
    assert local.label(NAME, EPOCH) is None
    remote = build_instance_index(conn, socket=SOCKET, names=[NAME], host_key="hosta")
    assert remote.identity(NAME, EPOCH)["id"] == there_id
    assert remote.label(NAME, EPOCH) == "remote title"


def test_a_fork_row_stays_on_its_anchors_host(conn):
    result = record_claude_session(conn, socket=SOCKET, name=NAME, epoch=EPOCH,
                                   claude_uuid="c-new", source="fork", pane_left_previous=True,
                                   host_key="hosta")
    assert result.outcome == LINEAGE_FORKED, result.detail
    child = conn.execute("SELECT host_key, parent_session_id FROM sessions WHERE id = ?",
                         (result.row_id,)).fetchone()
    parent = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'there'").fetchone()[0]
    assert tuple(child) == ("hosta", parent)
    missing = record_claude_session(conn, socket=SOCKET, name=NAME, epoch=EPOCH,
                                    claude_uuid="c-other", source="fork", host_key="nope")
    assert missing.outcome == LINEAGE_UNRESOLVED


HOST_FIELDS = ("host_key", "host_label", "host_state")
FEDERATION_FIELDS = ("session_uuid", "origin_install_id", "project_uid", "company_uid")


def test_the_listing_wrapper_is_unchanged_but_for_its_trailing_host_and_federation_fields():
    assert not set(HOST_FIELDS + FEDERATION_FIELDS) & set(Session.model_fields)
    before = create_model("SessionInfoBeforeHosts", **{
        name: (field.annotation, field)
        for name, field in SessionInfo.model_fields.items() if name not in HOST_FIELDS + FEDERATION_FIELDS})
    data = {"session": Session(id="ses_1", pty_pid=1, working_dir="/w", created_at="2026-09-27T00:00:00",
                               last_activity="2026-09-27T00:00:00"),
            "tmux_session": "carnivore_api", "session_row_id": 7, "label": "api",
            "activity_status": "working", "created_by_cloude": True, "created_by_us": True}
    old_json = before(**data).model_dump_json()
    new_json = SessionInfo(**data).model_dump_json()
    assert new_json == (old_json[:-1]
                        + ',"host_key":"local","host_label":"this machine","host_state":"up"'
                        + ',"session_uuid":null,"origin_install_id":null,"project_uid":null,"company_uid":null}')
    assert list(json.loads(new_json))[-7:] == [*HOST_FIELDS, *FEDERATION_FIELDS]
