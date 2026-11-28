
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from src.core import item_settings_store, resource_push, session_change_notice, ui_preferences
from src.core.computers import direction
from src.core.db import connect, db_path_for, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.item_settings_ddl import ITEM_SETTINGS_TABLE
from src.core.pack.globalsync import mesh_workspace, mesh_workspace_dash
from src.core.pack.machines import capabilities as caps, config_state, restrictions
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import gossip, wire, workspace_kind
from src.core.pack.meshdata.store import RecordStore
from src.core.preferences_push import broadcast as prefs_broadcast
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.resource_push import topics
from src.core.stats import config as stats_config, tripwires as stats_tripwires
from src.core.stats.store import StatsStore
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, UiPreferencesStore
from src.models.stats import AnnotationWrite, ChartWrite, TripwireWrite

CERT = base64.b64encode(b"x" * 40).decode()
NOW = 1_800_000_000_000


class EmptyRowLooks:

    def listing(self) -> Dict[str, Any]:
        return {}

    def set_look(self, _row_id: str, _fields: Dict[str, Optional[str]]) -> None:
        pass

    def forget(self, _row_id: str) -> None:
        pass


class DashNode:

    def __init__(self, mesh: "DashMesh", name: str, tmp: Path, *, with_stats: bool = True) -> None:
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
        self.stats: Optional[StatsStore] = None
        if with_stats:
            st = StatsStore(self.dir)
            st.initialize()
            stats_config.ensure_schema(st)
            self.stats = st
        self.panel_enabled = True
        self.may_receive_pack_ui = True
        self.broadcasts: List[Dict[str, Any]] = []
        self.notices: List[Dict[str, Any]] = []
        self.scheduler_events: List[Dict[str, Any]] = []
        self.app_state = SimpleNamespace(
            ui_preferences_store=self.ui,
            stats_store=self.stats,
            stats_scheduler=SimpleNamespace(settings_changed=lambda s: self.scheduler_events.append(dict(s))),
            node_name=name,
        )
        self.step_fn = mesh_workspace.attach(
            self.app_state,
            self.db,
            lambda: {"panel": self.panel_enabled},
            self.dir / "pack",
            row_looks_api=EmptyRowLooks(),
            stats_store=self.stats,
        )

    def db(self) -> Any:
        return connect(db_path_for(self.dir), create=False)

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


class DashMesh:

    def __init__(self, tmp: Path, *names: str, without_stats: Optional[Set[str]] = None) -> None:
        no_stats = without_stats or set()
        self.now = NOW
        self.keys = {n: DeviceKey.from_seed(bytes([i + 31]) * 32) for i, n in enumerate(names)}
        self.nodes = {n: DashNode(self, n, tmp, with_stats=n not in no_stats) for n in names}
        self.signing = {
            n: Signing(install_id=self.nodes[n].iid, load_key=lambda n=n: self.keys[n], pinned_key=lambda _i: None)
            for n in names
        }
        self.stores = {
            n: RecordStore(tmp / f"{n}-mesh.db", self.nodes[n].iid, wall=lambda: self.now, signing=self.signing[n])
            for n in names
        }
        self.alpha = names[0]
        self.active_node: DashNode = self.nodes[self.alpha]

    def __getitem__(self, name: str) -> DashNode:
        return self.nodes[name]

    def lst(self) -> RosterV2:
        rows = [
            RosterComputerV2(
                install_id=node.iid,
                label=n,
                fed_public_key=b64url(self.keys[n].raw_pub),
                cert=CERT,
                mesh=True,
                may_receive_logins=True,
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
def dash_mesh(tmp_path: Path, monkeypatch: Any) -> Any:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(direction, "contained", lambda _iid: False)
    monkeypatch.setattr(direction, "one_way_ids", lambda: [])
    monkeypatch.setattr(gossip, "STEPS", [])

    active_box: Dict[str, Optional[DashMesh]] = {"mesh": None}
    notified_topics: List[str] = []

    def _restrictions() -> restrictions.Restrictions:
        m = active_box["mesh"]
        if m is None:
            return restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=True)
        return restrictions.Restrictions(may_receive_global_setup=False, may_receive_pack_ui=m.active_node.may_receive_pack_ui)

    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=_restrictions))
    monkeypatch.setattr(resource_push, "notify", lambda topic: notified_topics.append(topic))

    def fake_publish(app_state: Any, frame: Dict[str, Any]) -> None:
        m = active_box["mesh"]
        if m is not None and hasattr(app_state, "node_name"):
            m.nodes[app_state.node_name].notices.append(dict(frame))

    monkeypatch.setattr(session_change_notice, "publish", fake_publish)

    async def fake_broadcast(app_state: Any, result: Any, client_id: Any) -> None:
        m = active_box["mesh"]
        if m is not None and hasattr(app_state, "node_name"):
            m.nodes[app_state.node_name].broadcasts.append({"changed": dict(result.changed), "client_id": client_id})

    monkeypatch.setattr(prefs_broadcast, "broadcast_changed", fake_broadcast)

    def factory(*names: str, **kw: Any) -> Tuple[DashMesh, List[str]]:
        m = DashMesh(tmp_path, *names, **kw)
        active_box["mesh"] = m
        return m, notified_topics

    return factory




