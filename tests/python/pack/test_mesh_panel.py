from __future__ import annotations

import asyncio
import base64
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.api import federation_pack_global_routes as routes
from src.core.computers import direction
from src.core.federation import mesh_powers, peer_links
from src.core.db import connect, db_path_for, get_meta, set_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation.shadow_rows import shadow_uuid
from src.core.pack.globalsync import fracindex, mesh_panel, panel, panel_apply, panel_merge, sender
from src.core.pack.globalsync.sender import PANEL_CAP, PANEL_CHANGE_CAP, GlobalSync, PeerView
from src.core.pack.globalsync.store import Status
from src.core.pack.machines import capabilities as caps, config_state
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import envelope, gossip, hlc, kinds, panel_kind, wire
from src.core.pack.meshdata.store import RecordStore
from src.core.ui_preferences.drawer_arrangement import SECTION_IDS
from src.core.relay_identity.device_key import DeviceKey, b64url

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000
DAY = 24 * 3600 * 1000


def uid(i: int) -> str:
    return f"{i:032x}"


def u36(i: int) -> str:
    return f"{i:08x}-0000-0000-0000-{i:012x}"


class Ui:

    def __init__(self) -> None:
        self.arr: Optional[dict] = None
        self.reject = False
        self.updates = 0

    def read(self) -> dict:
        return {"values": {"drawer_arrangement": self.arr}} if self.arr is not None else {}

    def update(self, patch: dict) -> Any:
        self.updates += 1
        if self.reject:
            return SimpleNamespace(status="rejected_invalid", values={})
        new = patch["drawer_arrangement"]
        status = "unchanged" if new == self.arr else "committed"
        self.arr = new
        return SimpleNamespace(status=status, values={"drawer_arrangement": new})


class Comp:

    def __init__(self, mesh: "Mesh", name: str, tmp: Path) -> None:
        self.mesh, self.name, self.dir = mesh, name, tmp / name
        self.iid = str(uuid.uuid4())
        ensure_db_migrated(self.dir)
        with closing(self.db()) as conn:
            set_meta(conn, META_INSTALL_ID, self.iid)
        self.ui = Ui()
        self.legacy = self.dir / "pack" / "panel-stamps.json"
        self.step_fn = mesh_panel.attach(SimpleNamespace(ui_preferences_store=self.ui), self.db, lambda: {"panel": True}, self.legacy)
        self.next_session = 1

    def db(self) -> Any:
        return connect(db_path_for(self.dir), create=False)

    def sql(self, text: str, *args: Any) -> None:
        with closing(self.db()) as conn:
            conn.execute(text, args)

    def project(self, name: str, puid: str, **cols: Any) -> None:
        with closing(self.db()) as conn:
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at) "
                         "VALUES (?, ?, ?, 'user', 'present', 't', 't', 't')", (f"/r/{puid}", f"/r/{puid}", name))
            conn.execute("UPDATE projects SET uid = ? WHERE root = ?", (puid, f"/r/{puid}"))
            for col, value in cols.items():
                conn.execute(f"UPDATE projects SET {col} = ? WHERE uid = ?", (value, puid))

    def session(self, i: int) -> str:
        with closing(self.db()) as conn:
            add_row(conn, uuid=u36(i), name=f"s{i}", epoch=1)
        return u36(i)

    def arrangement(self, **fields: Any) -> None:
        self.ui.arr = {**(self.ui.arr or {"v": 1}), **fields}

    def project_name(self, puid: str) -> Optional[str]:
        with closing(self.db()) as conn:
            row = conn.execute("SELECT display_name FROM projects WHERE uid = ?", (puid,)).fetchone()
        return row[0] if row else None

    def step(self) -> None:
        asyncio.run(self.step_fn(self.mesh.service(self.name), self.mesh.lst()))

    def rows(self) -> Dict[str, Any]:
        return self.mesh.stores[self.name].kind_rows(self.mesh.lst(), "panel")

    def own_rows(self) -> List[str]:
        return sorted(k for k, (_v, stamp) in self.rows().items() if stamp.iid == self.iid)


