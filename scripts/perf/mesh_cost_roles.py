
from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import resource
import shutil
import socket
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "perf")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HOPS = {"_live_grant_for": "hop1", "_read_local": "hop2"}
EVENTS = "/ws/events?listing=push"
OWNER_ROWS = 10
_NS = uuid.UUID("5d2c0de5-0000-4000-8000-000000000001")


def refuse_live_tmux() -> None:
    for name, value in os.environ.items():
        if name.upper().startswith(("CARNIVORE", "CLOUDE")) and "TMUX" in name.upper() and value == "cloude":
            raise SystemExit("refusing to run beside the live cloude tmux socket")


def build_rows(iid: str, count: int) -> List[Dict[str, Any]]:
    from src.models import Session, SessionInfo, SessionStatus

    rows = []
    for n in range(count):
        info = SessionInfo(
            session=Session(id=f"ses_{iid}_{n:04d}", working_dir=f"/Users/dev/projects/{iid}/service-{n:04d}", status=SessionStatus.RUNNING),
            tmux_session=f"carnivore_{iid}_{n:04d}", label=f"working on service {n}", agent_type="claude", agent_family="claude",
            activity_status="idle", session_uuid=str(uuid.uuid5(_NS, f"{iid}/{n}")), origin_install_id=iid, host_key="local", session_row_id=n + 1)
        rows.append(info.model_dump(mode="json"))
    return rows


def load_plan(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


def key_for(seed_hex: str) -> Any:
    from src.core.relay_identity.device_key import DeviceKey

    return DeviceKey.from_seed(bytes.fromhex(seed_hex))


def caps_list() -> List[str]:
    from src.core.pack.machines import capabilities

    return ["pack.machine", capabilities.CAP_SETTINGS_SIGNED, capabilities.CAP_ROSTER, capabilities.CAP_ROSTER_V2, capabilities.CAP_MESH]


def make_pack(iid: str, label: str, key: Any, alpha_iid: str, alpha_pub: str, state_file: Path) -> Any:
    from datetime import datetime

    from src.core.pack.machines import capabilities, config_state, exchange, settings_sign

    capabilities.register(capabilities.CAP_MACHINE, capabilities.CAP_SETTINGS_SIGNED)
    state_file.write_text("{}")
    signing = settings_sign.Signing(install_id=iid, load_key=lambda: key, pinned_key=lambda who: alpha_pub if who == alpha_iid else None)

    class _Collector:

        def hid_idle_seconds(self, wanted: bool) -> None:
            return None

        def collect(self, **_kw: Any) -> Dict[str, Any]:
            return {}

    return exchange.PackMachines(install_id=iid, label=label, app_version="1.0", state=config_state.ConfigState(lambda: state_file), collector=_Collector(),
                                 default_master=lambda: alpha_iid, connected=lambda: [], notify=lambda topic, key_, every: None,
                                 local_now=lambda: datetime(2026, 10, 18, 12, 0), signing=signing, paired=lambda: True)


async def wait_file(path: Path, seconds: float) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except ValueError:
                pass
        await asyncio.sleep(0.1)
    raise TimeoutError(f"{path.name} never appeared")


def _identity(plan: Dict[str, Any], who: Dict[str, Any]) -> Any:
    from src.core.computers.tls_identity import ensure_link_identity

    return ensure_link_identity(key_for(who["seed"]), who["iid"], Path(who["dir"]))


def _cpu_seconds() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def stub_app(members: Dict[int, Dict[str, Any]], caps: List[str]) -> Any:
    from src.core.federation import peer_listing_feed as feed
    from src.core.federation.pairing import PROTOCOL_MAJOR
    from src.core.federation.peer_terminal_proxy import SUBPROTOCOL_MARKER
    from src.core.listing_push.diff import diff, keyed

    async def http(scope: Any, receive: Any, send: Any, rec: Dict[str, Any]) -> None:
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        path = scope["path"][7:] if scope["path"].startswith("/api/v1") else scope["path"]
        if path == "/federation/hello":
            out: Any = {"install_id": rec["iid"], "protocol": PROTOCOL_MAJOR, "capabilities": caps}
        elif path == "/federation/mesh/token":
            out = {"install_id": rec["iid"], "token": "stub-token", "expires_in": 900}
        elif path == "/sessions/list-and-asleep":
            out = {"list": rec["rows"], "asleep": []}
        elif path == "/sessions/list":
            out = rec["rows"]
        elif path == "/sessions/asleep":
            out = []
        else:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        data = json.dumps(out).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]})
        await send({"type": "http.response.body", "body": data})

    async def websocket(scope: Any, receive: Any, send: Any, rec: Dict[str, Any]) -> None:
        from src.core.federation import shadow_rows

        await receive()
        offered = [p for p in scope.get("subprotocols", []) if p == SUBPROTOCOL_MARKER]
        await send({"type": "websocket.accept", "subprotocol": offered[0] if offered else None})
        mesh = bool(rec.get("mesh"))
        stream, seq = uuid.uuid4().hex[:12], 0
        full = {"type": feed.FRAME_TYPE, "stream": stream, "seq": seq, "full": True, "list": diff(None, keyed(rec["rows"], feed.row_key)), "asleep": diff(None, [])}
        text = json.dumps(full)
        pushing = len(text) <= feed.frame_cap(mesh) and (not mesh or len(rec["rows"]) <= shadow_rows.MAX_ROWS)
        quiet = bool(rec.get("quiet"))
        rec["path"] = "push" if pushing else "poll"
        if pushing:
            await send({"type": "websocket.send", "text": text})
        next_full = time.monotonic() + feed.resync_wait(mesh)
        current = keyed(rec["rows"], feed.row_key)
        flip = 0
        while True:
            try:
                wait = max(0.0, next_full - time.monotonic()) if quiet else 2.0
                msg = await asyncio.wait_for(receive(), wait)
            except asyncio.TimeoutError:
                if not pushing:
                    continue
                if quiet:
                    next_full = time.monotonic() + feed.resync_wait(mesh)
                    seq += 1
                    current = keyed(rec["rows"], feed.row_key)
                    await send({"type": "websocket.send", "text": json.dumps({"type": feed.FRAME_TYPE, "stream": stream, "seq": seq, "full": True,
                                                                              "list": diff(None, current), "asleep": diff(None, [])})})
                    continue
                next_full = time.monotonic() + feed.resync_wait(mesh)
                flip += 1
                rows = [dict(r) for r in rec["rows"]]
                rows[0]["activity_status"] = "working" if flip % 2 else "idle"
                new = keyed(rows, feed.row_key)
                seq += 1
                await send({"type": "websocket.send", "text": json.dumps({"type": feed.FRAME_TYPE, "stream": stream, "seq": seq, "full": False,
                                                                          "list": diff(current, new), "asleep": diff([], [])})})
                current = new
                continue
            if msg["type"] == "websocket.disconnect":
                return

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            return
        rec = members.get(scope["server"][1])
        if rec is None:
            return
        if scope["type"] == "http":
            await http(scope, receive, send, rec)
        else:
            await websocket(scope, receive, send, rec)

    return app


