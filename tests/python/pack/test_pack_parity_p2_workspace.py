
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from pydantic import ValidationError

from src.core import resource_push, row_looks, ui_preferences
from src.core.computers import direction
from src.core.db import connect, db_path_for, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.pack.globalsync import mesh_workspace
from src.core.pack.machines import capabilities as caps, config_state, restrictions
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import gossip, hlc, kinds, wire, workspace_kind
from src.core.pack.meshdata.store import RecordStore
from src.core.preferences_push import broadcast as prefs_broadcast
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.resource_push import topics
from src.core.row_looks.registry import Look
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000


def uid(n: int) -> str:
    return f"{n:032x}"


def rid(n: int) -> str:
    return f"{n:016x}"


class LocalRowLooks:

    def __init__(self) -> None:
        self._looks: Dict[str, Look] = {}

    def listing(self) -> Dict[str, Look]:
        return dict(self._looks)

    def set_look(self, row_id: str, fields: Dict[str, Optional[str]]) -> Look:
        old = self._looks.pop(row_id, Look())
        new = Look(fields["color"] if "color" in fields else old.color, fields["icon"] if "icon" in fields else old.icon)
        if new.color or new.icon:
            self._looks[row_id] = new
        else:
            new = Look()
        return new

    def forget(self, row_id: str) -> None:
        self._looks.pop(row_id, None)


class WorkspaceNode:

    def __init__(self, mesh: "WorkspaceMesh", name: str, tmp: Path) -> None:
        self.mesh = mesh
        self.name = name
        self.dir = tmp / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.iid = str(uuid.uuid4())
        ensure_db_migrated(self.dir)
        with closing(self.db()) as conn:
            set_meta(conn, META_INSTALL_ID, self.iid)
        self.config_path = self.dir / "config.json"
        self.config_path.write_text(json.dumps({}), encoding="utf-8")
        self.ui = UiPreferencesStore(lambda p=self.config_path: p)
        self.looks = LocalRowLooks()
        self.panel_enabled = True
        self.may_receive_pack_ui = True
        self.may_receive_global_setup = False
        self.broadcasts: List[Dict[str, Any]] = []
        self.app_state = SimpleNamespace(ui_preferences_store=self.ui, node_name=name)
        self.step_fn = mesh_workspace.attach(
            self.app_state,
            self.db,
            lambda: {"panel": self.panel_enabled},
            self.dir / "pack",
            row_looks_api=self.looks,
        )

    def db(self) -> Any:
        return connect(db_path_for(self.dir), create=False)

    def add_company(self, company_id: int, name: str, cuid: str) -> None:
        with closing(self.db()) as conn:
            conn.execute(
                "INSERT INTO companies (id, name, uid, created_at, updated_at) VALUES (?, ?, ?, 't', 't')",
                (company_id, name, cuid),
            )
            conn.commit()

    def add_project(self, project_id: int, name: str, puid: str) -> None:
        with closing(self.db()) as conn:
            conn.execute(
                "INSERT INTO projects (id, root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at, uid) "
                "VALUES (?, ?, ?, ?, 'user', 'present', 't', 't', 't', ?)",
                (project_id, f"/r/{puid}", f"/r/{puid}", name, puid),
            )
            conn.commit()

    def prefs(self) -> Dict[str, Any]:
        return dict(self.ui.read()["values"])

    def set_prefs(self, changes: Dict[str, Any]) -> Any:
        res = self.ui.update(changes)
        assert res.status in ("committed", "unchanged"), res.detail
        return res

    def step(self) -> None:
        self.mesh.active_node = self
        asyncio.run(self.step_fn(self.mesh.service(self.name), self.mesh.lst()))

    def rows(self) -> Dict[str, Any]:
        return self.mesh.stores[self.name].kind_rows(self.mesh.lst(), workspace_kind.KIND)

    def own_rows(self) -> List[str]:
        return sorted(k for k, (_v, stamp) in self.rows().items() if stamp.iid == self.iid)