class Mesh:

    def __init__(self, tmp: Path, *names: str, no_yes: Optional[set] = None, one_way: Optional[set] = None) -> None:
        self.no_yes = no_yes or set()
        self.one_way = one_way or set()
        self.now = NOW
        self.keys = {n: DeviceKey.from_seed(bytes([i + 3]) * 32) for i, n in enumerate(names)}
        self.comps = {n: Comp(self, n, tmp) for n in names}
        self.signing = {n: Signing(install_id=self.comps[n].iid, load_key=lambda n=n: self.keys[n], pinned_key=lambda iid: None) for n in names}
        self.stores = {n: RecordStore(tmp / f"{n}-mesh.db", self.comps[n].iid, wall=lambda: self.now, signing=self.signing[n]) for n in names}
        self.alpha = names[0]

    def __getitem__(self, name: str) -> Comp:
        return self.comps[name]

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=c.iid, label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT, mesh=True,
                                 may_receive_logins=n not in self.no_yes, one_way=n in self.one_way) for n, c in self.comps.items()]
        return RosterV2(generation=1, alpha=self.comps[self.alpha].iid, home=self.comps[self.alpha].iid, issued_at=1, computers=rows)

    def service(self, name: str) -> Any:
        return SimpleNamespace(store=self.stores[name], signing=self.signing[name], pass_gen=None)

    def sync(self, src: str, dst: str) -> None:
        lst = self.lst()

        async def call(body: dict) -> dict:
            import json

            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), self.comps[src].iid, lst, self.now)
            return json.loads(json.dumps(answer))
        asyncio.run(wire.run_sync(self.stores[src], call, lst, self.comps[dst].iid, lambda: self.now))

    def converge(self, *edges: tuple, rounds: int = 3) -> None:
        for _ in range(rounds):
            for x, y in edges:
                self.sync(x, y)
                self.sync(y, x)

    def seed_all(self) -> None:
        for c in self.comps.values():
            c.step()


@pytest.fixture()
def mesh(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=lambda: SimpleNamespace(may_receive_global_setup=False, may_receive_pack_ui=True)))

    async def quiet(_state, _report, _result):
        return False

    monkeypatch.setattr(panel_apply, "announce", quiet)
    return lambda *names, **kw: Mesh(tmp_path, *names, **kw)


