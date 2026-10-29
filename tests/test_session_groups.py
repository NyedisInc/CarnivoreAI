
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.core import session_group_store as G
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_models import SESSION_GROUP_MAX, SESSION_GROUP_NAME_MAX


@pytest.fixture()
def conn(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    c = connect(db_path_for(tmp_path))
    yield c
    c.close()


def stored(conn, name: str, *, lifecycle: str = "running", epoch: int = None) -> str:
    session_uuid = f"uuid-{name}-{lifecycle}-{epoch}"
    with conn:
        conn.execute(
            "INSERT INTO sessions "
            "(session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
            " origin, lifecycle, created_at, updated_at) "
            "VALUES (?, 'cloude', ?, ?, 'created', ?, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (session_uuid, name, epoch, lifecycle),
        )
    return session_uuid


def imported(conn, session_uuid: str) -> str:
    with conn:
        conn.execute(
            "INSERT INTO sessions "
            "(session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
            " origin, lifecycle, archived_at, created_at, updated_at) "
            "VALUES (?, 'cloude', NULL, NULL, 'imported', 'stopped', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z')",
            (session_uuid,),
        )
    return session_uuid


def test_migration_chain_reaches_v8(tmp_path: Path):
    state = ensure_db_migrated(tmp_path)
    assert state.schema_version == CURRENT_SCHEMA_VERSION
    assert state.schema_version >= 8
    assert "7->8" in state.migrations_applied
    c = connect(db_path_for(tmp_path))
    try:
        assert get_meta(c, "schema_version") == str(CURRENT_SCHEMA_VERSION)
    finally:
        c.close()


def test_v8_step_is_idempotent(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    c = connect(db_path_for(tmp_path))
    try:
        stored(c, "cloude_a")
        g = G.create_group(c, "keepme")
        G.assign(c, "cloude_a", g.group_uuid)
    finally:
        c.close()
    ensure_db_migrated(tmp_path)
    c = connect(db_path_for(tmp_path))
    try:
        groups = G.list_groups(c)
        assert [x.name for x in groups] == ["keepme"]
        assert groups[0].members == ("cloude_a",)
    finally:
        c.close()




def test_delete_group_returns_members_to_ungrouped(conn):
    g = G.create_group(conn, "work")
    for name in ("cloude_a", "cloude_b", "cloude_c"):
        stored(conn, name)
        G.assign(conn, name, g.group_uuid)

    freed = G.delete_group(conn, g.group_uuid)

    assert freed == 3, "the count the confirmation dialog quotes"
    assert G.list_groups(conn) == []
    for name in ("cloude_a", "cloude_b", "cloude_c"):
        assert G.group_of(conn, name) is None, f"{name} should be ungrouped"


def test_raw_delete_of_a_group_cannot_orphan_a_membership(conn):
    stored(conn, "cloude_a")
    g = G.create_group(conn, "work")
    G.assign(conn, "cloude_a", g.group_uuid)
    assert (
        conn.execute("SELECT COUNT(*) FROM session_group_membership").fetchone()[0] == 1
    )

    with conn:
        conn.execute("DELETE FROM session_groups WHERE group_uuid = ?", (g.group_uuid,))

    left = conn.execute("SELECT COUNT(*) FROM session_group_membership").fetchone()[0]
    assert left == 0, (
        "a membership outlived its group - ON DELETE CASCADE is not in "
        "force, and PRAGMA foreign_keys is probably off on this connection"
    )
    assert G.group_of(conn, "cloude_a") is None


def test_deleting_one_group_leaves_the_others_alone(conn):
    stored(conn, "cloude_a")
    stored(conn, "cloude_b")
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.assign(conn, "cloude_a", a.group_uuid)
    G.assign(conn, "cloude_b", b.group_uuid)

    G.delete_group(conn, a.group_uuid)

    assert [x.name for x in G.list_groups(conn)] == ["b"]
    assert G.group_of(conn, "cloude_b") == b.group_uuid




def test_a_second_assignment_moves_rather_than_duplicating(conn):
    key = stored(conn, "cloude_x")
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.assign(conn, "cloude_x", a.group_uuid)
    G.assign(conn, "cloude_x", b.group_uuid)

    rows = conn.execute(
        "SELECT COUNT(*) FROM session_group_membership WHERE session_uuid = ?",
        (key,),
    ).fetchone()[0]
    assert rows == 1, "one group per session is not being enforced"
    assert G.group_of(conn, "cloude_x") == b.group_uuid
    by_name = {g.name: g.members for g in G.list_groups(conn)}
    assert by_name["a"] == ()
    assert by_name["b"] == ("cloude_x",)


def test_the_primary_key_refuses_a_hand_written_second_membership(conn):
    key = stored(conn, "cloude_x")
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.assign(conn, "cloude_x", a.group_uuid)
    bid = conn.execute(
        "SELECT id FROM session_groups WHERE group_uuid = ?", (b.group_uuid,)
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO session_group_membership "
                "(session_uuid, group_id, position, added_at) "
                "VALUES (?, ?, 0, ?)",
                (key, bid, "2026-01-01T00:00:00Z"),
            )


def test_assign_none_returns_a_session_to_ungrouped(conn):
    stored(conn, "cloude_x")
    a = G.create_group(conn, "a")
    G.assign(conn, "cloude_x", a.group_uuid)
    G.assign(conn, "cloude_x", None)

    assert G.group_of(conn, "cloude_x") is None
    assert (
        conn.execute("SELECT COUNT(*) FROM session_group_membership").fetchone()[0] == 0
    )


def test_a_session_with_no_row_in_sessions_cannot_be_grouped(conn):
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    g = G.create_group(conn, "work")
    with pytest.raises(G.SessionNotStored):
        G.assign(conn, "cloude_never_adopted", g.group_uuid)
    assert G.group_of(conn, "cloude_never_adopted") is None


def test_a_session_with_no_tmux_name_can_be_grouped(conn):
    key = imported(conn, "imported-1")
    g = G.create_group(conn, "work")
    G.assign_session(conn, key, g.group_uuid)
    assert G.group_of_session(conn, key) == g.group_uuid
    listed = G.list_groups(conn)[0]
    assert listed.member_session_uuids == (key,)
    assert listed.members == ()


def test_two_sessions_sharing_one_name_hold_two_memberships(conn):
    dead = stored(conn, "cloude_Mac", lifecycle="stopped", epoch=1)
    live = stored(conn, "cloude_Mac", lifecycle="running", epoch=2)
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.assign_session(conn, dead, a.group_uuid)
    G.assign_session(conn, live, b.group_uuid)
    assert G.group_of_session(conn, dead) == a.group_uuid
    assert G.group_of_session(conn, live) == b.group_uuid
    assert G.group_of(conn, "cloude_Mac") == b.group_uuid


def test_member_order_is_stored_and_survives_a_round_trip(conn):
    a = stored(conn, "cloude_a")
    b = stored(conn, "cloude_b")
    c = stored(conn, "cloude_c")
    g = G.create_group(conn, "work")
    for key in (a, b, c):
        G.assign_session(conn, key, g.group_uuid)
    assert G.list_groups(conn)[0].member_session_uuids == (a, b, c)

    G.set_member_order(conn, g.group_uuid, [c, a, b])
    assert G.list_groups(conn)[0].member_session_uuids == (c, a, b)
    assert G.list_groups(conn)[0].members == ("cloude_c", "cloude_a", "cloude_b")


def test_an_omitted_member_keeps_a_position_after_every_named_one(conn):
    a = stored(conn, "cloude_a")
    b = stored(conn, "cloude_b")
    c = stored(conn, "cloude_c")
    g = G.create_group(conn, "work")
    for key in (a, b, c):
        G.assign_session(conn, key, g.group_uuid)
    G.set_member_order(conn, g.group_uuid, [c])
    assert G.list_groups(conn)[0].member_session_uuids == (c, a, b)


def test_reordering_never_files_a_stranger_into_the_group(conn):
    mine = stored(conn, "cloude_mine")
    theirs = stored(conn, "cloude_theirs")
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.assign_session(conn, mine, a.group_uuid)
    G.assign_session(conn, theirs, b.group_uuid)
    G.set_member_order(conn, a.group_uuid, [theirs, mine])
    by_name = {g.name: g.member_session_uuids for g in G.list_groups(conn)}
    assert by_name["a"] == (mine,)
    assert by_name["b"] == (theirs,)




def test_absent_tables_raise_rather_than_reading_as_no_groups():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bare.db"
        c = sqlite3.connect(path)
        try:
            with pytest.raises(G.GroupsUnavailable):
                G.list_groups(c)
            with pytest.raises(G.GroupsUnavailable):
                G.create_group(c, "x")
            with pytest.raises(G.GroupsUnavailable):
                G.assign(c, "cloude_a", None)
            with pytest.raises(G.GroupsUnavailable):
                G.group_of(c, "cloude_a")
        finally:
            c.close()


def test_half_a_migration_is_also_cannot_determine():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "half.db"
        c = sqlite3.connect(path)
        try:
            c.execute(
                "CREATE TABLE session_groups (id INTEGER PRIMARY KEY, "
                "group_uuid TEXT, name TEXT, position INTEGER, "
                "created_at TEXT, updated_at TEXT)"
            )
            with pytest.raises(G.GroupsUnavailable):
                G.list_groups(c)
        finally:
            c.close()




def test_names_are_trimmed_and_interior_whitespace_collapsed(conn):
    g = G.create_group(conn, "   work    stuff   ")
    assert g.name == "work stuff"


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_a_blank_name_is_refused(conn, bad):
    with pytest.raises(G.GroupNameInvalid):
        G.create_group(conn, bad)


def test_an_overlong_name_is_refused(conn):
    with pytest.raises(G.GroupNameInvalid):
        G.create_group(conn, "x" * (SESSION_GROUP_NAME_MAX + 1))


def test_a_name_exactly_at_the_bound_is_accepted(conn):
    g = G.create_group(conn, "x" * SESSION_GROUP_NAME_MAX)
    assert len(g.name) == SESSION_GROUP_NAME_MAX


def test_the_group_limit_is_enforced(conn):
    for i in range(SESSION_GROUP_MAX):
        G.create_group(conn, f"g{i}")
    with pytest.raises(G.GroupLimitReached):
        G.create_group(conn, "one too many")


def test_new_groups_append_rather_than_jumping_to_the_top(conn):
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    c = G.create_group(conn, "c")
    assert [g.name for g in G.list_groups(conn)] == ["a", "b", "c"]
    assert (a.position, b.position, c.position) == (0, 1, 2)


def test_set_group_order_rewrites_the_whole_order(conn):
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    c = G.create_group(conn, "c")
    G.set_group_order(conn, [c.group_uuid, a.group_uuid, b.group_uuid])
    assert [g.name for g in G.list_groups(conn)] == ["c", "a", "b"]


def test_an_omitted_group_keeps_a_position_after_every_named_one(conn):
    a = G.create_group(conn, "a")
    b = G.create_group(conn, "b")
    G.create_group(conn, "c")
    G.set_group_order(conn, [b.group_uuid, a.group_uuid])
    assert [g.name for g in G.list_groups(conn)] == ["b", "a", "c"]


def test_set_group_order_rejects_an_unknown_uuid(conn):
    G.create_group(conn, "a")
    with pytest.raises(G.GroupNotFound):
        G.set_group_order(conn, ["not-a-real-uuid"])


def test_group_order_is_total_when_positions_tie(conn):
    with conn:
        for uuid_value, name in (("zzzz-first", "a"), ("aaaa-second", "b")):
            conn.execute(
                "INSERT INTO session_groups "
                "(group_uuid, name, position, created_at, updated_at) "
                "VALUES (?, ?, 0, '2026-01-01T00:00:00Z', NULL)",
                (uuid_value, name),
            )

    assert [g.group_uuid for g in G.list_groups(conn)] == [
        "aaaa-second",
        "zzzz-first",
    ], "a position tie fell back to row order instead of to group_uuid"




@pytest.mark.parametrize(
    "call",
    [
        lambda c: G.rename_group(c, "nope", "x"),
        lambda c: G.delete_group(c, "nope"),
        lambda c: G.assign_session(c, "any-session-uuid", "nope"),
    ],
)
def test_operating_on_a_missing_group_raises(conn, call):
    with pytest.raises(G.GroupNotFound):
        call(conn)


def test_rename_keeps_membership_and_position(conn):
    stored(conn, "cloude_x")
    a = G.create_group(conn, "a")
    G.create_group(conn, "b")
    G.assign(conn, "cloude_x", a.group_uuid)
    G.rename_group(conn, a.group_uuid, "renamed")
    groups = G.list_groups(conn)
    assert [g.name for g in groups] == ["renamed", "b"]
    assert groups[0].members == ("cloude_x",)




def test_prune_refuses_an_empty_live_list(conn):
    stored(conn, "cloude_x")
    g = G.create_group(conn, "a")
    G.assign(conn, "cloude_x", g.group_uuid)
    assert G.prune_missing(conn, []) == 0
    assert G.group_of(conn, "cloude_x") == g.group_uuid


def test_prune_drops_only_the_names_that_are_gone(conn):
    stored(conn, "cloude_here")
    stored(conn, "cloude_gone")
    g = G.create_group(conn, "a")
    G.assign(conn, "cloude_here", g.group_uuid)
    G.assign(conn, "cloude_gone", g.group_uuid)
    removed = G.prune_missing(conn, ["cloude_here"])
    assert removed == 1
    assert G.group_of(conn, "cloude_here") == g.group_uuid
    assert G.group_of(conn, "cloude_gone") is None


def test_prune_never_unfiles_a_session_with_no_tmux_name(conn):
    stored(conn, "cloude_here")
    key = imported(conn, "imported-1")
    g = G.create_group(conn, "a")
    G.assign(conn, "cloude_here", g.group_uuid)
    G.assign_session(conn, key, g.group_uuid)
    assert G.prune_missing(conn, ["cloude_here"]) == 0
    assert G.group_of_session(conn, key) == g.group_uuid