class WorkspaceMesh:

    def __init__(self, tmp: Path, *names: str, no_yes: Optional[Set[str]] = None, one_way: Optional[Set[str]] = None) -> None:
        self.no_yes = no_yes or set()
        self.one_way = one_way or set()
        self.now = NOW
        self.keys = {n: DeviceKey.from_seed(bytes([i + 11]) * 32) for i, n in enumerate(names)}
        self.nodes = {n: WorkspaceNode(self, n, tmp) for n in names}
        self.signing = {
            n: Signing(install_id=self.nodes[n].iid, load_key=lambda n=n: self.keys[n], pinned_key=lambda _iid: None)
            for n in names
        }
        self.stores = {
            n: RecordStore(tmp / f"{n}-mesh.db", self.nodes[n].iid, wall=lambda: self.now, signing=self.signing[n])
            for n in names
        }
        self.alpha = names[0]
        self.active_node: WorkspaceNode = self.nodes[self.alpha]

    def __getitem__(self, name: str) -> WorkspaceNode:
        return self.nodes[name]

    def lst(self) -> RosterV2:
        rows = [
            RosterComputerV2(
                install_id=node.iid,
                label=n,
                fed_public_key=b64url(self.keys[n].raw_pub),
                cert=CERT,
                mesh=True,
                may_receive_logins=n not in self.no_yes,
                one_way=n in self.one_way,
            )
            for n, node in self.nodes.items()
        ]
        return RosterV2(generation=1, alpha=self.nodes[self.alpha].iid, home=self.nodes[self.alpha].iid, issued_at=1, computers=rows)

    def service(self, name: str) -> Any:
        return SimpleNamespace(store=self.stores[name], signing=self.signing[name], pass_gen=None)

    def sync(self, src: str, dst: str) -> None:
        lst = self.lst()

        async def call(body: dict) -> dict:
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), self.nodes[src].iid, lst, self.now)
            return json.loads(json.dumps(answer))

        asyncio.run(wire.run_sync(self.stores[src], call, lst, self.nodes[dst].iid, lambda: self.now))

    def converge(self, *edges: Tuple[str, str], rounds: int = 3) -> None:
        for _ in range(rounds):
            for x, y in edges:
                self.sync(x, y)
                self.sync(y, x)

    def seed_all(self) -> None:
        for node in self.nodes.values():
            node.step()


@pytest.fixture()
def ws_mesh(tmp_path: Path, monkeypatch: Any) -> Any:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda _iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])

    active_box: Dict[str, Optional[WorkspaceMesh]] = {"mesh": None}
    notified_topics: List[str] = []

    def _restrictions() -> restrictions.Restrictions:
        m = active_box["mesh"]
        if m is None:
            return restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=True)
        node = m.active_node
        return restrictions.Restrictions(
            may_receive_global_setup=node.may_receive_global_setup,
            may_receive_pack_ui=node.may_receive_pack_ui,
        )

    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=_restrictions))
    monkeypatch.setattr(resource_push, "notify", lambda topic: notified_topics.append(topic))

    async def fake_broadcast(app_state: Any, result: Any, client_id: Any) -> None:
        m = active_box["mesh"]
        if m is not None and hasattr(app_state, "node_name"):
            m.nodes[app_state.node_name].broadcasts.append({"changed": dict(result.changed), "client_id": client_id})

    monkeypatch.setattr(prefs_broadcast, "broadcast_changed", fake_broadcast)

    def factory(*names: str, **kw: Any) -> Tuple[WorkspaceMesh, List[str]]:
        m = WorkspaceMesh(tmp_path, *names, **kw)
        active_box["mesh"] = m
        return m, notified_topics

    return factory




def test_new_typed_ui_preferences_default_none_validate_and_roundtrip(tmp_path: Path) -> None:
    empty = ui_preferences.UiPreferenceValues()
    assert empty.layout_tabs is None
    assert empty.stats_bar_rate is None
    assert empty.stats_bar_window is None
    for field in ("layout_tabs", "stats_bar_rate", "stats_bar_window"):
        assert field in ui_preferences.known_fields()

    for rate in ui_preferences.STATS_BAR_RATES:
        assert ui_preferences.UiPreferenceValues(stats_bar_rate=rate).stats_bar_rate == rate
    for win in ui_preferences.STATS_BAR_WINDOWS:
        assert ui_preferences.UiPreferenceValues(stats_bar_window=win).stats_bar_window == win

    assert ui_preferences.STATS_BAR_RATES == ("sec", "min", "hour", "day")
    assert ui_preferences.STATS_BAR_WINDOWS == ("1h", "5h", "1d", "7d")
    assert ui_preferences.UiPreferenceValues(layout_tabs=["lay-1", "lay-2", "lay-1"]).layout_tabs == ["lay-1", "lay-2"]

    for bad_rate in ("tokens", "cost", "tpm", "", 1):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(stats_bar_rate=bad_rate)  # type: ignore[arg-type]
    for bad_win in ("24h", "30d", "all", "", 60):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(stats_bar_window=bad_win)  # type: ignore[arg-type]
    for bad_tabs in (["bad id"], [""], [f"id-{i}" for i in range(65)], ["../escape"]):
        with pytest.raises(ValidationError):
            ui_preferences.UiPreferenceValues(layout_tabs=bad_tabs)

    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    store = UiPreferencesStore(lambda: cfg)
    res = store.update({"layout_tabs": ["lay-a", "lay-b"], "stats_bar_rate": "hour", "stats_bar_window": "7d"})
    assert res.status == COMMITTED
    assert store.read()["values"] == {"layout_tabs": ["lay-a", "lay-b"], "stats_bar_rate": "hour", "stats_bar_window": "7d"}
    assert store.update({"stats_bar_rate": "bogus"}).status == REJECTED_INVALID
    unset = store.update({"layout_tabs": None, "stats_bar_rate": None, "stats_bar_window": None})
    assert unset.status == COMMITTED and store.read()["values"] == {}