def test_two_computers_pinning_different_sessions_at_the_same_time_both_keep_both_pins(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    m.seed_all()
    a.session(1), b.session(2)
    a.arrangement(pinned=[u36(1)])
    b.arrangement(pinned=[u36(2)])
    a.step(), b.step()
    m.converge(("a", "b"))
    a.step(), b.step()
    pairs_a = {a.iid + "/" + u36(1), b.iid + "/" + u36(2)}
    assert set(a.ui.arr["pinned"]) == {u36(1), shadow_uuid(b.iid, u36(2))}
    assert set(b.ui.arr["pinned"]) == {shadow_uuid(a.iid, u36(1)), u36(2)}
    assert {k.split(":", 2)[2] for k in a.rows() if k.startswith("l:pin:")} == pairs_a
    assert a.ui.arr["pinned"][0] != a.ui.arr["pinned"][1] and len(b.ui.arr["pinned"]) == 2


def test_concurrent_moves_of_different_rows_survive_even_when_one_move_sits_unapplied_in_the_other_store(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    m.seed_all()
    for i in (1, 2, 3, 4):
        a.session(i)
    a.arrangement(order=[u36(i) for i in (1, 2, 3, 4)])
    a.step()
    m.converge(("a", "b"))
    b.step()
    sh = [shadow_uuid(a.iid, u36(i)) for i in (1, 2, 3, 4)]
    assert b.ui.arr["order"] == sh
    a.arrangement(order=[u36(i) for i in (2, 3, 4, 1)])
    a.step()
    m.sync("a", "b")
    b.arrangement(order=[sh[3], sh[0], sh[1], sh[2]])
    b.step()
    m.converge(("a", "b"))
    a.step(), b.step()
    assert a.ui.arr["order"] == [u36(4), u36(2), u36(3), u36(1)]
    assert b.ui.arr["order"] == [sh[3], sh[1], sh[2], sh[0]]


def test_a_rename_on_b_reaches_d_through_the_alpha_c(mesh):
    m = mesh("c", "b", "d")
    for c in m.comps.values():
        c.project("Original", uid(1))
    m.seed_all()
    m["b"].sql("UPDATE projects SET display_name = 'Renamed' WHERE uid = ?", uid(1))
    m["b"].step()
    m.converge(("c", "b"), ("c", "d"))
    m["c"].step(), m["d"].step()
    assert m["c"].project_name(uid(1)) == "Renamed" and m["d"].project_name(uid(1)) == "Renamed"


def test_a_record_forged_by_c_in_bs_name_is_refused_and_applies_nothing(mesh):
    m = mesh("a", "b", "c")
    m["c"].project("Original", uid(1))
    m.seed_all()
    key, value, stamp = f"p:{uid(1)}:name", "Forged", [NOW + 5, 0, m["b"].iid]
    sig = envelope.sign(envelope.KIND_RECORD, f"panel:{key}", stamp, envelope.body_hash(value), m.signing["c"])
    out = m.stores["c"].offer_batch({f"panel:{key}": {"v": value, "s": stamp, "sig": sig.to_dict()}}, m["c"].iid, m.lst(), m.now)
    assert (out.accepted, out.refused) == (0, 1)
    m["c"].step()
    assert m["c"].project_name(uid(1)) == "Original"


def test_an_unpinned_old_copy_and_a_deleted_groups_old_name_stay_out_after_gc(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    m.seed_all()
    a.session(1)
    a.sql("INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at) VALUES (?, 'Team', 0, 't', 't')", u36(9))
    a.arrangement(pinned=[u36(1)])
    a.step()
    old = {n: e for n, e in m.stores["a"].servable(m.lst()).items() if n.startswith("panel:")}
    m.converge(("a", "b"))
    b.step()
    assert b.ui.arr["pinned"] == [shadow_uuid(a.iid, u36(1))]
    with closing(b.db()) as conn:
        assert conn.execute("SELECT name FROM session_groups WHERE group_uuid = ?", (u36(9),)).fetchone()[0] == "Team"
    a.arrangement(pinned=[])
    a.sql("DELETE FROM session_groups WHERE group_uuid = ?", u36(9))
    m.now += 1000
    a.step()
    m.converge(("a", "b"))
    b.step()
    assert b.ui.arr["pinned"] == []
    with closing(b.db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] == 0
    m.now += 31 * DAY
    for n in ("a", "b"):
        m.stores[n].gc(m.now)
    m.stores["b"].offer_batch(old, a.iid, m.lst(), m.now)
    b.step()
    assert b.ui.arr["pinned"] == []
    with closing(b.db()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] == 0


def test_an_apply_publishes_no_record_and_a_name_taken_skip_publishes_no_revert(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    a.project("X", uid(1))
    b.project("X", uid(1))
    b.project("Taken", uid(2))
    m.seed_all()
    a.sql("UPDATE projects SET display_name = 'Taken' WHERE uid = ?", uid(1))
    a.step()
    m.converge(("a", "b"))
    b.step(), b.step()
    assert b.project_name(uid(1)) == "X"
    assert b.own_rows() == []
    m.converge(("a", "b"))
    assert m.stores["a"].kind_rows(m.lst(), "panel")[f"p:{uid(1)}:name"][0] == "Taken"


def _ledger(path: Path, fields: Dict[str, list]) -> None:
    ledger = panel_merge.Ledger(path)
    ledger.fields, ledger.init = fields, True
    ledger.save()


def test_seeding_a_members_newer_legacy_edit_beats_the_alpha_a_shadow_is_not_seeded_and_a_member_seeds_only_its_own(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    a.project("Alpha", uid(1)), b.project("Newer", uid(1))
    a.project("Folder guess", uid(2), host_key="peer:x")
    b.project("Plain", uid(3))
    _ledger(b.legacy, {f"p:{uid(1)}:name": [NOW - 1000, b.iid, panel_merge._hash("Newer")], f"p:{uid(3)}:name": [0, "", panel_merge._hash("Plain")]})
    m.seed_all()
    m.converge(("a", "b"))
    for c in (a, b):
        assert c.rows()[f"p:{uid(1)}:name"][0] == "Newer"
    assert not any(k.startswith(f"p:{uid(2)}:") for k in a.rows())
    assert b.own_rows() == [f"p:{uid(1)}:name"]


def test_a_computer_without_the_yes_writes_no_panel_record(mesh):
    m = mesh("a", "b", "c", one_way={"b"}, no_yes={"c"})
    m["b"].project("P", uid(1))
    m["c"].project("Q", uid(2))
    m.seed_all()
    m["b"].sql("UPDATE projects SET display_name = 'Edited' WHERE uid = ?", uid(1))
    m["b"].step()
    assert m.stores["b"].kind_rows(m.lst(), "panel") == {}
    m["c"].sql("UPDATE projects SET display_name = 'EditedQ' WHERE uid = ?", uid(2))
    m["c"].step()
    assert m.stores["c"].kind_rows(m.lst(), "panel")[f"p:{uid(2)}:name"][0] == "EditedQ"


def _scaled(monkeypatch, **kw) -> None:
    monkeypatch.setitem(kinds.KINDS, "panel", kinds.KINDS["panel"]._replace(**kw))


def test_an_older_apps_member_origin_pin_is_not_signed_into_the_reserve_but_the_alphas_own_edit_is(mesh, monkeypatch):
    _scaled(monkeypatch, cap=40, origin_cap=40, reserve=8)
    m = mesh("a", "b", "c")
    a, b, c = m["a"], m["b"], m["c"]
    m.seed_all()
    room = 32 - len(a.rows())
    c_items = [(f"p:{uid(100 + i)}:name", "x", None) for i in range(room)]
    assert m.stores["c"].put_many("panel", c_items, m.signing["c"], m.lst()) == (room, 0)
    m.converge(("a", "c"))
    assert len(a.rows()) == 32
    doc = {"v": 1, "companies": [], "projects": [], "groups": [], "stamps": {"a:pinned": [NOW, b.iid]},
           "arrangement": {"pinned": [[b.iid, u36(1)]], "order": [], "bands": {}, "sections": None, "group_order": []}}
    with closing(a.db()) as conn, transaction(conn):
        _report, arrangement = panel_merge.receive(conn, doc, a.iid, a.ui.arr, a.legacy, from_main=False)
    a.ui.arr = arrangement
    a.session(2)
    a.arrangement(order=[u36(2)])
    a.step()
    keys = a.own_rows()
    assert f"l:ord:{a.iid}/{u36(2)}" in keys
    assert not any(k.startswith("l:pin:") for k in a.rows())


def test_a_key_missing_from_the_rows_is_no_opinion_never_a_delete_or_a_reset(mesh, monkeypatch):
    m = mesh("a", "b", "c")
    a, b, c = m["a"], m["b"], m["c"]
    for x in (a, b, c):
        x.project("Original", uid(1))
    m.seed_all()
    a.session(1)
    a.arrangement(pinned=[u36(1)])
    a.step()
    m.converge(("a", "b"), ("a", "c"))
    b.step(), c.step()
    assert c.ui.arr["pinned"] == [shadow_uuid(a.iid, u36(1))]
    m["b"].sql("UPDATE projects SET display_name = 'B rename' WHERE uid = ?", uid(1))
    b.arrangement(pinned=[])
    b.step()
    m.converge(("a", "b"), ("a", "c"))
    monkeypatch.setattr(direction, "contained", lambda iid: iid == b.iid)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [b.iid])
    c.step(), c.step()
    pin_key = f"l:pin:{a.iid}/{u36(1)}"
    assert f"p:{uid(1)}:name" not in c.rows() and pin_key not in c.rows()
    assert c.project_name(uid(1)) == "Original" and c.ui.arr["pinned"] == [shadow_uuid(a.iid, u36(1))]
    assert c.own_rows() == []


def test_an_edit_made_after_the_digest_read_is_published_and_survives_the_apply(mesh):
    m = mesh("a", "b")
    a = m["a"]
    a.project("Old", uid(1))
    m.seed_all()
    store, real, fired = m.stores["a"], m.stores["a"].kind_digest, []

    def digest_then_edit(lst: Any, kind: str) -> str:
        out = real(lst, kind)
        if not fired:
            fired.append(1)
            a.sql("UPDATE projects SET display_name = 'Mine' WHERE uid = ?", uid(1))
        return out

    store.kind_digest = digest_then_edit
    a.step()
    assert a.rows()[f"p:{uid(1)}:name"][0] == "Mine" and a.project_name(uid(1)) == "Mine"


def test_at_most_500_companies_reach_the_apply_and_every_held_company_is_kept(mesh, monkeypatch):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    held = [f"Held{i}" for i in range(3)]
    for i, name in enumerate(held):
        a.sql("INSERT INTO companies (name, uid, created_at, updated_at) VALUES (?, ?, 't', 't')", name, uid(500 + i))
    m.seed_all()
    assert m.stores["b"].put_many("panel", [(f"c:{uid(1000 + i)}:name", f"Junk{i}", None) for i in range(600)], m.signing["b"], m.lst()) == (600, 0)
    m.converge(("a", "b"))
    seen_sizes: List[int] = []
    real = panel.apply

    def spy(conn, doc, *args, **kw):
        seen_sizes.append(len(doc["companies"]))
        return real(conn, doc, *args, **kw)

    monkeypatch.setattr(panel, "apply", spy)
    a.step()
    assert seen_sizes and max(seen_sizes) <= panel.MAX_COMPANIES
    with closing(a.db()) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM companies")}
        assert set(held) <= names and conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == panel.MAX_COMPANIES


def test_the_sender_builds_nothing_for_a_mesh_peer_with_the_switch_on_and_behaves_as_before_with_it_off(tmp_path, monkeypatch):
    calls: List[str] = []

    class Wire:
        def for_peer(self, _iid, _timeout):
            async def request(method, path, json=None):
                calls.append(path)
                return 200, {"report": {}}
            return request

    built: List[int] = []

    def sender(peers, is_main):
        return GlobalSync(settings=lambda: {"enabled": False, "auto": False, "claude": True, "codex": True, "panel": True}, is_main=lambda: is_main,
                          peers=lambda: peers, approved=lambda _i: True, allows=lambda _i: True, contained=lambda _i: False, accounts=lambda: [],
                          request_for=Wire().for_peer, status=Status(tmp_path / "s.json"), outbox=tmp_path / "out", home=tmp_path, notify=lambda: None,
                          panel_doc=lambda: built.append(1) or {"v": 1}, panel_status=Status(tmp_path / "p.json"), main_id=lambda: "main",
                          one_way_toward=lambda _i: False, panel_pending=lambda: True, panel_sent=lambda: None)

    mesh_view = PeerView("m", "m", True, [PANEL_CAP, caps.CAP_MESH])
    member_view = PeerView("main", "main", True, [PANEL_CHANGE_CAP, caps.CAP_MESH])
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(panel_apply, "records_carry", lambda iid=None: True)
    assert asyncio.run(sender([mesh_view], True)._deliver_panel(mesh_view, False)) == "mesh" and built == [] and calls == []
    assert asyncio.run(sender([member_view], False).send_changes(force=True)) == "" and built == [] and calls == []
    monkeypatch.setattr(panel_apply, "records_carry", lambda iid=None: False)
    assert asyncio.run(sender([mesh_view], True)._deliver_panel(mesh_view, False)) == "synced" and built == [1]
    assert asyncio.run(sender([member_view], False).send_changes(force=True)) == "synced" and calls[-1].endswith("/panel-change")
    built.clear(), calls.clear()
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    assert asyncio.run(sender([mesh_view], True)._deliver_panel(mesh_view, True)) == "synced" and built == [1]
    assert asyncio.run(sender([member_view], False).send_changes(force=True)) == "synced" and calls[-1].endswith("/panel-change")


def _doc(stamps: Optional[dict] = None, **arr: Any) -> dict:
    return {"v": 1, "companies": [], "projects": [], "groups": [], "stamps": stamps or {},
            "arrangement": {"pinned": [], "order": [], "bands": {}, "sections": None, "group_order": [], **arr}}


def _req(c: Comp) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ui_preferences_store=c.ui)))


def _route(monkeypatch, c: Comp, doc: dict, from_main: bool, caller: Optional[str] = None) -> tuple:
    monkeypatch.setattr(routes, "state_dir", lambda: c.dir)
    monkeypatch.setattr(routes, "open_db", c.db)
    return routes._apply_panel(doc, _req(c), from_main, caller=caller)


def _receive(monkeypatch, c: Comp, doc: dict, from_main: bool, caller: Optional[str] = None) -> Any:
    monkeypatch.setattr(routes, "state_dir", lambda: c.dir)
    monkeypatch.setattr(routes, "open_db", c.db)
    monkeypatch.setattr(routes, "_panel_on", lambda: True)
    monkeypatch.setattr(routes, "_cap_body", lambda request, limit: None)
    return asyncio.run(routes._receive_panel(SimpleNamespace(doc=doc), _req(c), from_main=from_main, caller=caller))


def test_the_legacy_pin_route_runs_the_shared_apply_commits_rebases_and_announces(mesh, monkeypatch):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    m.seed_all()
    a.session(1)
    announced: List[Any] = []

    async def record(_state, report, result):
        announced.append((report, result))
        return True

    monkeypatch.setattr(panel_apply, "announce", record)
    now = int(time.time() * 1000)
    answer = _receive(monkeypatch, a, _doc({"a:pinned": [now, b.iid]}, pinned=[[a.iid, u36(1)]]), False, b.iid)
    assert "report" in answer and len(announced) == 1 and announced[0][1].status == "committed"
    assert a.ui.arr["pinned"] == [u36(1)]
    assert panel_merge.Ledger(a.legacy).init is True and panel_merge.pending(a.legacy) is False
    assert panel_apply.APPLY_LOCK is routes._APPLY_LOCK
    a.step()
    assert f"l:pin:{a.iid}/{u36(1)}" in a.own_rows()


def test_a_bad_panel_document_answers_422_and_announces_nothing(mesh, monkeypatch):
    m = mesh("a", "b")
    a = m["a"]
    m.seed_all()
    announced: List[Any] = []

    async def record(*args):
        announced.append(1)

    monkeypatch.setattr(panel_apply, "announce", record)
    answer = _receive(monkeypatch, a, {"v": 99}, True)
    assert answer.status_code == 422 and announced == []


def _legacy_doc(c: Comp, name: str) -> dict:
    c.sql("UPDATE projects SET display_name = ? WHERE uid = ?", name, uid(1))
    with closing(c.db()) as conn:
        return panel_merge.doc_for_send(conn, c.ui.arr, c.iid, c.legacy)


def test_an_older_apps_edit_and_a_mesh_edit_cross_the_alpha_both_ways_and_the_round_trip_settles(mesh, monkeypatch, tmp_path):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    o = Comp(m, "o", tmp_path)
    for c in (a, b, o):
        c.project("Orig", uid(1))
    m.seed_all()
    with closing(o.db()) as conn:
        panel_merge.doc_for_send(conn, o.ui.arr, o.iid, o.legacy)
    with closing(a.db()) as conn:
        panel_merge.doc_for_send(conn, a.ui.arr, a.iid, a.legacy)

    def a_doc() -> dict:
        with closing(a.db()) as conn:
            return panel_merge.doc_for_send(conn, a.ui.arr, a.iid, a.legacy)

    def to_alpha(doc: dict) -> None:
        _route(monkeypatch, a, doc, False, o.iid)
        panel_merge.clear_pending(o.legacy)

    def to_older(doc: dict) -> None:
        _route(monkeypatch, o, doc, True)

    def full_round() -> None:
        a.step()
        m.converge(("a", "b"))
        b.step()
        a.step()
        to_older(a_doc())
        if panel_merge.pending(o.legacy):
            to_alpha(_legacy_doc(o, o.project_name(uid(1))))

    to_alpha(_legacy_doc(o, "FromOlder"))
    a.step()
    m.converge(("a", "b"))
    b.step()
    assert b.project_name(uid(1)) == "FromOlder"
    m.now += 1000
    b.sql("UPDATE projects SET display_name = 'FromMesh' WHERE uid = ?", uid(1))
    b.step()
    m.converge(("a", "b"))
    a.step()
    time.sleep(0.01)
    to_older(a_doc())
    assert o.project_name(uid(1)) == "FromMesh" and a.project_name(uid(1)) == "FromMesh"
    full_round(), full_round()
    before = (m.stores["a"].kind_digest(m.lst(), "panel"), m.stores["b"].kind_digest(m.lst(), "panel"), a_doc(), panel_merge.pending(o.legacy))
    full_round()
    after = (m.stores["a"].kind_digest(m.lst(), "panel"), m.stores["b"].kind_digest(m.lst(), "panel"), a_doc(), panel_merge.pending(o.legacy))
    assert before[:2] == after[:2], (before, after)
    assert before[2] == after[2], (before[2], after[2])
    assert after[3] is False
    assert {c.project_name(uid(1)) for c in (a, b, o)} == {"FromMesh"}


def test_the_panel_change_route_is_star_only_and_refused_to_mesh_members_but_open_to_older_apps_and_with_the_switch_off(mesh, monkeypatch):
    mesh("a")
    path = "/api/v1/federation/pack/global/panel-change"
    assert mesh_powers.power_for("POST", path) is None and mesh_powers.REFUSED_WHY[("POST", path)] == "star_only"
    peer = "peer-x"
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id=peer))
    monkeypatch.setattr(routes, "content_alpha", lambda: "me")
    monkeypatch.setattr(routes, "read_install_id", lambda conn: "me")
    monkeypatch.setattr(routes, "open_db", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(panel_apply, "records_carry", lambda iid=None: True)
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda _iid: [caps.CAP_MESH]))
    with pytest.raises(routes.HTTPException) as refused:
        asyncio.run(routes._member(principal))
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "mesh_member"
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda _iid: []))
    assert asyncio.run(routes._member(principal)) == peer
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda _iid: [caps.CAP_MESH]))
    monkeypatch.setattr(caps, "MESH_BUILD_ON", False)
    assert asyncio.run(routes._member(principal)) == peer