def test_layout_ceiling_and_new_typed_p3_preferences(tmp_path: Path) -> None:
    assert ui_preferences.MAX_LAYOUT_BYTES == 131072
    assert ui_preferences.MAX_HOME_LAYOUT_BYTES >= 12 * ui_preferences.MAX_LAYOUT_BYTES

    empty = ui_preferences.UiPreferenceValues()
    assert empty.analytics_filters is None
    assert empty.analytics_timezone is None
    assert empty.timeline_filters is None
    assert empty.widget_state is None
    for field in ("analytics_filters", "analytics_timezone", "timeline_filters", "widget_state"):
        assert field in ui_preferences.known_fields()

    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    store = UiPreferencesStore(lambda: cfg)
    big_layout = {"v": 6, "rows": [{"id": "r1", "pad": "x" * 25000}], "hidden": [], "heroCollapsed": False, "collapsed": []}
    res_big = store.update({"home_layout": {"v": 2, "boards": [{"id": "home", "name": "Home", "layout": big_layout}], "analytics_seed": 2}})
    assert res_big.status == COMMITTED, res_big.detail

    res = store.update({
        "analytics_filters": {"range": "7d", "provider": "claude", "host": "local", "hosts": ["local"], "project": "p1", "model": "claude-opus-4-6", "agent_kind": "claude", "account_id": "acct-1"},
        "analytics_timezone": "America/New_York",
        "timeline_filters": {"bookmarks": True, "compacts": False, "restarts": True, "sleeps": False, "restores": True},
        "widget_state": {"core.activity-log": {"level": "warn", "author": "ops"}, "analytics:abc-123": {"collapsed": True}},
    })
    assert res.status == COMMITTED, res.detail
    vals = store.read()["values"]
    assert vals["analytics_timezone"] == "America/New_York"
    assert vals["analytics_filters"]["range"] == "7d"
    assert vals["timeline_filters"]["sleeps"] is False
    assert vals["widget_state"]["core.activity-log"]["level"] == "warn"

    assert store.update({"analytics_timezone": "Mars/Phobos"}).status == REJECTED_INVALID
    assert store.update({"analytics_timezone": "A" * 65}).status == REJECTED_INVALID
    assert store.update({"analytics_filters": {"api_key": "leaked"}}).status == REJECTED_INVALID
    assert store.update({"timeline_filters": {"auth": "bad"}}).status == REJECTED_INVALID
    assert store.update({"widget_state": {"core.notes": {"cookie": "yum"}}}).status == REJECTED_INVALID
    assert store.update({"widget_state": {"core.notes": {"password": "pw"}}}).status == REJECTED_INVALID
    assert store.update({"widget_state": {"core.notes": {"blob": "x" * 4100}}}).status == REJECTED_INVALID
    assert store.update({"widget_state": {f"w{i}": {"k": i} for i in range(129)}}).status == REJECTED_INVALID
    assert store.update({"widget_state": {"w" * 65: {"ok": 1}}}).status == REJECTED_INVALID

    chart_uuid = str(uuid.uuid4())
    assert workspace_kind.valid(f"db:home:g.analytics:{chart_uuid}", {"id": f"analytics:{chart_uuid}", "ord": 0}) is True
    assert workspace_kind.valid("db:home:r.0", {"i": 0, "n": 2, "data": "[]"}) is True
    assert workspace_kind.valid(f"sc:analytics:{chart_uuid}", {"title": "Tokens"}) is True
    assert workspace_kind.valid("ws:core.activity-log", {"enabled": True, "settings": {"author": "ok"}}) is True
    for secret_key in ("token", "secret", "password", "api_key", "cookie", "auth", "auth_header", "session_token"):
        assert workspace_kind.valid("ws:core.notes", {"enabled": True, "settings": {secret_key: "nope"}}) is False, secret_key
        assert workspace_kind.valid("wst:core.notes", {secret_key: "nope"}) is False, secret_key