def test_workspace_kind_registered_with_expected_caps_and_grammar() -> None:
    assert "workspace" in kinds.KINDS
    rule = kinds.KINDS["workspace"]
    assert (rule.cap, rule.origin_cap, rule.reserve, rule.tomb_ttl_ms, rule.tomb_value) == (
        16384, 8192, 2048, 30 * 24 * 3600 * 1000, None
    )

    valid_cases = [
        ("pref:sidebar_density", "compact"),
        ("pref:sidebar_layout", "rail"),
        ("pref:sidebar_show_leaders", True),
        ("pref:sidebar_show_archived", False),
        ("pref:sidebar_show_closed", True),
        ("pref:sidebar_list_open", True),
        ("pref:sidebar_list_sleeping", False),
        ("pref:sidebar_hide_empty_sections", True),
        ("pref:sidebar_show_stats", False),
        ("pref:drawer_row_icons", {"compact": {"agents": True}}),
        ("pref:drawer_zone", {"v": 1, "items": [{"widget": "core.ledger"}]}),
        ("pref:menu_order", ["agents", "settings"]),
        ("pref:rail_hidden_icons", ["automations"]),
        ("pref:theme", "matrix"),
        ("pref:projects_open", True),
        ("pref:layout_tabs", ["lay-1", "lay-2"]),
        ("pref:stats_bar_rate", "sec"),
        ("pref:stats_bar_window", "5h"),
        ("pref:desktop_collapsed", ["companies", f"cu:{uid(1)}", f"pu:{uid(2)}", f"pu:{uid(2)}:agents", "c:orphaned", "g:grp-1", "layout:lay-1", "host-off:iid-a"]),
        ("pref:analytics_filters", {"range": "7d", "projects": [uid(1)]}),
        ("pref:analytics_timezone", "America/New_York"),
        ("pref:timeline_filters", {"kinds": ["tool", "message"]}),
        ("pref:theme", None),
        (f"rl:{rid(1)}", {"color": "cyan", "icon": "docs"}),
        (f"rl:{rid(2)}", {"color": "coral", "icon": None}),
        (f"rl:{rid(3)}", {"gone": True}),
        ("db:meta", {"active": "home", "order": ["home", "ops"]}),
        ("db:home:head", {"name": "Home", "cols": 12}),
        ("db:home:rows", [{"id": "r1"}]),
        ("db:home:g.c1", {"widget": "core.ledger", "x": 0, "y": 0}),
        ("sc:chart-1", {"title": "Tokens", "window": "7d"}),
        ("st:tpl-1", {"name": "Daily"}),
        ("sa:alert-1", {"threshold": 80}),
        ("ss:settings", {"retention_days": 30}),
        ("ws:main", {"active_tab": "t1"}),
        ("wst:t1", {"kind": "dashboard", "target": "home"}),
        ("sc:chart-1", {"gone": True}),
    ]
    for key, val in valid_cases:
        assert workspace_kind.valid(key, val) is True, (key, val)

    assert workspace_kind.is_tomb({"gone": True}) is True
    assert workspace_kind.is_tomb(None) is False
    assert workspace_kind.is_tomb({"color": "cyan", "icon": None}) is False

    invalid_cases = [
        ("pref:sidebar_density_mobile", "compact"),
        ("pref:claude_tunnel_token", "secret"),
        ("pref:unknown_pref", "x"),
        ("pref:sidebar_density", "tiny"),
        ("pref:sidebar_show_leaders", 1),
        ("pref:layout_tabs", ["a", "a"]),
        ("pref:stats_bar_rate", "tokens"),
        ("pref:stats_bar_window", "99d"),
        ("pref:desktop_collapsed", ["c:42"]),
        ("pref:desktop_collapsed", ["p:7"]),
        ("pref:desktop_collapsed", ["p:7:agents"]),
        ("pref:analytics_timezone", "Mars/Olympus"),
        ("pref:analytics_filters", {"api_key": "leaked"}),
        ("rl:short", {"color": "cyan"}),
        (f"rl:{rid(1)}", {"color": "#ff0000"}),
        (f"rl:{rid(1)}", {"color": None, "icon": None}),
        (f"rl:{rid(1)}", {"gone": False}),
        ("db:../evil:head", {"name": "x"}),
        ("db:home:head", {"nested": {"access_token": "nope"}}),
        ("sc:chart-1", {"secret_fields": ["url"]}),
        ("ss:settings", {"gone": True}),
        ("sc:" + "a" * 130, {"x": 1}),
        ("sc:big", {"blob": "x" * 5000}),
        ("unknown:foo", {"x": 1}),
    ]
    for key, val in invalid_cases:
        assert workspace_kind.valid(key, val) is False, (key, val)