def test_the_real_records_gate_refuses_a_mesh_member_the_panel_change_and_skips_the_sender_only_where_the_list_approves(mesh, monkeypatch):
    m = mesh("a", "b", "c", "d", one_way={"c"}, no_yes={"d"})
    a, b, c, d = m["a"], m["b"], m["c"], m["d"]
    monkeypatch.setattr(gossip, "ACTIVE", gossip.Gossip(m.stores["a"], links_getter=lambda: None, signing=m.signing["a"], held_list=m.lst,
                                                         label=lambda: "a", app_version="t", own_iid=a.iid))
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(capabilities=lambda _iid: [caps.CAP_MESH]))
    monkeypatch.setattr(routes, "content_alpha", lambda: a.iid)
    monkeypatch.setattr(routes, "read_install_id", lambda conn: a.iid)
    monkeypatch.setattr(routes, "open_db", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(direction, "contained", lambda iid: False)

    def member(comp: Any) -> Any:
        return asyncio.run(routes._member(SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id=comp.iid))))
    with pytest.raises(routes.HTTPException) as refused:
        member(b)
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "mesh_member"
    assert sender._records_carry(b.iid) is True
    assert sender._records_carry(d.iid) is True
    assert member(c) == c.iid and sender._records_carry(c.iid) is False
    monkeypatch.setattr(direction, "contained", lambda iid: iid == b.iid)
    assert sender._records_carry(b.iid) is False


