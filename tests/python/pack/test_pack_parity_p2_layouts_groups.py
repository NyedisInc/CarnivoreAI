
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import resource_push, session_change_notice
from src.core.computers import direction
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, shadow_rows
from src.core.layouts import broadcast as layout_broadcast
from src.core.layouts import store as layouts_store
from src.core.layouts import style as layout_style
from src.core.pack.globalsync import panel_apply, panel_groups, panel_merge
from src.core.pack.machines import capabilities as caps, config_state, restrictions
from src.core.pack.meshdata import gossip, panel_kind
from src.core.resource_push import topics
from src.core.session_group_membership import assign_layout
from src.core import session_group_store
from tests.python.pack.test_mesh_panel import Mesh, u36, uid


@pytest.fixture()
def mesh_factory(tmp_path: Path, monkeypatch: Any) -> Any:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(
        restrictions=lambda: restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=True)
    ))

    async def quiet(_state: Any, _report: Any, _result: Any) -> bool:
        return False

    monkeypatch.setattr(panel_apply, "announce", quiet)
    return lambda *names, **kw: Mesh(tmp_path, *names, **kw)


def _sync_peer_sessions(src: Any, dst: Any, sess_uuids: List[str]) -> None:
    with closing(src.db()) as sconn:
        rows = []
        for suuid in sess_uuids:
            row = sconn.execute("SELECT id, tmux_name FROM sessions WHERE session_uuid = ?", (suuid,)).fetchone()
            rows.append({
                "session_uuid": suuid,
                "row_id": int(row["id"]),
                "name": row["tmux_name"],
                "working_dir": "/Users/a/work",
                "label": row["tmux_name"],
            })
    with closing(dst.db()) as dconn:
        host = peer_hosts.upsert(dconn, install_id=src.iid, label="src", grant_id="g-src", fid="f-src", initiator=True)
        add_row(dconn, uuid=u36(999), name="dst_offset_1", epoch=1)
        add_row(dconn, uuid=u36(998), name="dst_offset_2", epoch=1)
        shadow_rows.sync_peer(dconn, host_key=host.key, peer_install_id=src.iid, complete=True, rows=rows)
        dconn.commit()


def _create_layout_on(node: Any, layout_uuid: str, name: str, row_ids: List[int], *, style: Tuple[str, Any, str], off_row_ids: List[int] = ()) -> None:
    slots = [f"terminal:row:{rid}" for rid in row_ids]
    shape = {"layout": None, "groups": {slots[0]: {"tabs": slots}}}
    with closing(node.db()) as conn:
        top = int(conn.execute("SELECT COALESCE(MAX(position), -1) FROM layouts").fetchone()[0])
        lid = int(conn.execute(
            "INSERT INTO layouts (layout_uuid, name, name_fold, position, shape, revision, source_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, NULL, 't', 't')",
            (layout_uuid, name, layouts_store.fold_name(name), top + 1, json.dumps(shape)),
        ).lastrowid)
        for pos, rid in enumerate(row_ids):
            conn.execute("INSERT INTO layout_members (layout_id, session_row_id, position) VALUES (?, ?, ?)", (lid, rid, pos))
        layout_style.write(conn, layout_uuid, style[0], style[1], style[2], now="t")
        for rid in off_row_ids:
            conn.execute("INSERT INTO layout_broadcast_off (layout_id, session_row_id, updated_at) VALUES (?, ?, 't')", (lid, rid))
        conn.commit()


