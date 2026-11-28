
from __future__ import annotations

import asyncio
from contextlib import ExitStack, closing

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts, shadow_rows
from src.core.pack.globalsync import panel, panel_groups, panel_merge
from src.core.pack.globalsync.sender import ONE_WAY, PANEL_CHANGE_CAP, PANEL_CHANGE_PATH, GlobalSync, PeerView
from src.core.pack.globalsync.store import Status

ALPHA, RECEIVER = "iid-alpha", "iid-receiver"


def open_conn(path):
    ensure_db_migrated(path)
    return closing(connect(db_path_for(path), create=False))


def add_project(conn, name, root, **cols):
    conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at) "
                 "VALUES (?, ?, ?, 'user', 'present', 't', 't', 't')", (root, root, name))
    pid = conn.execute("SELECT id FROM projects WHERE root = ?", (root,)).fetchone()[0]
    for col, value in cols.items():
        conn.execute(f"UPDATE projects SET {col} = ? WHERE id = ?", (value, pid))
    return pid


def test_receiver_ends_with_the_alphas_panel_and_keeps_its_own_view(tmp_path):
    with open_conn(tmp_path / "alpha") as alpha, open_conn(tmp_path / "recv") as recv:
        conn_company = alpha.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Nyedis', 't', 't')").lastrowid
        pid = add_project(alpha, "Carnivore.ai", "/Users/a/carnivore", company_id=conn_company, color="#8a1c00")
        puid = alpha.execute("SELECT uid FROM projects WHERE id = ?", (pid,)).fetchone()[0]
        sid = add_row(alpha, uuid="sess-1", name="carnivore_api", epoch=1)
        alpha.execute("UPDATE sessions SET project_id = ? WHERE id = ?", (pid, sid))
        alpha.commit()
        listing = [{"session_uuid": "sess-1", "row_id": sid, "name": "carnivore_api", "working_dir": "/Users/a/cloudecode",
                    "label": "api", "project_uid": puid}]

        host = peer_hosts.upsert(recv, install_id=ALPHA, label="alpha", grant_id="g", fid="f", initiator=True)
        mine = add_project(recv, "Mine", "/Users/b/mine")
        shadows = shadow_rows.sync_peer(recv, host_key=host.key, peer_install_id=ALPHA, complete=True, rows=listing)
        shadow = shadows["carnivore_api"]
        assert recv.execute("SELECT uid, display_name FROM projects WHERE id = ?", (shadow.project_id,)).fetchone()[0] == puid

        arrangement = {"pinned": ["sess-1", "layout:abc"], "order": ["sess-1"], "bands": {f"p:{pid}": ["sess-1"]}, "sections": ["pinned", "companies"],
                       "collapsed": ["rogue"]}
        doc = panel.collect(alpha, arrangement, ALPHA)
        assert doc["arrangement"]["pinned"] == [[ALPHA, "sess-1"], ["layout", "abc"]] and f"p:{puid}" in doc["arrangement"]["bands"]

        own_view = {"v": 1, "pinned": ["layout:stale"], "collapsed": ["terminals"], "mobile": {"collapsed": ["groups"]}, "bands": {}, "order": []}
        report, new = panel.apply(recv, doc, RECEIVER, own_view)
        recv.commit()

        row = recv.execute("SELECT p.display_name, p.color, c.name AS company, c.uid AS cuid FROM projects p "
                           "LEFT JOIN companies c ON c.id = p.company_id WHERE p.id = ?", (shadow.project_id,)).fetchone()
        assert (row["display_name"], row["color"], row["company"]) == ("Carnivore.ai", "#8a1c00", "Nyedis")
        assert row["cuid"] == doc["companies"][0]["uid"]
        shadow_uuid = shadow_rows.shadow_uuid(ALPHA, "sess-1")
        assert new["pinned"] == [shadow_uuid, "layout:abc"] and new["order"] == [shadow_uuid]
        assert new["bands"] == {f"p:{shadow.project_id}": [shadow_uuid]} and new["sections"] == ["pinned", "companies"]
        assert new["collapsed"] == ["terminals"] and new["mobile"] == {"collapsed": ["groups"]}
        assert recv.execute("SELECT display_name, company_id FROM projects WHERE id = ?", (mine,)).fetchone()[:] == ("Mine", None)
        assert report["companies_created"] == 1 and report["projects_updated"] == 1