def test_a_hostile_older_app_cannot_fill_the_reserve_through_the_bridge_by_forged_or_missing_stamp_origins(mesh, monkeypatch):
    _scaled(monkeypatch, cap=40, origin_cap=40, reserve=8)
    m = mesh("a", "b", "c")
    a, b, c = m["a"], m["b"], m["c"]
    m.seed_all()
    room = 32 - len(a.rows())
    assert m.stores["c"].put_many("panel", [(f"p:{uid(100 + i)}:name", "x", None) for i in range(room)], m.signing["c"], m.lst()) == (room, 0)
    m.converge(("a", "c"))
    assert len(a.rows()) == 32
    now = int(time.time() * 1000)
    hostile = _doc({"a:pinned": [now, a.iid], "a:band:kind1": [now, ""]}, pinned=[[b.iid, u36(1)]], bands={"kind1": [[b.iid, u36(3)]]})
    hostile["groups"] = [{"uid": u36(7), "name": "Junk", "members": [[b.iid, u36(4)]], "band": None, "gone": False}]
    _route(monkeypatch, a, hostile, False, b.iid)
    a.session(2)
    a.arrangement(order=[u36(2)])
    a.step()
    signed = a.own_rows()
    assert f"l:ord:{a.iid}/{u36(2)}" in signed
    assert not [k for k in signed if k.startswith(("l:pin:", "l:b.", "l:gm.", f"g:{u36(7)}:"))], signed


