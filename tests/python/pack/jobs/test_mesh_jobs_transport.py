
from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from src.api import peer_auth, project_replica_routes as routes
from src.core.computers import mesh
from src.core.federation import mesh_peers, peer_hosts, peer_links
from src.core.pack.jobs import bundle_io, engine_run, member_link, target as target_mod
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.types import CollectAnswer, JobError, JobRecord, JobRequest, JobState
from src.core.pack.machines import capabilities
from src.core.pack.relay import member_reach
from src.core.pack.transport import blobs

SECRET = "marker-" + "body-text"


class Reply:

    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body


class Client:

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.reply, self.count = Reply(status, {} if body is None else body), 0

    async def request(self, method: str, path: str, **kw: Any) -> Reply:
        self.count += 1
        return self.reply


class Links:

    def __init__(self, clients: Optional[Dict[str, Any]] = None, caps: Optional[Dict[str, List[str]]] = None) -> None:
        self.clients, self.caps = clients or {}, caps or {}

    def client(self, iid: str) -> Any:
        return self.clients.get(iid)

    def capabilities(self, iid: str) -> List[str]:
        return list(self.caps.get(iid, []))


class Registry:

    def __init__(self, live: Optional[Dict[str, Any]] = None, dial: Any = None) -> None:
        self.live, self.dial, self.touches, self.dials = live or {}, dial, 0, []

    def client(self, iid: str) -> Any:
        if iid in self.live:
            self.touches += 1
        return self.live.get(iid)

    def peek(self, iid: str) -> Any:
        return self.live.get(iid)

    def touch(self, iid: str) -> None:
        self.touches += 1

    def capabilities(self, iid: str) -> Optional[List[str]]:
        return ["pack.transport.v1"] if iid in self.live else None

    async def connect(self, iid: str, timeout: Optional[float] = None) -> Any:
        self.dials.append(iid)
        return self.dial


@pytest.fixture()
def world(monkeypatch):
    w = SimpleNamespace(rows={}, mesh_touches=0)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(peer_links, "LINKS", Links())
    monkeypatch.setattr(mesh_peers, "REGISTRY", Registry())
    monkeypatch.setattr(peer_auth, "open_db", lambda: sqlite3.connect(":memory:"))
    monkeypatch.setattr(peer_hosts, "get", lambda _c, iid, include_mesh=False: w.rows.get(iid))
    monkeypatch.setattr(mesh, "touch", lambda _iid: setattr(w, "mesh_touches", w.mesh_touches + 1))
    return w


def _row(label: str, kind: str) -> Any:
    return SimpleNamespace(label=label, back_kind=kind, key=label, peer_install_id=label)


def test_switch_off_is_exactly_the_star_answer(monkeypatch):
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    monkeypatch.setattr(mesh_peers, "REGISTRY", None)
    star = Client()
    monkeypatch.setattr(peer_links, "LINKS", Links({"iid-b": star}, {"iid-b": ["x"]}))
    with pytest.raises(JobError) as e:
        target_mod.peer_target("iid-c")
    assert (e.value.code, e.value.detail, e.value.status) == ("unreachable", "that computer is not connected", 502)
    assert member_link.client_for("iid-b") is star and member_link.client_for("iid-c") is None
    assert member_link.caps_for("iid-b") == ["x"] and member_link.caps_for("iid-c") == []
    assert asyncio.run(member_link.connect_for("iid-c")) == (None, "that computer is not connected")

    async def go() -> Any:
        return member_link.hold("iid-c")
    assert asyncio.run(go()) is None
    with pytest.raises(HTTPException) as h:
        asyncio.run(routes.call_peer(_row("c-label", "mesh"), "POST", "/p", mesh=True))
    assert h.value.detail["detail"] == "c-label is not connected right now" and h.value.detail["code"] == "machine_unreachable"
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert member_link.client_for("iid-c") is None