MAIN, A, B = "iid-main", "iid-a", "iid-b"


class Node:

    def __init__(self, stack, tmp_path, name, iid):
        self.iid, self.conn, self.arr, self.ledger = iid, stack.enter_context(open_conn(tmp_path / name)), None, tmp_path / f"{name}-stamps.json"

    def doc(self):
        return panel_merge.doc_for_send(self.conn, self.arr, self.iid, self.ledger, member=self.iid != MAIN)

    def take(self, doc, from_main):
        report, new = panel_merge.receive(self.conn, doc, self.iid, self.arr, self.ledger, from_main=from_main)
        self.conn.commit()
        self.arr = new if new is not None else self.arr
        return report

    def company(self, uid):
        row = self.conn.execute("SELECT name FROM companies WHERE uid = ?", (uid,)).fetchone()
        return row[0] if row else None

    def project(self, uid):
        return self.conn.execute("SELECT p.display_name AS name, p.color AS color, c.name AS company FROM projects p "
                                 "LEFT JOIN companies c ON c.id = p.company_id WHERE p.uid = ?", (uid,)).fetchone()


@pytest.fixture
def trio(tmp_path, monkeypatch):
    clock = [100]
    monkeypatch.setattr(panel_merge, "now_ms", lambda: clock[0])
    with ExitStack() as stack:
        main, a, b = (Node(stack, tmp_path, n, i) for n, i in (("main", MAIN), ("a", A), ("b", B)))
        company = a.conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Nyedis', 't', 't')").lastrowid
        pid = add_project(a.conn, "Carn", "/Users/a/carn", company_id=company)
        puid = a.conn.execute("SELECT uid FROM projects WHERE id = ?", (pid,)).fetchone()[0]
        cuid = a.conn.execute("SELECT uid FROM companies WHERE id = ?", (company,)).fetchone()[0]
        sid = add_row(a.conn, uuid="sess-1", name="carnivore_api", epoch=1)
        a.conn.execute("UPDATE sessions SET project_id = ? WHERE id = ?", (pid, sid))
        a.conn.commit()
        listing = [{"session_uuid": "sess-1", "row_id": sid, "name": "carnivore_api", "working_dir": "/Users/a/carn", "label": "api",
                    "project_uid": puid}]
        for node in (main, b):
            host = peer_hosts.upsert(node.conn, install_id=A, label="a", grant_id="g", fid="f", initiator=True)
            shadow_rows.sync_peer(node.conn, host_key=host.key, peer_install_id=A, complete=True, rows=listing)
            node.conn.commit()
        for node in (a, main, b):
            node.doc()
        main.take(a.doc(), False)
        b.take(main.doc(), True)
        yield main, a, b, puid, cuid, clock


