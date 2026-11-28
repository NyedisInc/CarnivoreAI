
from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import resource_push, session_change_notice, session_group_store, session_sleep
from src.core.computers import direction
from src.core.db import connect, db_path_for, set_meta, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation import peer_hosts, peer_listing, peer_serve, shadow_rows
from src.core.federation.peer_link import CONNECTED, DISCONNECTED
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.layouts import store as layouts_store, style as layout_style
from src.core.mcp_usage import store as mcp_usage_store
from src.core.pack.globalsync import mesh_panel, mesh_workspace, panel, panel_apply
from src.core.pack.machines import capabilities as caps, config_state, restrictions
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import gossip, panel_kind, wire, workspace_kind
from src.core.pack.meshdata.store import RecordStore
from src.core.pack.rollup_import import puller, relay_export
from src.core.preferences_push import broadcast as prefs_broadcast
from src.core.project_lineage.parents import parent_project_ids
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.row_looks.registry import Look
from src.core.stats import config as stats_config, pack_scope, project_groups, queries, rollup
from src.core.stats.plugin import live as stats_live, revision as stats_revision, rollup as stats_write
from src.core.stats.store import StatsStore
from src.core.ui_preferences_store import UiPreferencesStore
from src.models import Session, SessionInfo, SessionStatus
from src.models.stats import QueryRequest

IID_ALPHA = "aaaaaaaa-0000-4000-8000-000000000001"
IID_MEMBER_B = "bbbbbbbb-0000-4000-8000-000000000002"
IID_MEMBER_C = "cccccccc-0000-4000-8000-000000000003"
IID_ONEWAY_D = "dddddddd-0000-4000-8000-000000000004"

DEFAULT_IIDS: Dict[str, str] = {"a": IID_ALPHA, "b": IID_MEMBER_B, "c": IID_MEMBER_C, "d": IID_ONEWAY_D}
CERT = base64.b64encode(b"x" * 40).decode()
NOW_MS = 1_800_000_000_000
V2_CAPS: List[str] = [caps.CAP_MACHINE, caps.CAP_PIPELINE_ROLLUP, caps.CAP_ROLLUP_RELAY, caps.CAP_MESH, caps.CAP_ROLLUP_V2]


def uid(n: int) -> str:
    return f"{n:032x}"


def u36(n: int) -> str:
    return f"{n:08x}-0000-0000-0000-{n:012x}"


def row_look_id(n: int) -> str:
    return f"{n:016x}"


def iso_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def clear_stats_caches() -> None:
    project_groups.forget()
    pack_scope._cache.clear()
    queries._COV_CACHE.clear()
    queries._DIM_CACHE.clear()
    rollup.forget_index()