def test_a_rejected_ui_store_write_reverts_nothing_and_is_applied_again_when_the_digest_next_changes(mesh):
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    a.project("Orig", uid(1)), b.project("Orig", uid(1))
    m.seed_all()
    sections = list(SECTION_IDS)[::-1]
    b.arrangement(sections=sections)
    b.step()
    m.converge(("a", "b"))
    assert "a:sections" in b.own_rows()
    seen_path = a.dir / "pack" / mesh_panel.SEEN_FILE
    before = mesh_panel.Seen.load(seen_path).scalars.get("a:sections")
    base = a.ui.updates
    a.ui.reject = True
    a.step(), a.step(), a.step()
    assert a.ui.updates == base + 1
    assert "a:sections" not in a.own_rows()
    assert mesh_panel.Seen.load(seen_path).scalars.get("a:sections") == before
    a.ui.reject = False
    a.step()
    assert a.ui.updates == base + 1 and a.ui.arr is None
    b.sql("UPDATE projects SET display_name = 'Remote' WHERE uid = ?", uid(1))
    b.step()
    m.converge(("a", "b"))
    a.step()
    assert a.ui.updates == base + 2 and a.ui.arr["sections"] == sections


def test_a_pin_refused_for_room_is_retried_after_an_apply_rebased_and_room_freed(mesh, monkeypatch):
    _scaled(monkeypatch, cap=40, origin_cap=20, reserve=8)
    m = mesh("a", "b")
    a, b = m["a"], m["b"]
    a.project("Orig", uid(1)), b.project("Orig", uid(1))
    m.seed_all()
    room = 20 - len(b.own_rows())
    assert m.stores["b"].put_many("panel", [(f"p:{uid(100 + i)}:name", "x", None) for i in range(room)], m.signing["b"], m.lst()) == (room, 0)
    b.session(1)
    b.arrangement(pinned=[u36(1)])
    b.step()
    pin = f"l:pin:{b.iid}/{u36(1)}"
    assert pin not in b.rows()
    a.sql("UPDATE projects SET display_name = 'Remote' WHERE uid = ?", uid(1))
    a.step()
    m.converge(("a", "b"))
    b.step()
    assert pin not in b.rows()
    _scaled(monkeypatch, cap=40, origin_cap=40, reserve=8)
    b.step()
    assert pin in b.own_rows()