def test_an_edit_on_a_member_reaches_the_main_and_then_every_other_computer(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    a.conn.execute("UPDATE projects SET display_name = 'Carnivore.ai', color = '#8a1c00' WHERE uid = ?", (puid,))
    a.conn.execute("UPDATE companies SET name = 'Nyedis Inc' WHERE uid = ?", (cuid,))
    a.arr = {"pinned": ["sess-1"], "order": ["sess-1"]}
    a.conn.commit()
    main.take(a.doc(), False)
    assert tuple(main.project(puid)) == ("Carnivore.ai", "#8a1c00", "Nyedis Inc")
    assert main.arr["pinned"] == [shadow_rows.shadow_uuid(A, "sess-1")]
    forwarded = main.doc()
    assert puid in {p["uid"] for p in forwarded["projects"]} and forwarded["stamps"][f"p:{puid}:name"] == [1000, A]
    b.take(forwarded, True)
    assert tuple(b.project(puid)) == ("Carnivore.ai", "#8a1c00", "Nyedis Inc")
    assert b.arr["pinned"] == [shadow_rows.shadow_uuid(A, "sess-1")] and b.arr["order"] == b.arr["pinned"]


def test_the_newer_stamp_wins_in_either_direction(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    main.conn.execute("UPDATE companies SET name = 'Main Name' WHERE uid = ?", (cuid,))
    main.conn.commit()
    old_main = main.doc()
    clock[0] = 1500
    b.conn.execute("UPDATE companies SET name = 'B Name' WHERE uid = ?", (cuid,))
    b.conn.commit()
    old_b = b.doc()
    clock[0] = 2000
    a.conn.execute("UPDATE companies SET name = 'A Name' WHERE uid = ?", (cuid,))
    a.conn.commit()
    newest = a.doc()
    a.take(old_main, True)
    assert a.company(cuid) == "A Name"
    main.take(old_b, False)
    assert main.company(cuid) == "B Name"
    main.take(newest, False)
    assert main.company(cuid) == "A Name"
    b.take(main.doc(), True)
    assert b.company(cuid) == "A Name"
    main.take(old_b, False)
    b.take(old_main, True)
    assert (main.company(cuid), b.company(cuid)) == ("A Name", "A Name")
    assert panel_merge.Ledger(main.ledger).stamp(f"c:{cuid}:name") == (2000, A)


def test_applying_a_received_document_is_not_an_edit(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    a.conn.execute("UPDATE companies SET name = 'Nyedis Inc' WHERE uid = ?", (cuid,))
    a.arr = {"pinned": ["sess-1"]}
    a.conn.commit()
    a_doc = a.doc()
    for node, doc, from_main in ((main, a_doc, False), (b, None, True)):
        clock[0] += 500
        node.take(doc if doc is not None else main.doc(), from_main)
        ledger = panel_merge.Ledger(node.ledger)
        assert ledger.pending is False
        flat = panel_merge.flatten(panel_merge.local_doc(node.conn, node.arr, node.iid, ledger, node.iid != MAIN))
        assert panel_merge.observe(ledger, flat, node.iid, clock[0] + 1) == 0
        assert ledger.stamp(f"c:{cuid}:name") == (1000, A)
    before = panel_merge.Ledger(main.ledger).fields
    clock[0] += 500
    assert main.take(b.doc(), False) == {"companies_created": 0, "companies_updated": 0, "projects_updated": 0, "groups_changed": 0, "layouts_changed": 0, "skipped": []}
    assert panel_merge.Ledger(main.ledger).fields == before


class _Wire:

    def __init__(self):
        self.calls = []

    def for_peer(self, _iid, _timeout):
        async def request(method, path, json=None):
            self.calls.append((method, path))
            return 200, {"report": {}}
        return request


def _member_sender(tmp_path, wire, *, one_way, pending):
    state = {"pending": pending}
    return GlobalSync(settings=lambda: {"enabled": False, "auto": False, "claude": True, "codex": True, "panel": True}, is_main=lambda: False,
                      peers=lambda: [PeerView(MAIN, "main", True, [PANEL_CHANGE_CAP])], approved=lambda _i: True, allows=lambda _i: True,
                      contained=lambda _i: False, accounts=lambda: [], request_for=wire.for_peer, status=Status(tmp_path / "s.json"),
                      outbox=tmp_path / "out", home=tmp_path, notify=lambda: None, panel_doc=lambda: {"v": 1}, panel_status=Status(tmp_path / "p.json"),
                      main_id=lambda: MAIN, one_way_toward=lambda _i: one_way, panel_pending=lambda: state["pending"],
                      panel_sent=lambda: state.update(pending=False)), state


def test_a_one_way_computer_sends_nothing_and_a_member_sends_only_a_waiting_edit(tmp_path):
    wire = _Wire()
    sender, _ = _member_sender(tmp_path, wire, one_way=True, pending=True)
    assert asyncio.run(sender.send_changes(force=True)) == ONE_WAY and wire.calls == []
    sender, state = _member_sender(tmp_path, wire, one_way=False, pending=False)
    assert asyncio.run(sender.send_changes()) == "unchanged" and wire.calls == []
    state["pending"] = True
    assert asyncio.run(sender.send_changes()) == "synced" and wire.calls == [("POST", PANEL_CHANGE_PATH)]
    assert state["pending"] is False and asyncio.run(sender.send_changes()) == "unchanged" and len(wire.calls) == 1


def test_member_edit_of_a_copy_of_the_mains_project_reaches_the_main_and_sticks(trio):
    main, a, b, puid, cuid, clock = trio
    qid = add_project(main.conn, "MainProj", "/Users/m/q")
    quid = main.conn.execute("SELECT uid FROM projects WHERE id = ?", (qid,)).fetchone()[0]
    sid = add_row(main.conn, uuid="m-sess", name="carnivore_m", epoch=1)
    main.conn.execute("UPDATE sessions SET project_id = ? WHERE id = ?", (qid, sid))
    main.conn.commit()
    host = peer_hosts.upsert(b.conn, install_id=MAIN, label="main", grant_id="g2", fid="f2", initiator=True)
    shadow_rows.sync_peer(b.conn, host_key=host.key, peer_install_id=MAIN, complete=True,
                          rows=[{"session_uuid": "m-sess", "row_id": sid, "name": "carnivore_m", "working_dir": "/Users/m/q",
                                 "label": "m", "project_uid": quid}])
    b.conn.commit()
    clock[0] = 1000
    main.doc(); b.doc()
    clock[0] = 2000
    b.conn.execute("UPDATE projects SET display_name = 'Doom Name', color = '#123456' WHERE uid = ?", (quid,))
    b.conn.commit()
    sent = b.doc()
    assert quid in {p["uid"] for p in sent["projects"]} and panel_merge.pending(b.ledger)
    main.take(sent, False)
    assert tuple(main.project(quid))[:2] == ("Doom Name", "#123456")
    clock[0] = 3000
    main.conn.execute("UPDATE companies SET name = 'Other' WHERE uid = ?", (cuid,))
    main.conn.commit()
    b.take(main.doc(), True)
    assert tuple(b.project(quid))[:2] == ("Doom Name", "#123456")


def test_member_pin_edit_keeps_the_pins_of_sessions_it_cannot_see(trio):
    main, a, b, puid, cuid, clock = trio
    b.conn.execute("DELETE FROM peer_sessions")
    b.conn.execute("DELETE FROM sessions WHERE origin = 'peer'")
    b.conn.commit()
    clock[0] = 1000
    held = shadow_rows.shadow_uuid(A, "sess-1")
    main.arr = {"pinned": [held], "order": [held]}
    b.take(main.doc(), True)
    add_row(b.conn, uuid="b-sess", name="carnivore_b", epoch=1)
    b.conn.commit()
    clock[0] = 2000
    b.arr = {**b.arr, "pinned": list(b.arr.get("pinned") or []) + ["b-sess"]}
    sent = b.doc()
    assert [A, "sess-1"] in sent["arrangement"]["pinned"] and [B, "b-sess"] in sent["arrangement"]["pinned"]
    main.take(sent, False)
    assert held in main.arr["pinned"] and shadow_rows.shadow_uuid(B, "b-sess") in main.arr["pinned"]


def test_arrangement_rebaseline_leaves_a_later_edit_visible(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    for name in ("m-sess", "later"):
        add_row(main.conn, uuid=name, name=f"carnivore_{name}", epoch=1)
    main.conn.commit()
    main.arr = {"pinned": ["m-sess"]}
    main.doc()
    committed = {"pinned": ["m-sess"]}
    clock[0] = 2000
    main.arr = {"pinned": ["m-sess", "later"]}
    panel_merge.rebaseline(main.conn, committed, MAIN, main.ledger)
    main.doc()
    assert panel_merge.Ledger(main.ledger).stamp("a:pinned")[0] == 2000


def test_send_path_reads_the_arrangement_inside_the_lock(trio):
    main, a, b, puid, cuid, clock = trio
    seen = []

    def read():
        seen.append(panel_merge.LOCK._is_owned())
        return None

    panel_merge.doc_for_send(main.conn, read, MAIN, main.ledger)
    assert seen == [True]


def _groups(node):
    rows = node.conn.execute("SELECT id, group_uuid, name FROM session_groups ORDER BY position, group_uuid").fetchall()
    members = {}
    for gid, uuid in node.conn.execute("SELECT group_id, session_uuid FROM session_group_membership ORDER BY group_id, position, session_uuid"):
        members.setdefault(gid, []).append(uuid)
    return {r["group_uuid"]: (r["name"], members.get(r["id"], [])) for r in rows}, [r["group_uuid"] for r in rows]


def _make_group(node, uid, name, members=()):
    gid = node.conn.execute("INSERT INTO session_groups (group_uuid, name, position, created_at) VALUES (?, ?, "
                            "(SELECT COALESCE(MAX(position), -1) + 1 FROM session_groups), 't')", (uid, name)).lastrowid
    for index, uuid in enumerate(members):
        node.conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) VALUES (?, ?, ?, 't')", (uuid, gid, index))
    node.conn.commit()


G1, G2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def test_group_created_on_alpha_appears_on_member_and_edits_reach_back(trio):
    main, a, b, puid, cuid, clock = trio
    held = shadow_rows.shadow_uuid(A, "sess-1")
    clock[0] = 1000
    _make_group(main, G1, "infra", [held])
    main.arr = {"bands": {f"g:{G1}": [held]}}
    b.take(main.doc(), True)
    assert _groups(b)[0] == {G1: ("infra", [held])} and b.arr["bands"][f"g:{G1}"] == [held]
    assert panel_merge.Ledger(b.ledger).pending is False
    clock[0] = 2000
    b.conn.execute("UPDATE session_groups SET name = 'infra team' WHERE group_uuid = ?", (G1,))
    add_row(b.conn, uuid="b-sess", name="carnivore_b", epoch=1)
    b.conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) "
                   "VALUES ('b-sess', (SELECT id FROM session_groups WHERE group_uuid = ?), 5, 't')", (G1,))
    b.conn.commit()
    assert panel_merge.pending(b.ledger) is False
    sent = b.doc()
    assert panel_merge.pending(b.ledger) is True
    main.take(sent, False)
    assert _groups(main)[0] == {G1: ("infra team", [held, shadow_rows.shadow_uuid(B, "b-sess")])}
    clock[0] = 3000
    a.take(main.doc(), True)
    assert _groups(a)[0][G1][0] == "infra team" and _groups(a)[0][G1][1][0] == "sess-1"


def test_member_group_edit_keeps_the_members_it_cannot_see(trio):
    main, a, b, puid, cuid, clock = trio
    b.conn.execute("DELETE FROM peer_sessions")
    b.conn.execute("DELETE FROM sessions WHERE origin = 'peer'")
    b.conn.commit()
    held = shadow_rows.shadow_uuid(A, "sess-1")
    clock[0] = 1000
    _make_group(main, G1, "infra", [held])
    b.take(main.doc(), True)
    clock[0] = 2000
    b.conn.execute("UPDATE session_groups SET name = 'renamed on b' WHERE group_uuid = ?", (G1,))
    b.conn.commit()
    sent = b.doc()
    assert sent["groups"][0]["members"] == [[A, "sess-1"]]
    main.take(sent, False)
    assert _groups(main)[0] == {G1: ("renamed on b", [held])}


def test_group_echo_does_not_bounce_and_order_follows_the_newer_edit(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    _make_group(main, G1, "one")
    _make_group(main, G2, "two")
    b.take(main.doc(), True)
    assert _groups(b)[1] == [G1, G2]
    before = panel_merge.Ledger(main.ledger).fields
    clock[0] = 1500
    assert main.take(b.doc(), False)["groups_changed"] == 0
    assert panel_merge.Ledger(main.ledger).fields == before and panel_merge.pending(b.ledger) is False
    clock[0] = 2000
    b.conn.execute("UPDATE session_groups SET position = 9 WHERE group_uuid = ?", (G1,))
    b.conn.commit()
    main.take(b.doc(), False)
    assert _groups(main)[1] == [G2, G1]


def test_group_deletion_propagates_and_is_not_resurrected(trio):
    main, a, b, puid, cuid, clock = trio
    clock[0] = 1000
    _make_group(main, G1, "gone soon")
    b.take(main.doc(), True)
    a.take(main.doc(), True)
    clock[0] = 2000
    main.conn.execute("DELETE FROM session_groups WHERE group_uuid = ?", (G1,))
    main.conn.commit()
    tomb = main.doc()
    assert [g for g in tomb["groups"] if g["uid"] == G1][0]["gone"] is True
    clock[0] = 2500
    b.take(tomb, True)
    assert _groups(b)[0] == {}
    stale = a.doc()
    main.take(stale, False)
    assert _groups(main)[0] == {}
    a.take(main.doc(), True)
    assert _groups(a)[0] == {}
    clock[0] = 3000
    _make_group(b, G2, "b group")
    main.take(b.doc(), False)
    a.take(main.doc(), True)
    clock[0] = 4000
    a.conn.execute("DELETE FROM session_groups WHERE group_uuid = ?", (G2,))
    a.conn.commit()
    main.take(a.doc(), False)
    assert _groups(main)[0] == {}


def test_a_session_moved_between_groups_ends_in_the_group_with_the_newer_edit(trio):
    main, a, b, puid, cuid, clock = trio
    held = shadow_rows.shadow_uuid(A, "sess-1")
    clock[0] = 1000
    _make_group(main, G1, "one")
    _make_group(main, G2, "two")
    b.take(main.doc(), True)
    clock[0] = 1500
    main.conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) "
                      "VALUES (?, (SELECT id FROM session_groups WHERE group_uuid = ?), 0, 't')", (held, G2))
    main.conn.commit()
    main.doc()
    clock[0] = 2000
    b.conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) "
                   "VALUES (?, (SELECT id FROM session_groups WHERE group_uuid = ?), 0, 't')", (held, G1))
    b.conn.commit()
    main.take(b.doc(), False)
    assert _groups(main)[0] == {G1: ("one", [held]), G2: ("two", [])}