def test_panel_kind_grammar_and_is_tomb_for_layouts_and_groups() -> None:
    guid, luuid, iid, suuid = u36(10), u36(20), u36(30), u36(40)
    style = {"colour": "teal", "gradient": "tide", "animation": "shimmer"}
    rule = {"flags": ["running", "coffee"], "prefix": "api", "suffix": ""}
    shape = {"layout": None, "groups": {f"terminal:peer:{iid}/{suuid}": {"tabs": [f"terminal:peer:{iid}/{suuid}"]}}}

    assert panel_kind.CAP == 32768
    assert panel_kind.ORIGIN_CAP == 16384
    assert panel_kind.RESERVE == 4096

    assert panel_kind.is_tomb({"pos": None}) is True
    assert panel_kind.is_tomb({"pos": None, "bc": False}) is True
    assert panel_kind.is_tomb({"pos": "V", "bc": False}) is False
    assert panel_kind.is_tomb(style) is False
    assert panel_kind.is_tomb(rule) is False
    assert panel_kind.is_tomb(shape) is False
    assert panel_kind.is_tomb(True) is False

    assert panel_kind.valid_shape(style) and panel_kind.valid(f"g:{guid}:style", style)
    assert panel_kind.valid_shape(rule) and panel_kind.valid(f"g:{guid}:rule", rule)
    assert panel_kind.valid(f"g:{guid}:parent_key", f"cu:{uid(1)}")
    assert panel_kind.valid(f"g:{guid}:parent_key", None)
    assert panel_kind.valid(f"g:{guid}:icon", "flask")
    assert panel_kind.valid(f"g:{guid}:icon", None)
    assert panel_kind.valid(f"ly:{luuid}:name", "API + Web")
    assert panel_kind.valid_shape(shape) and panel_kind.valid(f"ly:{luuid}:shape", shape)
    assert panel_kind.valid(f"ly:{luuid}:style", style)
    assert panel_kind.valid(f"ly:{luuid}:gone", True)
    assert panel_kind.valid(f"l:lo:{luuid}", {"pos": "V"})
    assert panel_kind.valid(f"l:lm.{luuid}:{iid}/{suuid}", {"pos": "V", "bc": False})
    assert panel_kind.valid(f"l:lm.{luuid}:{iid}/{suuid}", {"pos": "V"})
    assert panel_kind.valid(f"l:lm.{luuid}:{iid}/{suuid}", {"pos": None})
    assert panel_kind.valid(f"l:pin:ly/{luuid}", {"pos": "V"})
    assert panel_kind.valid(f"l:gm.{guid}:ly/{luuid}", {"pos": "V"})
    assert panel_kind.valid(f"l:gb.{guid}:ly/{luuid}", {"pos": "V"})

    assert not panel_kind.valid_shape({"pos": "V", "x": 1})
    assert not panel_kind.valid(f"l:pin:{iid}/{suuid}", {"pos": "V", "bc": False})
    assert not panel_kind.valid(f"g:{guid}:style", {"colour": "not-a-colour"})
    assert not panel_kind.valid(f"g:{guid}:rule", {"flags": ["bogus_flag"]})
    assert not panel_kind.valid(f"ly:{luuid}:shape", {"blob": "x" * 5000})