def test_a_live_star_client_never_reads_a_row_or_dials(world, monkeypatch):
    star = Client()
    monkeypatch.setattr(peer_links, "LINKS", Links({"iid-b": star}))
    monkeypatch.setattr(member_link, "_row", lambda _i: (_ for _ in ()).throw(AssertionError("row read")))
    monkeypatch.setattr(mesh_peers.REGISTRY, "connect", lambda *_a: (_ for _ in ()).throw(AssertionError("dial")))
    assert asyncio.run(member_link.connect_for("iid-b")) == (star, "")
    t = target_mod.peer_target("iid-b")
    asyncio.run(t._post("admit", {}))
    assert star.count == 1


def test_a_member_with_a_live_mesh_client_is_reached_through_the_wrapper(world):
    mesh_client = Client(200, {"ok": True})
    mesh_peers.REGISTRY.live["iid-c"] = mesh_client
    t = target_mod.peer_target("iid-c")
    assert asyncio.run(t._post("admit", {})) == {"ok": True} and mesh_client.count == 1
    client, _ = asyncio.run(member_link.connect_for("iid-c"))
    assert isinstance(client, member_link._MemberClient)


def test_a_member_is_never_reached_through_the_alpha(world, monkeypatch):
    alpha = Client()
    monkeypatch.setattr(peer_links, "LINKS", Links({"iid-alpha": alpha}))
    world.rows["iid-c"] = _row("c-label", peer_hosts.MESH_BACK_KIND)
    t = target_mod.peer_target("iid-c")
    with pytest.raises(JobError) as e:
        asyncio.run(t._post("admit", {}))
    assert (e.value.code, e.value.detail) == ("unreachable", "c-label cannot be reached from this computer right now") and e.value.status == 502
    assert alpha.count == 0 and mesh_peers.REGISTRY.dials == ["iid-c"]


def test_a_star_computer_with_its_link_down_is_never_dialed_on_the_mesh(world):
    world.rows["iid-a"] = _row("alpha", "unix")
    assert asyncio.run(member_link.connect_for("iid-a")) == (None, "that computer is not connected")
    assert mesh_peers.REGISTRY.dials == []


def test_passing_member_refusals_retry_and_coded_ones_stay_refusals(world, monkeypatch):
    for status, body in ((401, {}), (403, {"detail": "nope"}), (403, None)):
        mesh_peers.REGISTRY.live["iid-c"] = Client(status, body)
        with pytest.raises(JobError) as e:
            asyncio.run(target_mod.peer_target("iid-c")._post("admit", {}))
        assert e.value.code == "unreachable", (status, body)
    mesh_peers.REGISTRY.live["iid-c"] = Client(403, {"detail": {"code": "pack_restricted", "detail": "no"}})
    with pytest.raises(JobError) as e:
        asyncio.run(target_mod.peer_target("iid-c")._post("admit", {}))
    assert e.value.code == "pack_restricted"
    monkeypatch.setattr(peer_links, "LINKS", Links({"iid-b": Client(401, {})}))
    with pytest.raises(JobError) as e:
        asyncio.run(target_mod.peer_target("iid-b")._post("admit", {}))
    assert e.value.code == "http_401"


def test_copies_never_dial(world):
    assert member_link.client_for("iid-c") is None and mesh_peers.REGISTRY.dials == []


def test_capability_reads_do_not_touch_and_a_real_post_does_once(world, monkeypatch):
    reg = mesh_peers.REGISTRY
    reg.live["iid-c"] = Client()
    getter = lambda: peer_links.LINKS  # noqa: E731
    assert member_link.caps_for("iid-c") == ["pack.transport.v1"]
    assert member_reach.caps_of(getter)("iid-c") == ["pack.transport.v1"]
    assert member_reach.gate_caps_of(getter)("iid-c") == ["pack.transport.v1"]
    assert member_reach.allows("iid-c") is False and member_reach.via_member(getter)("iid-c") is True
    assert reg.touches == 0
    assert member_link.client_for("iid-c") is not None and reg.touches == 1
    look = member_reach.lookup(getter)
    assert look("iid-c") is not None and look("iid-c") is not None and reg.touches == 1
    assert asyncio.run(look("iid-c")[0]("GET", "/x")) == (200, {}) and reg.touches == 2