def test_a_group_made_after_a_receive_commit_is_found_as_an_edit(trio):
    main, a, b, puid, cuid, clock = trio
    main.doc()
    panel_merge.clear_pending(main.ledger)
    clock[0] = 2000
    _make_group(main, G1, "late")
    panel_merge.rebaseline(main.conn, {}, MAIN, main.ledger)
    main.doc()
    assert panel_merge.pending(main.ledger) is True and panel_merge.Ledger(main.ledger).stamp(f"g:{G1}:name")[0] == 2000


def test_deleted_group_markers_have_their_own_limit_newest_first(trio):
    main, a, b, puid, cuid, clock = trio
    _make_group(main, G1, "live")
    uids = [f"{i:08x}-0000-4000-8000-000000000000" for i in range(1, panel_groups.MAX_TOMBS + 60)]
    known = {u: i + 1 for i, u in enumerate(uids)}
    known[G2] = 1 << 62
    groups, order = panel_groups.collect(main.conn, lambda keys: [], {}, known)
    gone = [g["uid"] for g in groups if g["gone"]]
    assert order == [G1] and len(gone) == panel_groups.MAX_TOMBS and gone[0] == G2
    flat = panel_merge.flatten({"groups": groups})
    assert f"g:{G2}:gone" in flat and f"g:{G1}:name" in flat