def test_multi_dashboard_large_free_grid_and_tombstones_sync(dash_mesh: Any) -> None:
    m, _topics = dash_mesh("a", "b")
    a, b = m["a"], m["b"]

    cells_24: List[Dict[str, Any]] = []
    cells_12: List[Dict[str, Any]] = []
    big_rows: List[Dict[str, Any]] = []
    for i in range(45):
        cid = f"analytics:{uuid.UUID(int=i + 1)}"
        cells_24.append({"id": cid, "x": (i % 3) * 8, "y": (i // 3) * 6, "w": 8, "h": 6, "meta": "m" * 180})
        cells_12.append({"id": cid, "x": (i % 2) * 6, "y": (i // 2) * 6, "w": 6, "h": 6})
        big_rows.append({"id": f"r{i + 1}", "kind": "px", "size": 240, "slots": [{"id": cid, "fr": 1.0, "note": "r" * 40}]})

    home_layout_dict = {
        "v": 2,
        "active": "ops",
        "analytics_seed": 2,
        "boards": [
            {
                "id": "home",
                "name": "Home",
                "layout": {
                    "v": 6,
                    "rows": big_rows,
                    "hidden": ["skills"],
                    "heroCollapsed": False,
                    "collapsed": [],
                    "headerOff": ["stat-running"],
                    "grid": {
                        "v": 1,
                        "cols": 24,
                        "pitch": 40,
                        "rowsSig": "0123456789abcdef",
                        "order": [c["id"] for c in cells_24],
                        "layouts": {"24": cells_24, "12": cells_12},
                    },
                },
            },
            {
                "id": "ops",
                "name": "Ops Room",
                "layout": {
                    "v": 6,
                    "rows": [{"id": "r1", "kind": "px", "size": 220, "slots": [{"id": "running-sessions", "fr": 1.0}]}],
                    "hidden": [],
                    "heroCollapsed": True,
                    "collapsed": ["ledger"],
                },
            },
        ],
    }
    raw_bytes = len(json.dumps(home_layout_dict).encode("utf-8"))
    assert raw_bytes > 16384, f"fixture must exceed old 16 KiB cap (got {raw_bytes})"

    a.set_prefs({"home_layout": home_layout_dict})
    m.seed_all()

    a_rows = a.rows()
    assert a_rows["db:meta"][0] == {"active": "ops", "order": ["home", "ops"], "analytics_seed": 2}
    assert a_rows["db:home:rows"][0]["chunked"] is True
    assert "db:home:r.0" in a_rows and "db:home:r.1" in a_rows
    cell_keys = [k for k in a_rows if k.startswith("db:home:g.")]
    assert len(cell_keys) == 45
    for k, (val, _stamp) in a_rows.items():
        assert len(json.dumps(val, sort_keys=True, separators=(",", ":"))) <= 4096, k

    m.converge(("a", "b"))
    b.step()

    b_hl = b.prefs()["home_layout"]
    assert b_hl["active"] == "ops"
    assert b_hl["analytics_seed"] == 2
    assert [bd["id"] for bd in b_hl["boards"]] == ["home", "ops"]
    assert b_hl["boards"][0]["layout"]["rows"] == big_rows
    assert b_hl["boards"][0]["layout"]["grid"]["layouts"]["24"] == cells_24
    assert b_hl["boards"][0]["layout"]["grid"]["layouts"]["12"] == cells_12
    assert b_hl["boards"][0]["layout"]["headerOff"] == ["stat-running"]
    assert b_hl["boards"][1]["layout"]["heroCollapsed"] is True
    assert len(b.broadcasts) == 1 and "home_layout" in b.broadcasts[0]["changed"]

    b.step()
    assert b.own_rows() == []
    assert len(b.broadcasts) == 1

    m.now += 1000
    edited = json.loads(json.dumps(b_hl))
    edited["boards"] = [edited["boards"][0]]
    edited["active"] = "home"
    removed_cell = edited["boards"][0]["layout"]["grid"]["layouts"]["24"].pop()
    edited["boards"][0]["layout"]["grid"]["layouts"]["12"] = [
        c for c in edited["boards"][0]["layout"]["grid"]["layouts"]["12"] if c["id"] != removed_cell["id"]
    ]
    b.set_prefs({"home_layout": edited})
    b.step()

    assert b.rows()["db:ops:head"][0] == {"gone": True}
    assert b.rows()[f"db:home:g.{removed_cell['id']}"][0] == {"gone": True}

    m.converge(("a", "b"))
    a.step()

    a_hl = a.prefs()["home_layout"]
    assert a_hl["active"] == "home"
    assert [bd["id"] for bd in a_hl["boards"]] == ["home"]
    assert len(a_hl["boards"][0]["layout"]["grid"]["layouts"]["24"]) == 44
    assert all(c["id"] != removed_cell["id"] for c in a_hl["boards"][0]["layout"]["grid"]["layouts"]["24"])




def test_stats_charts_sync_host_normalization_and_tombstone(dash_mesh: Any) -> None:
    m, _topics = dash_mesh("a", "b", "c", without_stats={"c"})
    a, b, c = m["a"], m["b"], m["c"]
    assert a.stats is not None and b.stats is not None and c.stats is None

    chart_id = uuid.uuid4()
    stats_config.create_chart(
        a.stats,
        ChartWrite(
            id=chart_id,
            title="Alpha Local Tokens",
            series=[{"metric": "total_tokens", "operation": "timeline", "filters": {"host": "local"}}],
            filters={"host": "local", "hosts": ["local", b.iid]},
        ),
    )

    m.seed_all()
    wire_chart = a.rows()[f"sc:{chart_id}"][0]
    assert wire_chart["filters"]["host"] == a.iid
    assert wire_chart["filters"]["hosts"] == [a.iid, b.iid]
    assert wire_chart["series"][0]["filters"]["host"] == a.iid

    m.converge(("a", "b"), ("a", "c"))
    b.step()
    c.step()

    b_chart = stats_config.get_chart(b.stats, str(chart_id))
    assert b_chart["title"] == "Alpha Local Tokens"
    assert b_chart["filters"]["host"] == a.iid
    assert b_chart["filters"]["hosts"] == [a.iid, "local"]
    assert b_chart["series"][0]["filters"]["host"] == a.iid
    assert any(n.get("type") == "stats.changed" for n in b.notices)

    m.now += 1000
    stats_config.update_chart(
        b.stats,
        str(chart_id),
        ChartWrite(
            id=chart_id,
            title="Renamed On B",
            series=[{"metric": "total_tokens", "operation": "timeline", "filters": {"host": a.iid}}],
            filters={"host": a.iid, "hosts": [a.iid, "local"]},
        ),
        b_chart["revision"],
    )
    b.step()
    m.converge(("a", "b"))
    a.step()

    a_chart = stats_config.get_chart(a.stats, str(chart_id))
    assert a_chart["title"] == "Renamed On B"
    assert a_chart["filters"]["host"] == "local"
    assert a_chart["filters"]["hosts"] == ["local", b.iid]
    assert a_chart["series"][0]["filters"]["host"] == "local"

    prior_notices = len(a.notices)
    a.step()
    assert f"sc:{chart_id}" not in a.own_rows()
    assert a.rows()[f"sc:{chart_id}"][1].iid == b.iid
    assert len(a.notices) == prior_notices

    m.now += 1000
    stats_config.delete_chart(a.stats, str(chart_id), a_chart["revision"])
    a.step()
    assert a.rows()[f"sc:{chart_id}"][0] == {"gone": True}
    m.converge(("a", "b"))
    b.step()
    with pytest.raises(stats_config.NotFound):
        stats_config.get_chart(b.stats, str(chart_id))




def test_stats_tripwires_annotations_and_settings_sync_and_tombstones(dash_mesh: Any) -> None:
    m, _topics = dash_mesh("a", "b")
    a, b = m["a"], m["b"]
    assert a.stats is not None and b.stats is not None

    tw = stats_tripwires.create_tripwire(
        a.stats,
        TripwireWrite(
            name="Token Spike",
            query={"metric": "total_tokens", "operation": "summary", "filters": {"host": "local"}},
            window_minutes=15,
            comparator=">",
            threshold=50000.0,
            for_minutes=5,
            cooldown_minutes=30,
            enabled=True,
        ),
    )
    ann = stats_config.create_annotation(
        a.stats,
        AnnotationWrite(
            occurred_at=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
            kind="manual",
            label="Shipped P3",
            scope={"host": "local", "provider": "claude"},
            basis="manual",
        ),
    )
    a_settings = stats_config.get_settings(a.stats)
    stats_config.update_settings(a.stats, enabled=not a_settings["enabled"], revision=a_settings["revision"])
    expected_enabled = not a_settings["enabled"]

    m.seed_all()
    m.converge(("a", "b"))
    b.step()

    b_tw = stats_tripwires.get_tripwire(b.stats, tw["id"])
    assert b_tw["name"] == "Token Spike"
    assert b_tw["threshold"] == 50000.0
    assert b_tw["query"]["filters"]["host"] == a.iid

    b_ann = stats_config.get_annotation(b.stats, ann["id"])
    assert b_ann["label"] == "Shipped P3"
    assert b_ann["scope"]["host"] == a.iid

    assert stats_config.get_settings(b.stats)["enabled"] is expected_enabled
    assert any(ev["enabled"] is expected_enabled for ev in b.scheduler_events)

    m.now += 1000
    stats_tripwires.delete_tripwire(a.stats, tw["id"])
    stats_config.delete_annotation(a.stats, ann["id"], ann["revision"])
    a.step()
    assert a.rows()[f"st:{tw['id']}"][0] == {"gone": True}
    assert a.rows()[f"sa:{ann['id']}"][0] == {"gone": True}

    m.converge(("a", "b"))
    b.step()
    with pytest.raises(stats_config.NotFound):
        stats_tripwires.get_tripwire(b.stats, tw["id"])
    with pytest.raises(stats_config.NotFound):
        stats_config.get_annotation(b.stats, ann["id"])




def test_item_settings_sync_strips_secrets_and_notifies_resource_push(dash_mesh: Any) -> None:
    m, notified = dash_mesh("a", "b")
    a, b = m["a"], m["b"]

    with closing(a.db()) as conn:
        item_settings_store.write_item(conn, "widget", "core.stat-running", enabled=False)
        conn.execute(
            f"INSERT INTO {ITEM_SETTINGS_TABLE} (kind, item_id, enabled, schema_version, values_json, revision, updated_at) "
            "VALUES ('widget', 'custom.widget', 1, 1, ?, 2, '2026-11-26T00:00:00Z')",
            (json.dumps({"limit": 25, "api_key": "sk-secret", "password": "pw", "auth_token": "tok", "cookie": "c=1", "nested": {"secret": "s", "ok": True}}),),
        )
        conn.commit()

    m.seed_all()
    wire_custom = a.rows()["ws:custom.widget"][0]
    assert wire_custom == {"enabled": True, "settings": {"limit": 25, "nested": {"ok": True}}}
    assert a.rows()["ws:core.stat-running"][0] == {"enabled": False, "settings": {}}

    m.converge(("a", "b"))
    notified.clear()
    b.step()

    with closing(b.db()) as conn:
        assert item_settings_store.read_item(conn, "widget", "core.stat-running").enabled is False
        row = conn.execute(
            f"SELECT enabled, values_json FROM {ITEM_SETTINGS_TABLE} WHERE kind='widget' AND item_id='custom.widget'"
        ).fetchone()
        assert row is not None
        assert bool(row["enabled"]) is True
        assert json.loads(row["values_json"]) == {"limit": 25, "nested": {"ok": True}}

    assert topics.ITEM_SETTINGS in notified
    assert any(n.get("type") == "item_settings.changed" for n in b.notices)

    m.now += 1000
    with closing(a.db()) as conn:
        conn.execute(f"DELETE FROM {ITEM_SETTINGS_TABLE} WHERE kind='widget' AND item_id='custom.widget'")
        conn.commit()
    a.step()
    assert a.rows()["ws:custom.widget"][0] == {"gone": True}

    m.converge(("a", "b"))
    notified.clear()
    b.step()
    with closing(b.db()) as conn:
        gone = conn.execute(
            f"SELECT 1 FROM {ITEM_SETTINGS_TABLE} WHERE kind='widget' AND item_id='custom.widget'"
        ).fetchone()
        assert gone is None
    assert topics.ITEM_SETTINGS in notified




def test_analytics_timeline_filters_timezone_and_widget_state_sync(dash_mesh: Any) -> None:
    m, _topics = dash_mesh("a", "b")
    a, b = m["a"], m["b"]

    a.set_prefs({
        "analytics_filters": {"range": "24h", "provider": "claude", "model": "claude-opus-4-6"},
        "analytics_timezone": "Europe/London",
        "timeline_filters": {"bookmarks": True, "compacts": False, "restarts": True, "sleeps": True, "restores": False},
        "widget_state": {
            "core.activity-log": {"showSystem": False, "limit": 50},
            "core.notes": {"pinned": True},
        },
    })

    m.seed_all()
    assert a.rows()["pref:analytics_timezone"][0] == "Europe/London"
    assert a.rows()["pref:analytics_filters"][0]["range"] == "24h"
    assert a.rows()["pref:timeline_filters"][0]["compacts"] is False
    assert a.rows()["wst:core.activity-log"][0] == {"showSystem": False, "limit": 50}
    assert a.rows()["wst:core.notes"][0] == {"pinned": True}

    m.converge(("a", "b"))
    b.step()

    bp = b.prefs()
    assert bp["analytics_filters"] == {"range": "24h", "provider": "claude", "model": "claude-opus-4-6"}
    assert bp["analytics_timezone"] == "Europe/London"
    assert bp["timeline_filters"] == {"bookmarks": True, "compacts": False, "restarts": True, "sleeps": True, "restores": False}
    assert bp["widget_state"] == {"core.activity-log": {"showSystem": False, "limit": 50}, "core.notes": {"pinned": True}}

    m.now += 1000
    b.set_prefs({
        "analytics_timezone": "America/New_York",
        "widget_state": {
            "core.activity-log": {"showSystem": True, "limit": 100},
            "core.tasks": {"sort": "priority"},
        },
    })
    b.step()
    assert b.rows()["wst:core.notes"][0] == {"gone": True}

    m.converge(("a", "b"))
    a.step()

    ap = a.prefs()
    assert ap["analytics_timezone"] == "America/New_York"
    assert ap["widget_state"] == {
        "core.activity-log": {"showSystem": True, "limit": 100},
        "core.tasks": {"sort": "priority"},
    }
    assert "core.notes" not in ap["widget_state"]

    assert mesh_workspace_dash.normalize_host_for_wire({"host": "local"}, "iid-x") == {"host": "iid-x"}
    assert mesh_workspace_dash.normalize_host_for_local({"host": "iid-x"}, "iid-x") == {"host": "local"}