def test_announce_keeps_the_legacy_order(monkeypatch):
    order: List[str] = []
    from src.core import resource_push, session_change_notice
    from src.core.pack.globalsync import wiring
    from src.core.preferences_push import broadcast

    async def broadcast_changed(_state, _result, _x):
        order.append("broadcast")

    monkeypatch.setattr(session_change_notice, "publish", lambda _s, _n: order.append("notice"))
    monkeypatch.setattr(session_change_notice, "build_structural_notice", lambda kind: kind)
    monkeypatch.setattr(wiring, "groups_changed", lambda: order.append("groups_changed"))
    monkeypatch.setattr(broadcast, "broadcast_changed", broadcast_changed)
    monkeypatch.setattr(resource_push, "notify", lambda topic: order.append(f"notify:{topic}"))
    report = {"companies_created": 0, "companies_updated": 0, "projects_updated": 1, "groups_changed": 1}
    moved = asyncio.run(panel_apply.announce(None, report, SimpleNamespace(status="committed")))
    assert moved and order[:3] == ["notice", "groups_changed", "broadcast"] and len(order) == 5 and order[3].startswith("notify:")
    report = {"companies_created": 0, "companies_updated": 0, "projects_updated": 0, "groups_changed": 0}
    order.clear()
    assert not asyncio.run(panel_apply.announce(None, report, SimpleNamespace(status="conflict"))) and report["arrangement"] == "conflict" and order == []