def test_workspace_kind_approval_one_way_and_containment(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    contained_ids: Set[str] = set()
    monkeypatch.setattr(direction, "contained", lambda iid: iid in contained_ids)
    monkeypatch.setattr(direction, "one_way_ids", lambda: sorted(contained_ids))

    keys = {n: DeviceKey.from_seed(bytes([i + 20]) * 32) for i, n in enumerate(("a", "b", "c", "d"))}
    rows = [
        RosterComputerV2(install_id="iid-a", label="a", fed_public_key=b64url(keys["a"].raw_pub), cert=CERT, mesh=True, may_receive_logins=True),
        RosterComputerV2(install_id="iid-b", label="b", fed_public_key=b64url(keys["b"].raw_pub), cert=CERT, mesh=True, may_receive_logins=False),
        RosterComputerV2(install_id="iid-c", label="c", fed_public_key=b64url(keys["c"].raw_pub), cert=CERT, mesh=True, one_way=True),
        RosterComputerV2(install_id="iid-d", label="d", fed_public_key=b64url(keys["d"].raw_pub), cert=CERT, mesh=True, may_receive_logins=False),
    ]
    lst = RosterV2(generation=1, alpha="iid-a", home="iid-a", issued_at=1, computers=rows)

    assert workspace_kind.approved_listed(lst, "iid-b") is True
    assert workspace_kind.approved(lst, "iid-b") is True
    assert workspace_kind.approved_listed(lst, "iid-c") is False
    assert workspace_kind.approved(lst, "iid-c") is False

    contained_ids.add("iid-d")
    assert workspace_kind.approved_listed(lst, "iid-d") is True
    assert workspace_kind.origin_ok(lst, "iid-d") is True
    assert workspace_kind.approved(lst, "iid-d") is False
    assert workspace_kind.serve_ok(lst, "iid-d") is False

    sig_a = Signing(install_id="iid-a", load_key=lambda: keys["a"], pinned_key=lambda _i: None)
    store_a = RecordStore(tmp_path / "a.db", "iid-a", wall=lambda: NOW, signing=sig_a)
    assert store_a.put_own("workspace", "pref:theme", "matrix", sig_a, lst=lst) is True
    assert "workspace:pref:theme" in store_a.servable(lst, "iid-b")
    assert "workspace:pref:theme" not in store_a.servable(lst, "iid-c")
    assert "workspace:pref:theme" not in store_a.servable(lst, "iid-d")




def test_two_node_sidebar_preferences_sync_preserves_mobile_and_broadcasts(ws_mesh: Any) -> None:
    m, _topics = ws_mesh("a", "b", no_yes={"b"})
    a, b = m["a"], m["b"]

    a.set_prefs({
        "theme": "matrix",
        "sidebar_density": "compact",
        "sidebar_layout": "rail",
        "sidebar_show_leaders": False,
        "sidebar_show_archived": True,
        "sidebar_show_closed": True,
        "sidebar_list_open": True,
        "sidebar_list_sleeping": False,
        "sidebar_hide_empty_sections": True,
        "sidebar_show_stats": False,
        "menu_order": ["agents", "tasks", "settings"],
        "rail_hidden_icons": ["automations"],
        "layout_tabs": ["lay-1", "lay-2"],
        "stats_bar_rate": "sec",
        "stats_bar_window": "5h",
        "drawer_row_icons": {"compact": {"agents": True, "shells": False}},
        "drawer_zone": {"v": 1, "items": [{"widget": "core.ledger", "look": "compact"}]},
    })
    b.set_prefs({
        "sidebar_density_mobile": "detailed",
        "sidebar_show_stats_mobile": True,
        "sidebar_show_closed_mobile": False,
    })

    m.seed_all()
    m.converge(("a", "b"))
    b.step()

    bp = b.prefs()
    assert bp["theme"] == "matrix"
    assert bp["sidebar_density"] == "compact"
    assert bp["sidebar_layout"] == "rail"
    assert bp["sidebar_show_leaders"] is False
    assert bp["sidebar_show_archived"] is True
    assert bp["sidebar_show_closed"] is True
    assert bp["sidebar_list_open"] is True
    assert bp["sidebar_list_sleeping"] is False
    assert bp["sidebar_hide_empty_sections"] is True
    assert bp["sidebar_show_stats"] is False
    assert bp["menu_order"] == ["agents", "tasks", "settings"]
    assert bp["rail_hidden_icons"] == ["automations"]
    assert bp["layout_tabs"] == ["lay-1", "lay-2"]
    assert bp["stats_bar_rate"] == "sec"
    assert bp["stats_bar_window"] == "5h"
    assert bp["drawer_row_icons"]["compact"]["agents"] is True
    assert bp["drawer_zone"]["items"][0]["widget"] == "core.ledger"
    assert bp["sidebar_density_mobile"] == "detailed"
    assert bp["sidebar_show_stats_mobile"] is True
    assert bp["sidebar_show_closed_mobile"] is False
    assert len(b.broadcasts) == 1 and "theme" in b.broadcasts[0]["changed"]

    b.step()
    assert b.own_rows() == []
    assert len(b.broadcasts) == 1

    m.now += 1000
    b.set_prefs({"stats_bar_window": "7d", "theme": None})
    b.step()
    m.converge(("a", "b"))
    a.step()
    ap = a.prefs()
    assert ap["stats_bar_window"] == "7d"
    assert "theme" not in ap
    assert len(a.broadcasts) == 1 and a.broadcasts[0]["changed"]["theme"] is None




def test_desktop_collapsed_translates_company_and_project_ids_without_clobbering_panel_or_mobile(ws_mesh: Any) -> None:
    m, _topics = ws_mesh("a", "b")
    a, b = m["a"], m["b"]
    co_uid, proj_uid, late_uid = uid(101), uid(102), uid(103)

    a.add_company(1, "Nyedis", co_uid)
    a.add_project(2, "Carnivore", proj_uid)
    a.add_company(3, "LateCo", late_uid)
    b.add_company(42, "Nyedis", co_uid)
    b.add_project(99, "Carnivore", proj_uid)

    b.set_prefs({
        "drawer_arrangement": {
            "v": 1,
            "pinned": ["sess-pin-1"],
            "order": ["sess-ord-1"],
            "bands": {"rogue": ["sess-rogue-1"]},
            "collapsed": ["other"],
            "sections": ["pinned", "companies", "rogue"],
            "mobile": {"collapsed": ["terminals", "browsers"]},
            "projects_open": True,
        }
    })

    m.seed_all()
    m.now += 1000
    a.set_prefs({
        "drawer_arrangement": {
            "v": 1,
            "pinned": [],
            "order": [],
            "bands": {},
            "collapsed": [
                "companies",
                "c:1",
                "p:2",
                "p:2:agents",
                "c:3",
                "c:orphaned",
                "g:grp-1",
                "layout:lay-1",
                "host-off:iid-peer",
            ],
            "projects_open": False,
        }
    })
    a.step()

    wire_folds = a.rows()["pref:desktop_collapsed"][0]
    assert wire_folds == [
        "companies",
        f"cu:{co_uid}",
        f"pu:{proj_uid}",
        f"pu:{proj_uid}:agents",
        f"cu:{late_uid}",
        "c:orphaned",
        "g:grp-1",
        "layout:lay-1",
        "host-off:iid-peer",
    ]
    assert a.rows()["pref:projects_open"][0] is False

    m.converge(("a", "b"))
    b.step()
    b_arr = b.prefs()["drawer_arrangement"]
    assert b_arr["collapsed"] == [
        "companies",
        "c:42",
        "p:99",
        "p:99:agents",
        "c:orphaned",
        "g:grp-1",
        "layout:lay-1",
        "host-off:iid-peer",
    ]
    assert b_arr["projects_open"] is False
    assert b_arr["pinned"] == ["sess-pin-1"]
    assert b_arr["order"] == ["sess-ord-1"]
    assert b_arr["bands"] == {"rogue": ["sess-rogue-1"]}
    assert b_arr["sections"] == ["pinned", "companies", "rogue"]
    assert b_arr["mobile"] == {"collapsed": ["terminals", "browsers"]}

    b.step()
    assert b.own_rows() == []

    m.now += 1000
    b_arr_edit = dict(b.prefs()["drawer_arrangement"])
    b_arr_edit["collapsed"] = [*b_arr_edit["collapsed"], "files"]
    b.set_prefs({"drawer_arrangement": b_arr_edit})
    b.step()
    assert f"cu:{late_uid}" in b.rows()["pref:desktop_collapsed"][0]
    assert "files" in b.rows()["pref:desktop_collapsed"][0]

    b.add_company(77, "LateCo", late_uid)
    b.step()
    assert "c:77" in b.prefs()["drawer_arrangement"]["collapsed"]




def test_row_looks_sync_upsert_update_tombstone_and_real_registry_notify(ws_mesh: Any, tmp_path: Path) -> None:
    m, notified = ws_mesh("a", "b")
    a, b = m["a"], m["b"]
    row_id = rid(7)

    a.looks.set_look(row_id, {"color": "cyan", "icon": "docs"})
    m.seed_all()
    m.converge(("a", "b"))
    notified.clear()
    b.step()

    assert b.looks.listing() == {row_id: Look("cyan", "docs")}
    assert topics.ROW_LOOKS in notified

    m.now += 1000
    b.looks.set_look(row_id, {"color": "violet", "icon": "star"})
    b.step()
    m.converge(("a", "b"))
    notified.clear()
    a.step()
    assert a.looks.listing() == {row_id: Look("violet", "star")}
    assert topics.ROW_LOOKS in notified

    m.now += 1000
    a.looks.forget(row_id)
    a.step()
    assert a.rows()[f"rl:{row_id}"][0] == {"gone": True}
    m.converge(("a", "b"))
    notified.clear()
    b.step()
    assert b.looks.listing() == {}
    assert topics.ROW_LOOKS in notified

    notified.clear()
    b.step()
    assert notified == []

    row_looks.reset_for_test()
    row_looks.configure(tmp_path / "real_rl")
    try:
        real_row = rid(9)
        rows = {f"rl:{real_row}": ({"color": "green", "icon": "code"}, hlc.Stamp(NOW, 0, a.iid))}
        seen = mesh_workspace.Seen(tmp_path / "seen.json")
        assert mesh_workspace._apply_row_looks(row_looks.registry, rows, set(), seen) is True
        assert row_looks.listing() == {real_row: Look("green", "code")}
        assert mesh_workspace._apply_row_looks(row_looks.registry, {f"rl:{real_row}": ({"gone": True}, hlc.Stamp(NOW + 1, 0, a.iid))}, set(), seen) is True
        assert row_looks.listing() == {}
    finally:
        row_looks.reset_for_test()




def test_may_receive_pack_ui_gates_apply_independently_of_may_receive_global_setup(ws_mesh: Any) -> None:
    m, _topics = ws_mesh("a", "b", no_yes={"b"})
    a, b = m["a"], m["b"]
    b.may_receive_global_setup = False
    b.may_receive_pack_ui = False

    a.set_prefs({"theme": "cyberpunk", "sidebar_density": "compact"})
    a.looks.set_look(rid(1), {"color": "coral", "icon": "bolt"})
    m.seed_all()
    m.converge(("a", "b"))

    b.step()
    assert "theme" not in b.prefs()
    assert b.looks.listing() == {}

    b.may_receive_pack_ui = True
    b.step()
    assert b.prefs()["theme"] == "cyberpunk"
    assert b.prefs()["sidebar_density"] == "compact"
    assert b.looks.listing() == {rid(1): Look("coral", "bolt")}

    m.now += 1000
    b.panel_enabled = False
    a.set_prefs({"theme": "matrix"})
    a.step()
    m.converge(("a", "b"))
    b.step()
    assert b.prefs()["theme"] == "cyberpunk"