async def run_s(plan: Dict[str, Any]) -> None:
    from src.core.computers import mesh, mesh_choice
    from src.core.computers.member_listener import MemberListener, Rendezvous
    from src.core.db import connect, db_path_for, set_meta
    from src.core.db_migration import ensure_db_migrated
    from src.core.db_models import META_INSTALL_ID
    from src.core.federation import mesh_listener, mesh_peers, peer_terminal_proxy
    from src.core.federation.peer_listener import _NoSignalServer
    from src.core.pack.machines import capabilities
    from src.core.computers.mux.session import bridge
    import uvicorn
    from websockets.exceptions import WebSocketException

    capabilities.MESH_BUILD_ON = True
    root, m_iid, alpha = Path(plan["root"]), plan["m"]["iid"], plan["alpha"]
    mesh_choice.choose_links = lambda lst, self_iid, **kw: [m_iid]
    template = root / "s_template"
    template.mkdir(mode=0o700)
    ensure_db_migrated(template)
    members: List[Dict[str, Any]] = plan["members"]
    stub_by_port: Dict[int, Dict[str, Any]] = {}
    for w in members:
        w["sock"] = socket.socket()
        w["sock"].setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        w["sock"].bind(("127.0.0.1", 0))
        w["sock"].listen(256)
        w["sock"].setblocking(False)
        w["stub_port"] = w["sock"].getsockname()[1]
        w["rows"] = build_rows(w["iid"], plan["rows"])
        stub_by_port[w["stub_port"]] = {"iid": w["iid"], "rows": w["rows"], "quiet": bool(plan.get("quiet")), "mesh": plan["mode"] != "star"}
        folder = root / f"s_state_{w['name']}"
        folder.mkdir(mode=0o700)
        shutil.copy2(db_path_for(template), db_path_for(folder))
        w["db"] = db_path_for(folder)
        with closing(connect(w["db"], create=False)) as conn:
            set_meta(conn, META_INSTALL_ID, w["iid"])
        w["ident"] = await asyncio.to_thread(_identity, plan, w)
        w["key"] = key_for(w["seed"])

        async def _follows() -> Dict[str, Any]:
            return {"follows": alpha["iid"]}

        w["listener"] = MemberListener(identity=w["ident"], rendezvous=Rendezvous(), host="127.0.0.1", follow_hello=_follows)
        if not await w["listener"].bind(0):
            raise RuntimeError("a member listener did not bind")
    (root / "ready_s.json").write_text(json.dumps({w["name"]: w["listener"].port for w in members}))
    lists = await wait_file(root / "lists.json", 200)

    server = _NoSignalServer(uvicorn.Config(stub_app(stub_by_port, caps_list()), lifespan="off", log_level="warning", access_log=False,
                                            proxy_headers=False, ws="websockets", log_config=None))
    stub_task = asyncio.create_task(server.serve(sockets=[w["sock"] for w in members]))

    async def stub_bridge(stream: Any, peer: str, mux: Any) -> None:
        owner = next((w for w in members if w.get("links") is not None and w["links"].current_mux(peer) is mux), None)
        if owner is None:
            stream.reset(2)
            return
        reader, writer = await asyncio.open_connection("127.0.0.1", owner["stub_port"])
        try:
            await bridge(stream, reader, writer)
        finally:
            writer.close()

    mesh_listener.bridge_inbound = stub_bridge
    m_cert = (await asyncio.to_thread(_identity, plan, plan["m"])).cert
    alpha_cert = (await asyncio.to_thread(_identity, plan, alpha)).cert

    async def read_m(reg: Any) -> None:
        while True:
            client = reg.client(m_iid)
            if client is None:
                await asyncio.sleep(0.5)
                continue
            try:
                ws = await peer_terminal_proxy.connect_upstream(client, EVENTS)
                async for _ in ws:
                    pass
            except (peer_terminal_proxy.PeerUnavailable, WebSocketException, OSError):
                await asyncio.sleep(1.0)

    tasks = []
    for start in range(0, len(members), 4):
        for w in members[start:start + 4]:
            pack = make_pack(w["iid"], w["name"], w["key"], alpha["iid"], alpha["pub"], root / f"s_cfg_{w['name']}.json")
            if not pack.custody.merge_roster_v2(lists["v2"], alpha["iid"]):
                raise RuntimeError("a member refused the signed list")
            await w["listener"].set_pins([alpha_cert], [m_cert])

            def opener(path: Path = w["db"]) -> Any:
                return connect(path, create=False)

            holder: Dict[str, Any] = {}
            reg = mesh_peers.MeshPeers(open_db=opener, self_iid=w["iid"], fed_dir=Path(w["dir"]), sign=w["key"].sign, trusted=lambda p, h=holder: h["l"].trusted(p),
                                       ensure=lambda *a, h=holder, **k: h["l"].ensure(*a, **k), touch=lambda i, h=holder: h["l"].touch(i))

            async def changed(h: Dict[str, Any] = holder) -> None:
                await h["l"].list_changed()

            links = mesh.MeshLinks(identity=w["ident"], iid=w["iid"], listener=w["listener"], custody=lambda p=pack: p.custody, after_change=changed,
                                   star_linked=lambda _iid: 0.0, backoff=lambda _a: 0.5, stagger=0.0, jitter=0.0, on_session=reg.session_changed,
                                   on_list=reg.list_changed)
            holder["l"], w["links"], w["reg"] = links, links, reg
            links.start()
            tasks.append(asyncio.create_task(links.list_changed()))
            tasks.append(asyncio.create_task(read_m(reg)))
        await asyncio.sleep(0.5)
    await asyncio.gather(*tasks[::2])
    samples = root / "s_cpu.jsonl"
    while True:
        with samples.open("a") as fh:
            fh.write(json.dumps({"t": time.time(), "cpu": _cpu_seconds(), "paths": sorted({r.get("path", "?") for r in stub_by_port.values()})}) + "\n")
        if stub_task.done():
            raise RuntimeError("the stub server stopped")
        if not root.exists():
            return
        await asyncio.sleep(2.0)