def test_saved_layouts_full_mesh_sync_order_pins_broadcast_and_tombstone(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b")
    a, b = m["a"], m["b"]
    s1, s2, s3 = u36(1), u36(2), u36(3)
    ly1, ly2 = u36(51), u36(52)

    with closing(a.db()) as conn:
        r1 = add_row(conn, uuid=s1, name="sess_one", epoch=1)
        r2 = add_row(conn, uuid=s2, name="sess_two", epoch=1)
        r3 = add_row(conn, uuid=s3, name="sess_three", epoch=1)
        conn.commit()
    _sync_peer_sessions(a, b, [s1, s2, s3])

    _create_layout_on(a, ly1, "API + Web", [r1, r2], style=("teal", "tide", "shimmer"), off_row_ids=[r2])
    _create_layout_on(a, ly2, "Ops Trio", [r2, r3], style=("#6c799f", None, "pulse"))
    a.arrangement(pinned=[f"layout:{ly1}", s1])

    m.seed_all()
    m.converge(("a", "b"))
    b.step()
    b.step()
    assert b.own_rows() == []

    sh1 = shadow_rows.shadow_uuid(a.iid, s1)
    sh2 = shadow_rows.shadow_uuid(a.iid, s2)
    sh3 = shadow_rows.shadow_uuid(a.iid, s3)
    with closing(b.db()) as conn:
        b_r1 = int(conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (sh1,)).fetchone()[0])
        b_r2 = int(conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (sh2,)).fetchone()[0])
        assert b_r1 != r1 and b_r2 != r2
        got = layouts_store.list_layouts(conn)

    assert [ly.layout_uuid for ly in got] == [ly1, ly2]
    assert got[0].name == "API + Web"
    assert (got[0].colour, got[0].gradient, got[0].animation) == ("teal", "tide", "shimmer")
    assert [(mem.session_uuid, mem.broadcast) for mem in got[0].members] == [(sh1, True), (sh2, False)]
    assert got[0].shape == {"layout": None, "groups": {f"terminal:row:{b_r1}": {"tabs": [f"terminal:row:{b_r1}", f"terminal:row:{b_r2}"]}}}
    assert got[1].name == "Ops Trio"
    assert (got[1].colour, got[1].gradient, got[1].animation) == ("#6c799f", None, "pulse")
    assert [(mem.session_uuid, mem.broadcast) for mem in got[1].members] == [(sh2, True), (sh3, True)]
    assert b.ui.arr["pinned"] == [f"layout:{ly1}", sh1]

    with closing(a.db()) as conn:
        layout_broadcast.set_member_broadcast(conn, ly1, s2, True)
        layout_broadcast.set_member_broadcast(conn, ly1, s1, False)
        layouts_store.set_order(conn, [ly2, ly1])
        conn.commit()
    m.now += 1000
    a.step()
    m.converge(("a", "b"))
    b.step()
    with closing(b.db()) as conn:
        got2 = layouts_store.list_layouts(conn)
    assert [ly.layout_uuid for ly in got2] == [ly2, ly1]
    assert [(mem.session_uuid, mem.broadcast) for mem in got2[1].members] == [(sh1, False), (sh2, True)]

    with closing(a.db()) as conn:
        layouts_store.delete_layout(conn, ly1)
        conn.commit()
    a.arrangement(pinned=[s1])
    m.now += 1000
    a.step()
    assert a.rows()[f"ly:{ly1}:gone"][0] is True
    m.converge(("a", "b"))
    b.step()
    with closing(b.db()) as conn:
        assert [ly.layout_uuid for ly in layouts_store.list_layouts(conn)] == [ly2]
    assert b.ui.arr["pinned"] == [sh1]

    m.now += panel_kind.TOMB_TTL_MS + 10_000
    assert m.stores["b"].gc(m.now) >= 0
    assert b.rows()[f"ly:{ly1}:gone"][0] is True