def build_query(
    metric: str,
    start: int,
    end: int,
    *,
    operation: str = "timeline",
    resolution: str = "5minute",
    scope: str = "pack",
    group_by: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> QueryRequest:
    body: Dict[str, Any] = {
        "metric": metric, "from": iso_utc(start), "to": iso_utc(end),
        "operation": operation, "resolution": resolution, "scope": scope, "filters": filters or {},
    }
    if group_by is not None:
        body["group_by"] = group_by
    return QueryRequest.model_validate(body)


def build_large_home_layout() -> Dict[str, Any]:
    cells_24: List[Dict[str, Any]] = []
    cells_12: List[Dict[str, Any]] = []
    big_rows: List[Dict[str, Any]] = []
    for i in range(45):
        cid = f"analytics:{uuid.UUID(int=i + 10)}"
        cells_24.append({"id": cid, "x": (i % 3) * 8, "y": (i // 3) * 6, "w": 8, "h": 6, "meta": "m" * 180})
        cells_12.append({"id": cid, "x": (i % 2) * 6, "y": (i // 2) * 6, "w": 6, "h": 6})
        big_rows.append({"id": f"r{i + 1}", "kind": "px", "size": 240, "slots": [{"id": cid, "fr": 1.0, "note": "r" * 40}]})
    return {
        "v": 2, "active": "ops", "analytics_seed": 2,
        "boards": [
            {
                "id": "home", "name": "Home",
                "layout": {
                    "v": 6, "rows": big_rows, "hidden": ["skills"], "heroCollapsed": False, "collapsed": [],
                    "headerOff": ["stat-running"],
                    "grid": {
                        "v": 1, "cols": 24, "pitch": 40, "rowsSig": "0123456789abcdef",
                        "order": [cell["id"] for cell in cells_24], "layouts": {"24": cells_24, "12": cells_12},
                    },
                },
            },
            {
                "id": "ops", "name": "Ops Room",
                "layout": {
                    "v": 6,
                    "rows": [{"id": "r1", "kind": "px", "size": 220, "slots": [{"id": "running-sessions", "fr": 1.0}]}],
                    "hidden": [], "heroCollapsed": True, "collapsed": ["ledger"],
                },
            },
        ],
    }


class SimClock:

    def __init__(self, start: float) -> None:
        self.now: float = float(start)

    def __call__(self) -> float:
        return self.now


class LocalRowLooks:

    def __init__(self) -> None:
        self._looks: Dict[str, Look] = {}

    def listing(self) -> Dict[str, Look]:
        return dict(self._looks)

    def set_look(self, row_id: str, fields: Dict[str, Optional[str]]) -> Look:
        old = self._looks.pop(row_id, Look())
        new = Look(
            fields["color"] if "color" in fields else old.color,
            fields["icon"] if "icon" in fields else old.icon,
        )
        if new.color or new.icon:
            self._looks[row_id] = new
            return new
        return Look()

    def forget(self, row_id: str) -> None:
        self._looks.pop(row_id, None)


class _Reply:

    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def json(self) -> Any:
        return self._data


class StarSessionLinks:

    def __init__(
        self,
        owner: "PackParityNode",
        peers: Dict[str, Tuple["PackParityNode", str]],
        hub_links: Optional[Dict[str, "StarSessionLinks"]] = None,
        *,
        include_swarm: bool = False,
    ) -> None:
        self.owner, self._peers, self._hub_links, self._include_swarm = owner, peers, hub_links or {}, include_swarm

    def state(self, peer_id: str) -> str:
        entry = self._peers.get(peer_id)
        return entry[1] if entry is not None and entry[0].online else DISCONNECTED

    def client(self, peer_id: str) -> Optional["_StarSessionClient"]:
        entry = self._peers.get(peer_id)
        if entry is None or entry[1] != CONNECTED or not entry[0].online:
            return None
        return _StarSessionClient(entry[0], caller_id=self.owner.iid, links_for_hub=self._hub_links.get(peer_id), include_swarm=self._include_swarm)


class _StarSessionClient:

    def __init__(self, target: "PackParityNode", *, caller_id: str, links_for_hub: Optional[StarSessionLinks], include_swarm: bool) -> None:
        self.target, self.caller_id, self.links_for_hub, self.include_swarm = target, caller_id, links_for_hub, include_swarm

    async def request(self, _method: str, path: str, **_kw: Any) -> _Reply:
        if path == "/sessions/asleep":
            body: Any = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.target.open_db, include_swarm=self.include_swarm, caller_install_id=self.caller_id)
        elif path == "/sessions/list-and-asleep":
            owned = await peer_listing.for_caller(self.target.own_sessions, is_peer=True, open_db=self.target.open_db, include_swarm=self.include_swarm, caller_install_id=self.caller_id)
            asleep = await asyncio.to_thread(peer_serve.serve_asleep_to_peer, self.target.open_db, include_swarm=self.include_swarm, caller_install_id=self.caller_id)
            relayed = await asyncio.to_thread(peer_listing.relayed_for_peer, self.target.open_db, self.links_for_hub, caller_install_id=self.caller_id, include_swarm=self.include_swarm)
            body = {"list": [i.model_dump(mode="json") for i in owned], "asleep": asleep, "relayed": [i.model_dump(mode="json") for i in relayed]}
        else:
            owned = await peer_listing.for_caller(self.target.own_sessions, is_peer=True, open_db=self.target.open_db, include_swarm=self.include_swarm, caller_install_id=self.caller_id)
            body = [i.model_dump(mode="json") for i in owned]
        return _Reply(json.loads(json.dumps(body)))


class PackParityNode:

    def __init__(self, mesh: "PackParityMesh", name: str, iid: str, tmp: Path, now_s: float) -> None:
        self.mesh, self.name, self.iid, self.dir = mesh, name, iid, tmp / name
        self.dir.mkdir(parents=True, exist_ok=True)
        assert ensure_db_migrated(self.dir).status == "ok"
        with closing(self.open_db()) as conn:
            set_meta(conn, META_INSTALL_ID, self.iid)

        self.config_path = self.dir / "config.json"
        self.config_path.write_text("{}", encoding="utf-8")
        self.ui = UiPreferencesStore(lambda p=self.config_path: p)
        self.looks = LocalRowLooks()

        self.stats = StatsStore(self.dir)
        self.stats.initialize()
        stats_config.ensure_schema(self.stats)
        with self.stats.connect() as sconn:
            sconn.execute("UPDATE stats_settings SET enabled = 1")

        self.mcp_usage_db = mcp_usage_store.UsageStore(self.dir / "mcp_usage.db")
        self.clock = SimClock(now_s)
        self.online, self.panel_enabled = True, True
        self.restrictions = restrictions.Restrictions()
        self.broadcasts: List[Dict[str, Any]] = []
        self.notices: List[Dict[str, Any]] = []
        self.scheduler_events: List[Dict[str, Any]] = []
        self.own_sessions: List[SessionInfo] = []
        self.app_state = SimpleNamespace(
            ui_preferences_store=self.ui, stats_store=self.stats, node_name=name,
            stats_scheduler=SimpleNamespace(settings_changed=lambda s: self.scheduler_events.append(dict(s))),
        )
        self.panel_step = mesh_panel.attach(self.app_state, self.open_db, lambda: {"panel": self.panel_enabled}, self.dir / "pack" / "panel-stamps.json")
        self.workspace_step = mesh_workspace.attach(self.app_state, self.open_db, lambda: {"panel": self.panel_enabled}, self.dir / "pack", row_looks_api=self.looks, stats_store=self.stats)
        self.importer: Optional[puller.RollupImporter] = None

    def open_db(self) -> sqlite3.Connection:
        return connect(db_path_for(self.dir), create=False)

    def prefs(self) -> Dict[str, Any]:
        return dict(self.ui.read()["values"])

    def set_prefs(self, changes: Dict[str, Any]) -> Any:
        res = self.ui.update(changes)
        assert res.status in ("committed", "unchanged"), res.detail
        return res

    def pair_with(self, other: "PackParityNode", *, initiator: bool = False) -> None:
        with closing(self.open_db()) as conn:
            peer_hosts.upsert(conn, install_id=other.iid, label=other.name, grant_id=f"g-{self.name}-{other.name}", fid=f"f-{self.name}-{other.name}", initiator=initiator)
            conn.commit()

    def mark_one_way_peer(self, target_iid: str) -> None:
        with closing(self.open_db()) as conn:
            conn.execute(
                "INSERT INTO computer_links (peer_install_id, role, transport, inbound_control, updated_at) "
                "VALUES (?, 'peer', 'ssh', 0, '2026-11-26T00:00:00Z') ON CONFLICT(peer_install_id) DO UPDATE SET inbound_control = 0",
                (target_iid,),
            )
            conn.commit()

    def add_company(self, name: str, cuid: str, *, hue: Optional[int] = None, parent_id: Optional[int] = None) -> int:
        with closing(self.open_db()) as conn:
            cid = int(conn.execute("INSERT INTO companies (name, uid, hue, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, 't', 't')", (name, cuid, hue, parent_id)).lastrowid)
            conn.commit()
        return cid

    def add_project(
        self, name: str, puid: str, *, root: Optional[str] = None, company_id: Optional[int] = None,
        color: Optional[str] = None, archived_at: Optional[str] = None, air_gap: int = 0,
    ) -> int:
        proj_root = root or f"/work/{self.name}/{puid[:8]}"
        with closing(self.open_db()) as conn:
            pid = int(conn.execute(
                "INSERT INTO projects (root, raw_path, display_name, source, presence, company_id, color, archived_at, air_gap, created_at, updated_at, last_opened_at, uid) "
                "VALUES (?, ?, ?, 'user', 'present', ?, ?, ?, ?, 't', 't', 't', ?)",
                (proj_root, proj_root, name, company_id, color, archived_at, air_gap, puid),
            ).lastrowid)
            conn.commit()
        return pid

    def add_live_session(
        self, session_uuid: str, tmux_name: str, *, working_dir: str, project_id: Optional[int] = None,
        last_work_at: Optional[str] = None, tmux_created_epoch: int = 1_760_000_100,
    ) -> int:
        with closing(self.open_db()) as conn:
            row_id = add_row(conn, uuid=session_uuid, name=tmux_name, epoch=tmux_created_epoch, origin="created", socket="carnivore")
            conn.execute("UPDATE sessions SET working_dir = ?, project_id = ?, last_work_at = ? WHERE id = ?", (working_dir, project_id, last_work_at, row_id))
            conn.commit()
        self.own_sessions.append(SessionInfo(
            session=Session(id=f"ses_{self.name}_{tmux_name}", working_dir=working_dir, status=SessionStatus.RUNNING, created_at=datetime(2026, 11, 26, tzinfo=timezone.utc), tmux_created_epoch=tmux_created_epoch),
            tmux_session=tmux_name, session_row_id=row_id, project_id=project_id, activity_status="working", startup_gate="ready",
        ))
        return row_id

    def add_asleep_session(
        self, session_uuid: str, tmux_name: str, *, working_dir: str, project_id: Optional[int] = None,
        last_work_at: Optional[str] = None, tmux_created_epoch: int = 1_760_000_200,
    ) -> int:
        with closing(self.open_db()) as conn:
            row_id = add_row(conn, uuid=session_uuid, name=tmux_name, epoch=tmux_created_epoch, origin="created", socket="carnivore")
            conn.execute(
                "UPDATE sessions SET working_dir = ?, project_id = ?, last_work_at = ?, lifecycle = 'stopped', lifecycle_source = ?, title = ? WHERE id = ?",
                (working_dir, project_id, last_work_at, session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER, f"Asleep {tmux_name}", row_id),
            )
            conn.commit()
        return row_id

    def create_layout(self, layout_uuid: str, name: str, row_ids: Sequence[int], *, style: Tuple[str, Optional[str], str], off_row_ids: Sequence[int] = ()) -> int:
        slots = [f"terminal:row:{rid}" for rid in row_ids]
        shape = {"layout": None, "groups": {slots[0]: {"tabs": slots}}}
        with closing(self.open_db()) as conn:
            top = int(conn.execute("SELECT COALESCE(MAX(position), -1) FROM layouts").fetchone()[0])
            lid = int(conn.execute(
                "INSERT INTO layouts (layout_uuid, name, name_fold, position, shape, revision, source_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, NULL, 't', 't')",
                (layout_uuid, name, layouts_store.fold_name(name), top + 1, json.dumps(shape)),
            ).lastrowid)
            for pos, rid in enumerate(row_ids):
                conn.execute("INSERT INTO layout_members (layout_id, session_row_id, position) VALUES (?, ?, ?)", (lid, rid, pos))
            layout_style.write(conn, layout_uuid, style[0], style[1], style[2], now="t")
            for rid in off_row_ids:
                conn.execute("INSERT INTO layout_broadcast_off (layout_id, session_row_id, updated_at) VALUES (?, ?, 't')", (lid, rid))
            conn.commit()
        return lid

    def seed_conversation_stats(
        self, *, path_key: int, conversation_id: str, provider: str, agent_kind: str, account_id: str,
        subagent_type: str, model: str, project_hash: str,
        usage_points: Sequence[Tuple[int, Tuple[int, int, int, int], int, int]],
        turns: int = 2, activity_points: Sequence[Tuple[int, Tuple[float, float, float, int, int, float, float]]] = (),
    ) -> None:
        ts_list = [pt[0] for pt in usage_points]
        with self.stats.connect() as sconn:
            sconn.execute(
                "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, account_id, subagent_type, first_minute, last_minute) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path_key, conversation_id, provider, agent_kind, account_id, subagent_type, min(ts_list), max(ts_list)),
            )
            src_id = int(sconn.execute("SELECT id FROM dim_source WHERE path_key = ?", (path_key,)).fetchone()[0])
            batch = stats_write.Batch(src_id)
            for minute_ts, counts, cost_nano, msgs in usage_points:
                batch.add_usage(minute_ts, model, project_hash, "v1", counts, cost_nano, msgs)
            if turns:
                batch.add_counter(max(ts_list), model, project_hash, "turns", "total", turns)
            batch.flush(sconn, {})
            for minute_ts, vals in activity_points:
                stats_live.add_activity(sconn, minute_ts, ("local", provider, conversation_id, project_hash, model, agent_kind), vals)
                stats_live.add_coverage(sconn, minute_ts, float(vals[0]))

    def seed_quota(self, *, minute_ts: int, provider: str, account_id: str, window: str, utilization: float, fetched_at: float, state: str = "ok") -> None:
        with self.stats.connect() as sconn:
            stats_live.put_quota(sconn, {
                "minute_ts": minute_ts, "provider": provider, "account_id": account_id, "window": window,
                "reset_at": iso_utc(minute_ts + 5 * 3600), "utilization": utilization, "fetched_at": iso_utc(int(fetched_at)), "state": state,
            })

    def seed_mcp_call(self, call_id: str, started_at: int, tool: str, outcome: str = "ok", duration_ms: int = 50) -> None:
        with closing(self.open_db()) as conn, transaction(conn):
            conn.execute("INSERT INTO mcp_events (call_id, started_at, tool, caller_kind, outcome, duration_ms) VALUES (?, ?, ?, 'pane', ?, ?)", (call_id, float(started_at), tool, outcome, duration_ms))

    def rebuild_local_mcp_usage(self) -> None:
        merged: Dict[Tuple[str, str, str, str], int] = {}
        with closing(self.open_db()) as conn:
            for started_at, tool, caller_kind, outcome in conn.execute("SELECT started_at, tool, caller_kind, outcome FROM mcp_events"):
                day_str = datetime.fromtimestamp(float(started_at), timezone.utc).date().isoformat()
                short_tool = tool.split("__", 2)[2] if tool.startswith("mcp__") and len(tool.split("__", 2)) == 3 else tool
                key = (day_str, short_tool, str(caller_kind), str(outcome))
                merged[key] = merged.get(key, 0) + 1
        self.mcp_usage_db.replace_from("0000-00-00", [(d, t, ck, oc, c) for (d, t, ck, oc), c in sorted(merged.items())])

    def rollup_snapshot(self) -> Dict[str, Any]:
        with self.stats.connect() as sconn:
            stats_rev = stats_revision.current(sconn)
        return {"install_id": self.iid, "pipeline_rev": {"stats": stats_rev, **relay_export.advertised(self.open_db)}}

    def step_all(self) -> None:
        self.mesh.active_node = self
        asyncio.run(self.panel_step(self.mesh.service(self.name), self.mesh.roster()))
        asyncio.run(self.workspace_step(self.mesh.service(self.name), self.mesh.roster()))

    def panel_rows(self) -> Dict[str, Any]:
        return self.mesh.stores[self.name].kind_rows(self.mesh.roster(), panel_kind.KIND)

    def workspace_rows(self) -> Dict[str, Any]:
        return self.mesh.stores[self.name].kind_rows(self.mesh.roster(), workspace_kind.KIND)

    def pull_rollups_from(self, target: "PackParityNode") -> None:
        assert self.importer is not None
        self.clock.now += puller.MIN_INTERVAL_SECONDS + 5.0
        asyncio.run(self.importer.maybe_pull(target.iid, target.rollup_snapshot()))


class PackParityMesh:

    def __init__(
        self, tmp: Path, names: Sequence[str] = ("a", "b", "c"), *,
        no_logins: Optional[Set[str]] = None, one_way: Optional[Set[str]] = None, now_s: Optional[float] = None,
    ) -> None:
        self.now_ms, self.now_s = NOW_MS, float(int(time.time()) if now_s is None else now_s)
        self.no_logins, self.one_way = set(no_logins or ()), set(one_way or ())
        self.keys = {n: DeviceKey.from_seed(bytes([i + 41]) * 32) for i, n in enumerate(names)}
        self.nodes = {n: PackParityNode(self, n, DEFAULT_IIDS.get(n, f"iid-{n}"), tmp, self.now_s) for n in names}
        self.signing = {n: Signing(install_id=self.nodes[n].iid, load_key=lambda n=n: self.keys[n], pinned_key=lambda _i: None) for n in names}
        self.stores = {n: RecordStore(tmp / f"{n}-mesh.db", self.nodes[n].iid, wall=lambda: self.now_ms, signing=self.signing[n]) for n in names}
        self.alpha = names[0]
        self.active_node = self.nodes[self.alpha]
        for name in names:
            self._wire_rollup_importer(name)

    def __getitem__(self, name: str) -> PackParityNode:
        return self.nodes[name]

    def by_iid(self, iid: str) -> PackParityNode:
        return next(n for n in self.nodes.values() if n.iid == iid)

    def pair_star(self, *, include_d: bool = False) -> None:
        a, b, c = self["a"], self["b"], self["c"]
        a.pair_with(b, initiator=True)
        b.pair_with(a, initiator=False)
        a.pair_with(c, initiator=True)
        c.pair_with(a, initiator=False)
        if include_d and "d" in self.nodes:
            d = self["d"]
            a.pair_with(d, initiator=True)
            d.pair_with(a, initiator=False)
            a.mark_one_way_peer(d.iid)

    def roster(self) -> RosterV2:
        rows = [
            RosterComputerV2(
                install_id=node.iid, label=n, fed_public_key=b64url(self.keys[n].raw_pub), cert=CERT,
                mesh=True, may_receive_logins=n not in self.no_logins, one_way=n in self.one_way,
            )
            for n, node in self.nodes.items()
        ]
        return RosterV2(generation=1, alpha=self.nodes[self.alpha].iid, home=self.nodes[self.alpha].iid, issued_at=1, computers=rows)

    def service(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(store=self.stores[name], signing=self.signing[name], pass_gen=None)

    def sync_mesh(self, src: str, dst: str) -> None:
        if not self.nodes[src].online or not self.nodes[dst].online:
            return
        lst = self.roster()

        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            answer, _ = wire.handle_sync(self.stores[dst], json.loads(json.dumps(body)), self.nodes[src].iid, lst, self.now_ms)
            return json.loads(json.dumps(answer))

        asyncio.run(wire.run_sync(self.stores[src], call, lst, self.nodes[dst].iid, lambda: self.now_ms))

    def converge_star(self, *, edges: Optional[Sequence[Tuple[str, str]]] = None, rounds: int = 3) -> None:
        for _ in range(rounds):
            for x, y in (edges if edges is not None else (("a", "b"), ("a", "c"))):
                self.sync_mesh(x, y)
                self.sync_mesh(y, x)

    def step_all(self, names: Optional[Iterable[str]] = None) -> None:
        for name in (names if names is not None else list(self.nodes)):
            if self.nodes[name].online:
                self.nodes[name].step_all()

    def _wire_rollup_importer(self, name: str) -> None:
        node = self.nodes[name]

        def post_for(peer_iid: str) -> Optional[Callable[[str, str, Optional[dict]], Any]]:
            target = self.by_iid(peer_iid)
            if not target.online or not node.online:
                return None

            async def post(_method: str, path: str, _body: Optional[dict]) -> Tuple[int, Any]:
                if direction.contained(node.iid):
                    return 403, {"code": direction.REFUSAL_CODE}
                q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
                page = relay_export.serve_stream(
                    target.stats, target.open_db, caller=node.iid, stream=q.get("stream"),
                    since_revision=int(q["since_rev"]), until_revision=int(q["until_rev"]) if "until_rev" in q else None,
                    cursor=q.get("cursor"), max_bytes=int(q["max_bytes"]),
                    signing=self.signing[target.name] if caps.mesh_on() else None,
                    include_v2=q.get("v2") in ("1", "true", "True"),
                )
                return 200, json.loads(json.dumps(page))

            return post

        node.importer = puller.RollupImporter(node.open_db, post_for, lambda _iid: list(V2_CAPS), node.clock, self_id=node.iid, held_list=self.roster)

    def pull_rollups_star(self) -> None:
        a, b, c = self["a"], self["b"], self["c"]
        a.pull_rollups_from(b)
        a.pull_rollups_from(c)
        b.pull_rollups_from(a)
        c.pull_rollups_from(a)


def snapshot_agent_bar(node: PackParityNode) -> Dict[str, Any]:
    with closing(node.open_db()) as conn:
        companies = {r["uid"]: (r["name"], r["hue"]) for r in conn.execute("SELECT uid, name, hue FROM companies WHERE uid IS NOT NULL")}
        cid_to_uid = {int(r["id"]): r["uid"] for r in conn.execute("SELECT id, uid FROM companies WHERE uid IS NOT NULL")}
        proj_rows = conn.execute("SELECT id, uid, root, display_name, color, company_id, archived_at, host_key FROM projects WHERE uid IS NOT NULL").fetchall()
        pid_to_uid = {int(r["id"]): r["uid"] for r in proj_rows}
        derived_parents = parent_project_ids([{"id": r["id"], "root": r["root"], "host_key": r["host_key"], "archived_at": r["archived_at"]} for r in proj_rows])
        synced_parents = panel.synced_project_parents(conn)
        projects: Dict[str, Tuple[Any, ...]] = {}
        for r in proj_rows:
            puid = r["uid"]
            par_uid = pid_to_uid.get(derived_parents[r["id"]]) if r["host_key"] == LOCAL_HOST_KEY and r["id"] in derived_parents else synced_parents.get(puid)
            projects[puid] = (r["display_name"], r["color"], cid_to_uid.get(r["company_id"]), bool(r["archived_at"]), par_uid)
        groups: Dict[str, Tuple[Any, ...]] = {}
        for g in session_group_store.list_groups(conn):
            pkey = g.parent_key
            if pkey and pkey.startswith("c:") and pkey[2:].isdigit():
                pkey = f"cu:{cid_to_uid[int(pkey[2:])]}"
            elif pkey and pkey.startswith("p:") and pkey[2:].isdigit():
                pkey = f"pu:{pid_to_uid[int(pkey[2:])]}"
            groups[g.group_uuid] = (g.name, pkey, (g.style.colour, g.style.gradient, g.style.animation, g.style.icon), g.rule, len(g.member_session_uuids))
        layouts = [(ly.layout_uuid, ly.name, (ly.colour, ly.gradient, ly.animation), [m.broadcast for m in ly.members], len(ly.members)) for ly in layouts_store.list_layouts(conn)]
        norm_collapsed: List[str] = []
        for entry in (node.prefs().get("drawer_arrangement") or {}).get("collapsed") or []:
            if entry.startswith("c:") and entry[2:].isdigit():
                norm_collapsed.append(f"cu:{cid_to_uid[int(entry[2:])]}")
            elif entry.startswith("p:") and entry.endswith(":agents") and entry[2:-7].isdigit():
                norm_collapsed.append(f"pu:{pid_to_uid[int(entry[2:-7])]}:agents")
            elif entry.startswith("p:") and entry[2:].isdigit():
                norm_collapsed.append(f"pu:{pid_to_uid[int(entry[2:])]}")
            else:
                norm_collapsed.append(entry)

    prefs = node.prefs()
    return {
        "companies": companies, "projects": projects, "groups": groups, "layouts": layouts,
        "pinned_layouts": [p for p in (prefs.get("drawer_arrangement") or {}).get("pinned", []) if p.startswith("layout:")],
        "collapsed": sorted(norm_collapsed),
        "prefs": {k: prefs.get(k) for k in ("theme", "sidebar_density", "sidebar_layout", "sidebar_show_leaders", "sidebar_show_archived", "layout_tabs", "stats_bar_rate", "stats_bar_window")},
        "row_looks": {k: (v.color, v.icon) for k, v in node.looks.listing().items()},
    }


def install_mesh_monkeypatches(monkeypatch: Any) -> Tuple[Dict[str, Optional[PackParityMesh]], List[str], Set[str]]:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", True)
    monkeypatch.setattr(gossip, "STEPS", [])
    active_box: Dict[str, Optional[PackParityMesh]] = {"mesh": None}
    notified_topics: List[str] = []
    contained_ids: Set[str] = set()
    monkeypatch.setattr(direction, "contained", lambda iid: iid in contained_ids)
    monkeypatch.setattr(direction, "one_way_ids", lambda: sorted(contained_ids))
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=lambda: restrictions.Restrictions() if active_box["mesh"] is None else active_box["mesh"].active_node.restrictions))
    monkeypatch.setattr(resource_push, "notify", lambda topic: notified_topics.append(topic))

    async def quiet_announce(_state: Any, _report: Any, _result: Any) -> bool:
        return False

    monkeypatch.setattr(panel_apply, "announce", quiet_announce)
    monkeypatch.setattr(session_change_notice, "publish", lambda st, fr: active_box["mesh"].nodes[st.node_name].notices.append(dict(fr)) if active_box["mesh"] and hasattr(st, "node_name") else None)

    async def fake_broadcast(app_state: Any, result: Any, client_id: Any) -> None:
        if active_box["mesh"] is not None and hasattr(app_state, "node_name"):
            active_box["mesh"].nodes[app_state.node_name].broadcasts.append({"changed": dict(result.changed), "client_id": client_id})

    monkeypatch.setattr(prefs_broadcast, "broadcast_changed", fake_broadcast)
    return active_box, notified_topics, contained_ids


def sync_direct_sessions_as_shadows(src: PackParityNode, dst: PackParityNode, sess_uuids: Sequence[str]) -> None:
    with closing(src.open_db()) as sconn:
        rows: List[Dict[str, Any]] = []
        for suuid in sess_uuids:
            row = sconn.execute(
                "SELECT s.id, s.tmux_name, s.working_dir, p.uid AS project_uid "
                "FROM sessions s LEFT JOIN projects p ON p.id = s.project_id WHERE s.session_uuid = ?",
                (suuid,),
            ).fetchone()
            assert row is not None, suuid
            entry: Dict[str, Any] = {
                "session_uuid": suuid, "row_id": int(row["id"]), "name": row["tmux_name"],
                "working_dir": row["working_dir"] or f"/work/{src.name}", "label": row["tmux_name"],
            }
            if row["project_uid"]:
                entry["project_uid"] = row["project_uid"]
            rows.append(entry)
    with closing(dst.open_db()) as dconn:
        host = peer_hosts.get(dconn, src.iid, include_mesh=True)
        assert host is not None, f"{dst.name} must be paired with {src.name}"
        shadow_rows.sync_peer(dconn, host_key=host.key, peer_install_id=src.iid, complete=True, rows=rows)
        dconn.commit()