def _engine(tmp_path, tgt):
    state, jobs = tmp_path / "s", tmp_path / "j"
    state.mkdir()
    jobs.mkdir()

    async def no_sleep(_s: float) -> None:
        await asyncio.sleep(0)

    eng = Engine(state_dir=state, jobs_root=jobs, install_id="iid-a", target_for=lambda _i: tgt, sleep=no_sleep, open_db=lambda: None)  # type: ignore[arg-type]
    ctx = {"request": {"command": "echo hi", "folder": "/work/app"}, "snap": {"toplevel": "/work/app", "head": None, "scope": "", "project_root": "/work/app",
                                                                               "notes": [], "roots": ["/work/app"], "dep_dirs": []}}
    now = eng._clock()
    return eng, eng.store.create_job(JobRecord(id="job-keep-1", idem_key="k1", project_uid="uid", project_name="app", request_json=json.dumps(ctx),
                                               state=JobState.RUNNING, peer_install_id="iid-b", peer_label="b", snapshot_commit="a" * 40,
                                               created_at=now, updated_at=now))


def test_the_keep_alive_lives_exactly_as_long_as_the_job(world, monkeypatch, tmp_path):
    monkeypatch.setattr(mesh_peers, "TOUCH_SECONDS", 0.01)
    gate = {}

    class T:
        install_id, label = "iid-b", "b"

        async def status(self, _jid: str) -> Any:
            await gate["ev"].wait()
            raise JobError("boom", "failed", 500)

    holds: List[Any] = []
    real_hold = member_link.hold
    monkeypatch.setattr(member_link, "hold", lambda iid: holds.append(real_hold(iid)) or holds[-1])

    async def go(on: bool) -> Any:
        gate["ev"] = asyncio.Event()
        eng, rec = _engine(tmp_path / ("on" if on else "off"), T())
        task = asyncio.create_task(eng._run(rec.id))
        await asyncio.sleep(0.1)
        if on:
            assert world.mesh_touches >= 3, "touches rise while the job runs"
        gate["ev"].set()
        await task
        assert eng.get(rec.id).state == JobState.FAILED
        seen = world.mesh_touches
        await asyncio.sleep(0.05)
        return seen, world.mesh_touches

    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    seen, later = asyncio.run(go(True))
    assert seen == later and holds[-1].cancelled()
    monkeypatch.setattr(mesh_peers, "REGISTRY", None)
    holds.clear()
    asyncio.run(go(False))
    assert holds == [None]


def test_a_result_from_another_computer_is_refused(world, tmp_path):
    inbox = blobs.Inbox(tmp_path / "pack" / "inbox")
    bid, data = blobs.new_id(), b"result"
    import hashlib
    sha = hashlib.sha256(data).hexdigest()
    inbox.put(bid, 0, data, sha, peer="iid-d")
    inbox.seal(bid, len(data), sha, "bundle")
    with pytest.raises(JobError):
        asyncio.run(target_mod.PeerTarget("iid-c", "c", None, None).fetch_result("j", CollectAnswer(blob_id=bid), tmp_path))
    assert bundle_io.received_path(tmp_path, bid, sender="iid-d")


def test_gh_login_style_lookups_stay_star_only(world, monkeypatch):
    star_row, member = _row("star", "unix"), _row("c-label", peer_hosts.MESH_BACK_KIND)
    monkeypatch.setattr(peer_hosts, "list_peers", lambda _c, include_mesh=False: [star_row] + ([member] if include_mesh else []))
    with pytest.raises(HTTPException) as e:
        routes.find_peer("c-label")
    assert e.value.status_code == 404 and e.value.detail["code"] == "unknown_machine"
    assert routes.find_peer("c-label", members=True) is member


def test_nothing_secret_reaches_a_log(world, capsys):
    member_link.log.info("probe", marker=SECRET)
    seen = capsys.readouterr()
    assert SECRET in seen.out + seen.err, "the capture must be able to see a log line"
    mesh_peers.REGISTRY.live["iid-c"] = Client(401, {"detail": SECRET})
    t = target_mod.peer_target("iid-c")
    with pytest.raises(JobError):
        asyncio.run(t._post("start", {"command": SECRET}))
    world.rows["iid-d"] = _row("d", peer_hosts.MESH_BACK_KIND)
    asyncio.run(member_link.connect_for("iid-d"))
    seen = capsys.readouterr()
    assert SECRET not in seen.out + seen.err