def test_session_group_full_fidelity_style_icon_rule_filed_layout_and_portable_parents(mesh_factory: Any) -> None:
    m = mesh_factory("a", "b")
    a, b = m["a"], m["b"]
    s1, s2 = u36(11), u36(12)
    ly1 = u36(61)
    g_co, g_proj, g_nested, g_ly = u36(71), u36(72), u36(73), u36(74)
    co_uid, proj_uid = uid(101), uid(102)

    with closing(b.db()) as conn:
        conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Spacer1', ?, 't', 't')", (uid(901),))
        conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Spacer2', ?, 't', 't')", (uid(902),))
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at, uid) "
                     "VALUES ('/tmp/s1', '/tmp/s1', 'SpacerP1', 'user', 'present', 't', 't', 't', ?)", (uid(903),))
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at, uid) "
                     "VALUES ('/tmp/s2', '/tmp/s2', 'SpacerP2', 'user', 'present', 't', 't', 't', ?)", (uid(904),))
        conn.commit()

    with closing(a.db()) as conn:
        a_cid = int(conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Nyedis', ?, 't', 't')", (co_uid,)).lastrowid)
        a_pid = int(conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, presence, company_id, created_at, updated_at, last_opened_at, uid) "
            "VALUES ('/Users/a/proj', '/Users/a/proj', 'CoreProj', 'user', 'present', ?, 't', 't', 't', ?)",
            (a_cid, proj_uid),
        ).lastrowid)
        r1 = add_row(conn, uuid=s1, name="g_sess_1", epoch=1)
        r2 = add_row(conn, uuid=s2, name="g_sess_2", epoch=1)
        conn.commit()
    _sync_peer_sessions(a, b, [s1, s2])
    _create_layout_on(a, ly1, "Dev Pair", [r1, r2], style=("rose", None, "none"))

    with closing(a.db()) as conn:
        for pos, (guid, name, pkey) in enumerate((
            (g_co, "CoGroup", f"c:{a_cid}"),
            (g_proj, "ProjGroup", f"p:{a_pid}"),
            (g_nested, "SubGroup", f"g:{g_co}"),
            (g_ly, "LayoutGroup", f"layout:{ly1}"),
        )):
            conn.execute(
                "INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at, parent_key) VALUES (?, ?, ?, 't', 't', ?)",
                (guid, name, pos, pkey),
            )
        conn.commit()
        session_group_store.set_group_style(conn, g_co, "coral", "ember", "shimmer")
        session_group_store.set_group_icon(conn, g_co, "flask")
        session_group_store.set_group_rule(conn, g_co, ["running", "coffee"], "api", "dev")
        session_group_store.assign_session(conn, s1, g_co)
        assign_layout(conn, ly1, g_co)
        session_group_store.set_group_style(conn, g_proj, "#123456", None, "pulse")
        session_group_store.set_group_style(conn, g_nested, "gold", "dusk", "none")
        session_group_store.set_group_style(conn, g_ly, "violet", "neon", "shimmer")
        conn.commit()

    m.seed_all()
    m.converge(("a", "b"))
    b.step()
    b.step()
    assert b.own_rows() == []

    sh1 = shadow_rows.shadow_uuid(a.iid, s1)
    with closing(b.db()) as conn:
        b_cid = int(conn.execute("SELECT id FROM companies WHERE uid = ?", (co_uid,)).fetchone()[0])
        b_pid = int(conn.execute("SELECT id FROM projects WHERE uid = ?", (proj_uid,)).fetchone()[0])
        assert b_cid != a_cid and b_pid != a_pid
        groups_b = {g.group_uuid: g for g in session_group_store.list_groups(conn)}

    assert groups_b[g_co].parent_key == f"c:{b_cid}"
    assert (groups_b[g_co].style.colour, groups_b[g_co].style.gradient, groups_b[g_co].style.animation) == ("coral", "ember", "shimmer")
    assert groups_b[g_co].style.icon == "flask"
    assert groups_b[g_co].rule == {"flags": ["running", "coffee"], "prefix": "api", "suffix": "dev"}
    assert list(groups_b[g_co].member_session_uuids) == [sh1, f"layout:{ly1}"]

    assert groups_b[g_proj].parent_key == f"p:{b_pid}"
    assert (groups_b[g_proj].style.colour, groups_b[g_proj].style.gradient, groups_b[g_proj].style.animation) == ("#123456", None, "pulse")

    assert groups_b[g_nested].parent_key == f"g:{g_co}"
    assert (groups_b[g_nested].style.colour, groups_b[g_nested].style.gradient, groups_b[g_nested].style.animation) == ("gold", "dusk", "none")

    assert groups_b[g_ly].parent_key == f"layout:{ly1}"
    assert (groups_b[g_ly].style.colour, groups_b[g_ly].style.gradient, groups_b[g_ly].style.animation) == ("violet", "neon", "shimmer")

    with closing(a.db()) as conn:
        session_group_store.set_group_icon(conn, g_co, None)
        session_group_store.set_group_rule(conn, g_co, [], None, None)
        session_group_store.set_group_parent(conn, g_co, None)
        assign_layout(conn, ly1, None)
        conn.commit()
    m.now += 1000
    a.step()
    m.converge(("a", "b"))
    b.step()

    with closing(b.db()) as conn:
        updated = {g.group_uuid: g for g in session_group_store.list_groups(conn)}[g_co]
    assert updated.style.icon is None
    assert updated.rule is None
    assert updated.parent_key is None
    assert list(updated.member_session_uuids) == [sh1]