class Probe:

    def __init__(self) -> None:
        self.imports: Dict[str, List[float]] = {"push": [], "poll": [], "full": [], "fast": []}
        self.active, self.seq = 0, 0
        self.drifts: List[float] = []
        self.drift_import: List[float] = []
        self.drift_t: List[Any] = []
        self.drift_import_t: List[Any] = []
        self.hops: Dict[str, Dict[str, List[float]]] = {n: {"queue": [], "inside": [], "total": []} for n in HOPS.values()}
        self.full_at_submit = 0
        self.requests = 0
        self.armed = False
        self.gc: List[Any] = []
        self.locks: List[Any] = []
        self.hop_samples: Dict[str, List[Any]] = {n: [] for n in HOPS.values()}
        self.sync_ms: List[float] = []

    def begin(self) -> float:
        self.active += 1
        self.seq += 1
        return time.perf_counter()

    def end(self, kinds: Any, t0: float) -> None:
        if self.armed:
            ms = (time.perf_counter() - t0) * 1000
            for kind in ((kinds,) if isinstance(kinds, str) else kinds):
                self.imports[kind].append(ms)
        self.active -= 1
        self.seq += 1


_FULL: "contextvars.ContextVar[Optional[Dict[str, bool]]]" = contextvars.ContextVar("meshcost_full", default=None)