def test_fractional_positions_stay_between_their_neighbours_and_inside_the_grammar():
    assert fracindex.key_between(None, None) < fracindex.key_between("V", None)
    key = None
    for _ in range(400):
        key = fracindex.key_between("V", key) if key else fracindex.key_between("V", "W")
    assert "V" < key < "W" and fracindex.needs_rebalance(key)
    assert all(panel_kind._POS.fullmatch(fracindex.seed(i, 500)) for i in range(500))
    assert [fracindex.seed(i, 7) for i in range(7)] == sorted({fracindex.seed(i, 7) for i in range(7)})
    for bad in (("b", "a"), ("a", "a"), ("A0", None), (None, "z0")):
        with pytest.raises(ValueError):
            fracindex.key_between(*bad)


def test_one_apply_step_and_one_no_op_step_at_2000_projects_500_companies_and_200_order_items(mesh, capsys):
    m = mesh("a", "b")
    a = m["a"]
    with closing(a.db()) as conn, transaction(conn):
        for i in range(2000):
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at, uid) "
                         "VALUES (?, ?, ?, 'user', 'present', 't', 't', 't', ?)", (f"/r/{i}", f"/r/{i}", f"Project {i}", uid(10 + i)))
        for i in range(500):
            conn.execute("INSERT INTO companies (name, uid, created_at, updated_at) VALUES (?, ?, 't', 't')", (f"Company {i}", uid(5000 + i)))
        for i in range(1, 201):
            add_row(conn, uuid=u36(i), name=f"s{i}", epoch=1)
    a.arrangement(order=[u36(i) for i in range(1, 201)])
    t0 = time.perf_counter()
    a.step()
    seed_s = time.perf_counter() - t0
    a.step()
    a.sql("UPDATE projects SET display_name = 'Changed' WHERE uid = ?", uid(10))
    t1 = time.perf_counter()
    a.step()
    apply_s = time.perf_counter() - t1
    t2 = time.perf_counter()
    a.step()
    noop_s = time.perf_counter() - t2
    with capsys.disabled():
        print(f"\nA10 timing: records {len(a.rows())}, seed {seed_s:.2f} s, apply step {apply_s:.2f} s, no-op step {noop_s:.2f} s")
    assert a.rows()[f"p:{uid(10)}:name"][0] == "Changed"