def test_panel_groups_skips_missing_parent_target_and_blocks_cycles(tmp_path: Path) -> None:
    state = tmp_path / "db"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    guid = u36(88)
    with closing(connect(db_path_for(state), create=False)) as conn:
        report = {"groups_changed": 0, "skipped": []}
        panel_groups.apply(
            conn,
            [{"uid": guid, "name": "Orphaned", "parent_key": f"cu:{uid(555)}", "style": {"colour": "teal", "gradient": None, "animation": "none"}, "gone": False}],
            [guid],
            lambda pairs: [],
            report,
        )
        assert conn.execute("SELECT parent_key FROM session_groups WHERE group_uuid = ?", (guid,)).fetchone()[0] is None
        panel_groups.apply(
            conn,
            [{"uid": guid, "name": "Orphaned", "parent_key": f"g:{guid}", "gone": False}],
            [guid],
            lambda pairs: [],
            report,
        )
        assert conn.execute("SELECT parent_key FROM session_groups WHERE group_uuid = ?", (guid,)).fetchone()[0] is None


def test_legacy_panel_merge_parity_for_layouts_and_full_groups(tmp_path: Path, monkeypatch: Any) -> None:
    clock = [100]
    monkeypatch.setattr(panel_merge, "now_ms", lambda: clock[0])
    s_a, s_b = tmp_path / "a", tmp_path / "b"
    s_a.mkdir()
    s_b.mkdir()
    assert ensure_db_migrated(s_a).status == "ok"
    assert ensure_db_migrated(s_b).status == "ok"
    iid_a, iid_b = "iid-main", "iid-member"
    l_a, l_b = tmp_path / "a.json", tmp_path / "b.json"
    s1, s2 = u36(201), u36(202)
    ly1, g1 = u36(210), u36(220)
    co_uid = uid(230)

    with closing(connect(db_path_for(s_a), create=False)) as ca, closing(connect(db_path_for(s_b), create=False)) as cb:
        cid_a = int(ca.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES ('Acme', ?, 't', 't')", (co_uid,)).lastrowid)
        r1 = add_row(ca, uuid=s1, name="leg_1", epoch=1)
        r2 = add_row(ca, uuid=s2, name="leg_2", epoch=1)
        ca.commit()

        host = peer_hosts.upsert(cb, install_id=iid_a, label="main", grant_id="g1", fid="f1", initiator=True)
        add_row(cb, uuid=u36(299), name="offset_row", epoch=1)
        shadow_rows.sync_peer(
            cb, host_key=host.key, peer_install_id=iid_a, complete=True,
            rows=[
                {"session_uuid": s1, "row_id": r1, "name": "leg_1", "working_dir": "/w", "label": "1"},
                {"session_uuid": s2, "row_id": r2, "name": "leg_2", "working_dir": "/w", "label": "2"},
            ],
        )
        cb.commit()

        panel_merge.doc_for_send(ca, None, iid_a, l_a, member=False)
        panel_merge.doc_for_send(cb, None, iid_b, l_b, member=True)

        clock[0] = 1000
        shape = {"layout": None, "groups": {f"terminal:row:{r1}": {"tabs": [f"terminal:row:{r1}", f"terminal:row:{r2}"]}}}
        lid = int(ca.execute(
            "INSERT INTO layouts (layout_uuid, name, name_fold, position, shape, revision, source_key, created_at, updated_at) "
            "VALUES (?, 'LegacyLay', 'legacylay', 0, ?, 1, NULL, 't', 't')",
            (ly1, json.dumps(shape)),
        ).lastrowid)
        ca.execute("INSERT INTO layout_members (layout_id, session_row_id, position) VALUES (?, ?, 0)", (lid, r1))
        ca.execute("INSERT INTO layout_members (layout_id, session_row_id, position) VALUES (?, ?, 1)", (lid, r2))
        ca.execute("INSERT INTO layout_broadcast_off (layout_id, session_row_id, updated_at) VALUES (?, ?, 't')", (lid, r2))
        layout_style.write(ca, ly1, "orange", "ember", "pulse", now="t")
        ca.execute(
            "INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at, parent_key) VALUES (?, 'LegacyGrp', 0, 't', 't', ?)",
            (g1, f"c:{cid_a}"),
        )
        ca.commit()
        session_group_store.set_group_style(ca, g1, "green", "tide", "shimmer")
        session_group_store.set_group_icon(ca, g1, "rocket")
        session_group_store.set_group_rule(ca, g1, ["pinned"], "pre", "suf")
        assign_layout(ca, ly1, g1)
        ca.commit()

        doc_a = panel_merge.doc_for_send(ca, {"pinned": [f"layout:{ly1}"]}, iid_a, l_a, member=False)
        report, new_arr = panel_merge.receive(cb, doc_a, iid_b, None, l_b, from_main=True)
        cb.commit()
        assert report["layouts_changed"] >= 1 and report["groups_changed"] >= 1
        assert new_arr is not None and new_arr["pinned"] == [f"layout:{ly1}"]

        got_ly = layouts_store.get_layout(cb, ly1)
        assert got_ly.name == "LegacyLay" and (got_ly.colour, got_ly.gradient, got_ly.animation) == ("orange", "ember", "pulse")
        assert [(mem.session_uuid, mem.broadcast) for mem in got_ly.members] == [
            (shadow_rows.shadow_uuid(iid_a, s1), True),
            (shadow_rows.shadow_uuid(iid_a, s2), False),
        ]
        got_grp = session_group_store.list_groups(cb)[0]
        cid_b = int(cb.execute("SELECT id FROM companies WHERE uid = ?", (co_uid,)).fetchone()[0])
        assert got_grp.parent_key == f"c:{cid_b}"
        assert (got_grp.style.colour, got_grp.style.gradient, got_grp.style.animation, got_grp.style.icon) == ("green", "tide", "shimmer", "rocket")
        assert got_grp.rule == {"flags": ["pinned"], "prefix": "pre", "suffix": "suf"}
        assert list(got_grp.member_session_uuids) == [f"layout:{ly1}"]

        clock[0] = 2000
        layouts_store.delete_layout(ca, ly1)
        ca.commit()
        doc_tomb = panel_merge.doc_for_send(ca, {"pinned": []}, iid_a, l_a, member=False)
        panel_merge.receive(cb, doc_tomb, iid_b, new_arr, l_b, from_main=True)
        cb.commit()
        assert layouts_store.list_layouts(cb) == []


def test_announce_publishes_layouts_notice_and_topic(monkeypatch: Any) -> None:
    events: List[str] = []
    monkeypatch.setattr(session_change_notice, "publish", lambda _s, notice: events.append(f"notice:{notice}"))
    monkeypatch.setattr(session_change_notice, "build_structural_notice", lambda kind: kind)
    monkeypatch.setattr(resource_push, "notify", lambda topic: events.append(f"notify:{topic}"))

    report = {"companies_created": 0, "companies_updated": 0, "projects_updated": 0, "groups_changed": 0, "layouts_changed": 1}
    asyncio.run(panel_apply.announce(None, report, None))
    assert events == ["notice:layouts", f"notify:{topics.LAYOUTS}"]