def install_probes(probe: Probe, slow_ms: float) -> None:
    import anyio
    import mesh_cost_split
    from src.api import peer_auth
    from src.core.federation import mesh_grants, mesh_listener, peer_listing, peer_listing_push, shadow_rows, shadow_rows_diff

    timed_tx = mesh_cost_split.timed_transaction(shadow_rows.transaction, probe.locks, lambda: probe.armed)
    shadow_rows.transaction = shadow_rows_diff.transaction = timed_tx
    orig_sync = shadow_rows.sync_peer

    def sync_peer(*a: Any, **k: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return orig_sync(*a, **k)
        finally:
            if probe.armed:
                probe.sync_ms.append((time.perf_counter() - t0) * 1000)

    shadow_rows.sync_peer = sync_peer

    orig_apply, orig_parse, orig_ingest = peer_listing_push.apply, peer_listing._parse_and_import, peer_listing.ingest

    async def ingest(*a: Any, **k: Any) -> Any:
        box = _FULL.get()
        if box is not None:
            box["full"] = True
        return await orig_ingest(*a, **k)

    async def apply(frame: Any, peer: Any, open_db: Any) -> bool:
        if frame.get("resync") is True:
            return await orig_apply(frame, peer, open_db)
        box: Dict[str, bool] = {"full": False}
        token = _FULL.set(box)
        t0 = probe.begin()
        try:
            return await orig_apply(frame, peer, open_db)
        finally:
            _FULL.reset(token)
            probe.end(("push", "full" if box["full"] else "fast"), t0)

    def parse(open_db: Any, peer: Any, body: Any, asleep_body: Any = None) -> Any:
        t0 = probe.begin()
        try:
            return orig_parse(open_db, peer, body, asleep_body)
        finally:
            probe.end("poll", t0)

    peer_listing_push.apply, peer_listing._parse_and_import, peer_listing.ingest = apply, parse, ingest

    def wrap_hop(orig: Any) -> Any:

        async def hop(fn: Any, *args: Any, **kwargs: Any) -> Any:
            name = HOPS.get(getattr(fn, "__name__", ""))
            if name is None:
                return await orig(fn, *args, **kwargs)
            limiter = anyio.to_thread.current_default_thread_limiter()
            if limiter.borrowed_tokens >= limiter.total_tokens:
                probe.full_at_submit += 1
            box: Dict[str, float] = {}
            submitted = time.perf_counter()

            def timed(*a: Any, **k: Any) -> Any:
                cpu0 = time.thread_time()
                box["start"] = time.perf_counter()
                try:
                    return fn(*a, **k)
                finally:
                    box["end"] = time.perf_counter()
                    box["cpu_ms"] = (time.thread_time() - cpu0) * 1000

            try:
                return await orig(timed, *args, **kwargs)
            finally:
                done = time.perf_counter()
                if "start" in box and "end" in box:
                    probe.hops[name]["queue"].append((box["start"] - submitted) * 1000)
                    probe.hops[name]["inside"].append((box["end"] - box["start"]) * 1000)
                    probe.hops[name]["total"].append((done - submitted) * 1000)
                    if probe.armed:
                        probe.hop_samples[name].append((box["start"], box["end"], box["cpu_ms"]))

        return hop

    peer_auth.run_in_threadpool = wrap_hop(peer_auth.run_in_threadpool)
    mesh_grants.run_in_threadpool = wrap_hop(mesh_grants.run_in_threadpool)
    orig_call = mesh_listener.MeshTag.__call__

    async def counted(self: Any, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            probe.requests += 1
        await orig_call(self, scope, receive, send)

    mesh_listener.MeshTag.__call__ = counted
    if slow_ms > 0:
        orig_rows = peer_listing.peer_rows

        async def slow_rows(*a: Any, **k: Any) -> Any:
            time.sleep(slow_ms / 1000.0)
            return await orig_rows(*a, **k)

        peer_listing.peer_rows = slow_rows


async def monitor(probe: Probe) -> None:
    while True:
        was_active, seq, t0 = probe.active, probe.seq, time.perf_counter()
        await asyncio.sleep(0.05)
        drift = (time.perf_counter() - t0 - 0.05) * 1000
        if not probe.armed:
            continue
        probe.drifts.append(drift)
        probe.drift_t.append((t0, drift))
        if was_active or probe.active or seq != probe.seq:
            probe.drift_import.append(drift)
            probe.drift_import_t.append((t0, drift))


def gc_record(probe: Probe) -> Dict[str, Any]:
    pauses = [(t, ms) for gen, ms, t in probe.gc if gen == 2]
    worst = max(probe.drift_import_t or probe.drift_t, key=lambda x: x[1], default=None)
    at_worst = bool(worst and any(t <= worst[0] + 0.05 + worst[1] / 1000.0 and t + ms / 1000.0 >= worst[0] for t, ms in pauses))
    return {"count": len(pauses), "max_ms": max((ms for _, ms in pauses), default=0.0), "at_worst_drift": at_worst}


def install_gc_probe(probe: Probe) -> None:
    import gc

    mark: Dict[str, float] = {}

    def hook(phase: str, info: Dict[str, Any]) -> None:
        if phase == "start":
            mark["t"] = time.perf_counter()
        elif probe.armed and "t" in mark:
            probe.gc.append((info["generation"], (time.perf_counter() - mark["t"]) * 1000, mark["t"]))

    gc.callbacks.append(hook)


def shadow_count(open_db: Any) -> int:
    from src.core.federation import peer_hosts, shadow_rows

    with closing(open_db()) as conn:
        keys = [p.key for p in peer_hosts.list_peers(conn, include_mesh=True)]
        if not keys:
            return 0
        marks = ",".join("?" * len(keys))
        return int(conn.execute(f"SELECT COUNT(*) FROM sessions WHERE origin = ? AND lifecycle = 'running' AND host_key IN ({marks})",
                                (shadow_rows.PEER_ORIGIN, *keys)).fetchone()[0])


async def sample_rss(samples: List[int]) -> None:
    from perf_client import sample_process

    got = await asyncio.to_thread(sample_process, os.getpid())
    if got is not None:
        samples.append(got.rss_kb)


async def idle_window(seconds: float, probe: Probe) -> Dict[str, Any]:
    rss: List[int] = []
    await sample_rss(rss)
    reqs0, wall0, subs = probe.requests, time.time(), []
    step = seconds / 5.0
    last_rss = time.monotonic()
    for _ in range(5):
        c0, t0 = _cpu_seconds(), time.perf_counter()
        deadline = time.monotonic() + step
        while time.monotonic() < deadline:
            await asyncio.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
            if time.monotonic() - last_rss >= 10.0:
                await sample_rss(rss)
                last_rss = time.monotonic()
        subs.append(100.0 * (_cpu_seconds() - c0) / (time.perf_counter() - t0))
    await sample_rss(rss)
    subs_sorted = sorted(subs)
    return {"cpu_pct": subs_sorted[2], "cpu_min": subs_sorted[0], "cpu_max": subs_sorted[-1], "cpu_windows": subs, "rss_kb_end": rss[-1] if rss else None,
            "rss_kb_max": max(rss) if rss else None, "rss_samples": len(rss), "requests": probe.requests - reqs0, "wall_start": wall0, "wall_end": time.time()}


def summary(values: List[float]) -> Dict[str, Any]:
    from dataclasses import asdict

    from perf_stats import summarize

    return asdict(summarize(values))


async def run_m(plan: Dict[str, Any]) -> Dict[str, Any]:
    mode, n_peers, rows_each = plan["mode"], plan["peers"], plan["rows"]
    if plan.get("switch_interval") is not None:
        sys.setswitchinterval(float(plan["switch_interval"]))
    from src.core.computers import mesh
    from src.core.computers.member_listener import MemberListener, Rendezvous
    from src.core.computers.runtime import ComputersRuntime
    from src.core.db import connect, db_path_for, set_meta
    from src.core.db_migration import ensure_db_migrated
    from src.core.db_models import META_INSTALL_ID
    from src.core.event_hub import EventHub
    from src.core.federation import mesh_listener, mesh_peers, mesh_powers, peer_event_stream, peer_hosts, peer_links, peer_listing, peer_listing_push
    from src.core.federation.peer_link import CONNECTED
    from src.core.pack.machines import capabilities
    from src.api import peer_auth, peer_listing_view, session_crud_routes, session_listing_collections
    from src.main import app

    root, m_iid, alpha = Path(plan["root"]), plan["m"]["iid"], plan["alpha"]
    capabilities.MESH_BUILD_ON = mode != "star"
    mesh_powers.OPEN_POWERS = mesh_powers.OPEN_POWERS | {mesh_powers.MESH_SESSIONS}
    state = Path(os.environ["CARNIVORE_STATE_DIR"])
    ensure_db_migrated(state)
    path = db_path_for(state)
    with closing(connect(path, create=False)) as conn:
        set_meta(conn, META_INSTALL_ID, m_iid)

    m_open = peer_auth.open_db
    app.state.event_hub = EventHub()
    from src.models import SessionInfo

    owner = [SessionInfo.model_validate(r) for r in build_rows(m_iid, OWNER_ROWS)]

    async def owner_listing(_state: Any) -> List[Any]:
        return list(owner)

    for module in (session_crud_routes, peer_listing_view, session_listing_collections):
        module.build_owner_listing = owner_listing
    peer_links.LINKS = peer_links.PeerLinks(open_db=m_open, listener_path="unused")
    peer_listing.reset()
    probe = Probe()
    install_probes(probe, plan["slow_ms"])
    install_gc_probe(probe)
    trace_a: Optional[Dict[str, Any]] = None
    if plan.get("product_gc"):
        from src.core.perf_hooks import gc_tuning

        gc_tuning.tune_after_startup()
    if plan.get("trace") and mode in ("none", "mesh"):
        import mesh_cost_trace as trace

        trace.start()
        trace_a = trace.mark(root)
        trace_snap_a = trace.snapshot()
    expected = OWNER_ROWS + n_peers * rows_each
    record: Dict[str, Any] = {"expected_rows": expected, "owner_rows": OWNER_ROWS}
    t_setup = time.monotonic()
    monitor_task = asyncio.create_task(monitor(probe))
    paused = {"on": False}
    background: List["asyncio.Task[Any]"] = []

    async def pass_loop() -> None:
        while True:
            if not paused["on"]:
                peer_event_stream.sync(app.state, m_open)
                await peer_listing.for_caller(await owner_listing(None), is_peer=False, open_db=m_open)
            await asyncio.sleep(2.0)

    try:
        if mode == "star":
            from src.core.federation.fed_key import fid_for
            from src.core.federation.grants import decode_public_key
            from src.core.federation.peer_link import CONNECTED as UP

            members = plan["members"]
            with closing(m_open()) as conn:
                for w in members:
                    peer_hosts.upsert(conn, install_id=w["iid"], label=w["name"], grant_id="star-" + w["name"], fid=fid_for(decode_public_key(w["pub"])), initiator=False)
            peer_links.LINKS = SimpleNamespace(state=lambda iid: UP, client=lambda iid: None, minor=lambda iid: 0, connected_clients=lambda: [])
            peers = {p.peer_install_id: p for p in peer_listing.read_peers(m_open)}
            frames = {}
            for w in members:
                rows = build_rows(w["iid"], rows_each)
                from src.core.federation import peer_listing_feed as feed
                from src.core.listing_push.diff import diff, keyed
                frames[w["iid"]] = (rows, {"type": feed.FRAME_TYPE, "stream": "s", "seq": 0, "full": True, "list": diff(None, keyed(rows, feed.row_key)), "asleep": diff(None, [])})
            record["import_path"] = "push" if all(len(json.dumps(f)) <= 512 * 1024 for _, f in frames.values()) else "poll"
            probe.armed = True
            rounds = max(1, 24 // max(1, len(members))) if members else 0
            for _ in range(rounds):
                for w in members:
                    rows, frame = frames[w["iid"]]
                    if record["import_path"] == "push":
                        await peer_listing_push.apply(frame, peers[w["iid"]], m_open)
                    else:
                        resp = SimpleNamespace(json=lambda r=rows: r)
                        peer_listing._SNAPSHOTS[w["iid"]] = peer_listing.Snapshot(await asyncio.to_thread(peer_listing._parse_and_import, m_open, peers[w["iid"]], resp, None) or [])
                    await asyncio.sleep(0.05)
            peer_listing.PUSHED.update(peers)
            record["setup_seconds"] = time.monotonic() - t_setup
            record["sessions"] = record["connected"] = record["followers"] = record["event_clients"] = None
        else:
            ident = await asyncio.to_thread(_identity, plan, plan["m"])
            key = key_for(plan["m"]["seed"])
            listener = MemberListener(identity=ident, rendezvous=Rendezvous(), host="127.0.0.1")
            if not await listener.bind(0):
                raise RuntimeError("the M listener did not bind")
            (root / "ready_m.json").write_text(json.dumps({"port": listener.port}))
            lists = await wait_file(root / "lists.json", 200)
            pack = make_pack(m_iid, "m", key, alpha["iid"], alpha["pub"], root / "m_cfg.json")
            if not pack.custody.merge_roster_v2(lists["v2"], alpha["iid"]):
                raise RuntimeError("M refused the signed list")
            alpha_cert = (await asyncio.to_thread(_identity, plan, alpha)).cert
            member_certs = [(await asyncio.to_thread(_identity, plan, w)).cert for w in plan["members"]]
            await listener.set_pins([alpha_cert], member_certs)

            async def no_sync(_flag: Any) -> None:
                pass

            ns = SimpleNamespace(_roster=SimpleNamespace(held_lists=pack.custody.held_lists, _wired=lambda: SimpleNamespace(runtime=SimpleNamespace(custody=pack.custody))),
                                 member_listener=listener, identity=ident, iid=m_iid, takeover=None, notify=lambda _t: None, _roster_cache=None,
                                 _sync_member_listener=no_sync, open_db=m_open, fed_dir=Path(plan["m"]["dir"]), fed_key=key)
            ns.after_roster_change = lambda: ComputersRuntime.after_roster_change(ns)
            await mesh_listener.start(app)
            mesh.attach(ns)
            await mesh.list_changed()
            background.append(asyncio.create_task(pass_loop()))
            ids = [w["iid"] for w in plan["members"]]
            deadline = time.monotonic() + plan["setup_seconds"]
            while time.monotonic() < deadline:
                links, reg = mesh._ACTIVE, mesh_peers.REGISTRY
                up = len(links._sessions) if links is not None else 0
                conn_n = sum(1 for i in ids if reg is not None and reg.state(i) == CONNECTED)
                shadow = await asyncio.to_thread(shadow_count, m_open)
                if up == n_peers and conn_n == n_peers and shadow == n_peers * rows_each:
                    break
                await asyncio.sleep(0.5)
            record["setup_seconds"] = time.monotonic() - t_setup
            record["setup_complete"] = up == n_peers and conn_n == n_peers and shadow == n_peers * rows_each
            await asyncio.sleep(3.0)
            probe.armed = True
        paused["on"] = True
        await asyncio.sleep(0.2)
        runs, wrong = [], 0
        for _ in range(plan["listing_runs"]):
            t0 = time.perf_counter()
            got = await peer_listing.for_caller(await owner_listing(None), is_peer=False, open_db=m_open)
            runs.append((time.perf_counter() - t0) * 1000)
            wrong += len(got) != expected
        paused["on"] = False
        if plan.get("drop_listing"):
            got = None
        if mode != "star":
            window = await idle_window(plan["idle_seconds"], probe)
        else:
            window = {"cpu_pct": None, "rss_kb_end": None, "rss_kb_max": None, "requests": 0, "wall_start": time.time(), "wall_end": time.time()}
        if trace_a is not None:
            trace_b = trace.mark(root)
            record["trace"] = {"A": trace_a, "B": trace_b, "diff": trace.diff(trace_snap_a, trace.snapshot()),
                               "peak_minus_current_B": trace_b["tracemalloc"]["peak"] - trace_b["tracemalloc"]["current"]}
            known = {id(r) for snap in peer_listing._SNAPSHOTS.values() for r in snap.rows}
            record["trace"]["session_info_holders"] = trace.holders("src.models.sessions.SessionInfo", known)
        if mode != "star":
            links, reg = mesh._ACTIVE, mesh_peers.REGISTRY
            ids = [w["iid"] for w in plan["members"]]
            record["sessions"] = len(links._sessions) if links is not None else 0
            record["connected"] = sum(1 for i in ids if reg is not None and reg.state(i) == CONNECTED)
            record["followers"] = len(peer_event_stream._TASKS)
            record["event_clients"] = app.state.event_hub.client_count
        record["shadow_rows"] = await asyncio.to_thread(shadow_count, m_open)
        record["expected_shadow_rows"] = n_peers * rows_each
        record["listing"] = summary(runs)
        record["wrong_row_counts"] = wrong
        record["import_push"], record["import_poll"] = summary(probe.imports["push"]), summary(probe.imports["poll"])
        if mode != "star":
            record["import_path"] = "push" if len(probe.imports["push"]) >= len(probe.imports["poll"]) and probe.imports["push"] else ("poll" if probe.imports["poll"] else "none")
        record["import_full"] = summary(probe.imports["full"] + probe.imports["poll"])
        record["import_fast"] = summary(probe.imports["fast"])
        record["import_counts"] = {k: len(v) for k, v in probe.imports.items()}
        record["drift_all"] = summary(probe.drifts)
        record["drift_during_import"] = summary(probe.drift_import)
        record["gc_gen2"] = gc_record(probe)
        record["idle"] = window
        record["hops"] = {name: {part: summary(vals) for part, vals in parts.items()} for name, parts in probe.hops.items()}
        record["hop_limiter_full"] = probe.full_at_submit
        import mesh_cost_split
        record["hop_split"] = mesh_cost_split.hop_split(probe.hop_samples, probe.locks)
        record["locks"] = {**mesh_cost_split.lock_summary(probe.locks), "full_imports_with_lock": len(probe.locks)}
        record["sync_ms"] = summary(probe.sync_ms)
        record["held_bytes"] = {name: mesh_cost_split.deep_size(obj) for name, obj in (
            ("peer_listing_push._HELD", peer_listing_push._HELD), ("peer_listing._SNAPSHOTS", peer_listing._SNAPSHOTS),
            ("peer_listing.PUSHED", peer_listing.PUSHED))}
        record["requests_total"] = probe.requests
        record["requests_per_minute"] = (window["requests"] * 60.0 / plan["idle_seconds"]) if mode != "star" else 0.0
        record["pushed_peers"] = len(peer_listing.PUSHED)
        record["event_tasks"] = len(peer_event_stream._TASKS)
        return record
    finally:
        monitor_task.cancel()
        for task in background:
            task.cancel()
        await peer_event_stream.stop()
        await mesh.detach()
        await mesh_listener.stop()


def main() -> None:
    refuse_live_tmux()
    os.environ.setdefault("DEFAULT_WORKING_DIR", str(Path(os.environ["CARNIVORE_STATE_DIR"]) / "wd"))
    os.environ.setdefault("LOG_DIRECTORY", str(Path(os.environ["CARNIVORE_STATE_DIR"]) / "logs"))
    os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
    os.environ.setdefault("JWT_SECRET", "testjwtnotreal")
    for name in ("DEFAULT_WORKING_DIR", "LOG_DIRECTORY"):
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("m", "s"), required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if args.role == "s":
        asyncio.run(run_s(plan))
        return
    try:
        record = asyncio.run(run_m(plan))
    except Exception as exc:  # noqa: BLE001
        import traceback

        record = {"error": f"{type(exc).__name__}: {exc}"[:200] + " @ " + " | ".join(traceback.format_exc().splitlines()[-4:])[:400]}
    out = Path(plan["root"]) / "m_result.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.replace(out)


if __name__ == "__main__":
    main()
