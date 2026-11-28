
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Dict

import pytest
import structlog

from src.core.db import connect
from src.core.federation import mesh_grants, mesh_powers
from src.core.pack.jobs import host_admit, paths
from src.core.pack.jobs.host import Host
from src.core.pack.reserve.holds import Holds
from src.core.pack.machines import capabilities, config_state, restrictions as restrictions_mod
from src.main import app
from tests.python.computers.test_mesh_links import B, C  # noqa: F401
from tests.python.federation.test_mesh_route_inventory import _bearer, _code, _edit, _mint, env  # noqa: F401

P = "/api/v1/federation/pack/"
HOME_UID, REPLICA_UID, ELSEWHERE_UID, UNHELD_UID = "uid-home-0001", "uid-repl-0001", "uid-else-0001", "uid-none-0001"
MARK = {"can": {"marker": "own-snapshot"}, "pressure": {"pegged": False}}


@pytest.fixture()
def rig(env, tmp_path, monkeypatch):  # noqa: F811
    with closing(connect(env.path, create=False)) as conn:
        for uid, state, home_iid in ((HOME_UID, "home", None), (REPLICA_UID, "replica", B), (ELSEWHERE_UID, "replica", "iid-elsewhere")):
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, uid, pack_state, home_install_id) "
                         "VALUES (?, ?, ?, 'user', 'unchecked', 't', 't', ?, ?, ?)", (f"/r/{uid}", f"/r/{uid}", uid, uid, state, home_iid))
        conn.execute("INSERT INTO project_replicas (project_uid, install_id, state, created_at, updated_at) VALUES (?, ?, 'active', 't', 't')", (HOME_UID, B))
        conn.commit()
    state = {"restrictions": restrictions_mod.Restrictions()}
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    host = Host(state_dir=tmp_path, jobs_root=jobs, install_id=C, open_db=lambda: connect(env.path, create=False), admit=lambda _w: None,
                restrictions=lambda: state["restrictions"], live_agents=lambda: 0)
    monkeypatch.setattr(app.state, "pack_jobs_host", host, raising=False)
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=lambda: state["restrictions"]))
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: MARK)
    monkeypatch.setattr(host_admit, "HOLDS", Holds())
    env.head, env.state, env.host = _bearer(_mint(env)), state, host
    return env


def _post(rig, name: str, body: Dict[str, Any], head=None):
    return rig.client.post(P + "jobs/" + name, json=body, headers=head or rig.head)


def _admit(uid: str) -> Dict[str, Any]:
    return {"job_id": paths.new_job_id(), "project_uid": uid, "kind": "suite"}


def test_a_member_job_reaches_the_receiver_only_through_every_receiver_side_check(rig, monkeypatch, capsys):
    for uid in (HOME_UID, REPLICA_UID):
        assert _post(rig, "admit", _admit(uid)).status_code == 200, uid
        looked = _post(rig, "look", {"project_uid": uid})
        assert looked.status_code == 200 and looked.json() == {"snapshot": MARK, "project": "ok"}, looked.text

    r = _post(rig, "admit", _admit(ELSEWHERE_UID))
    assert r.status_code == 403 and _code(r) == "not_a_counterpart", r.text
    assert _post(rig, "look", {"project_uid": ELSEWHERE_UID}).json()["project"] == "not_a_counterpart"
    r = _post(rig, "admit", _admit(UNHELD_UID))
    assert r.status_code == 409 and _code(r) == "project_not_here", r.text
    assert _post(rig, "look", {"project_uid": UNHELD_UID}).json()["project"] == "project_not_here"

    rig.state["restrictions"] = restrictions_mod.Restrictions(may_host_agents=False)
    r = _post(rig, "admit", _admit(HOME_UID))
    assert r.status_code == 403 and _code(r) == "pack_restricted", r.text
    rig.state["restrictions"] = restrictions_mod.Restrictions(allowed_projects=[REPLICA_UID])
    assert _post(rig, "admit", _admit(HOME_UID)).status_code == 403 and _post(rig, "admit", _admit(REPLICA_UID)).status_code == 200
    rig.state["restrictions"] = restrictions_mod.Restrictions()

    assert mesh_powers.REFUSED_WHY[("POST", "/api/v1/federation/swarm/body")] == "not_jobs"
    for method, path in (("PUT", P + "reserve"), ("POST", "/api/v1/federation/swarm/body"), ("POST", "/api/v1/federation/swarm/proxy"),
                         ("POST", P + "board/anything"), ("POST", P + "sessions/create")):
        r = rig.client.request(method, path, json={}, headers=rig.head)
        assert r.status_code == 403 and _code(r) == "mesh_power_refused", (method, path, r.text)

    r = _post(rig, "look", {"project_uid": HOME_UID, "caller": "iid-elsewhere", "command": "rm -rf TOPSECRET_CMD", "env": {"K": "TOPSECRET_ENV"}})
    assert r.status_code in (400, 422), r.text
    r = _post(rig, "admit", {**_admit(ELSEWHERE_UID), "caller_install": B})
    assert r.status_code in (400, 422), r.text
    with structlog.testing.capture_logs() as logs:
        _post(rig, "look", {"project_uid": HOME_UID, "command": "rm -rf TOPSECRET_CMD", "env": {"K": "TOPSECRET_ENV"}})
    out = capsys.readouterr()
    assert "TOPSECRET" not in json.dumps(logs, default=str) + out.out + out.err

    held = rig.lst
    rig.lst = _edit(held, B, one_way=True)
    r = _post(rig, "admit", _admit(HOME_UID))
    assert r.status_code == 403 and _code(r) == "computer_one_way", r.text
    rig.lst = _edit(held, C, one_way=True)
    r = _post(rig, "admit", _admit(HOME_UID))
    assert r.status_code == 403 and _code(r) == "mesh_power_refused", r.text
    assert mesh_powers.MESH_JOBS not in asyncio.run(mesh_grants.current(B)).powers
    for gone in (held.model_copy(update={"computers": [c for c in held.computers if c.install_id != B]}), _edit(held, B, link_peers=False)):
        rig.lst = gone
        assert _post(rig, "admit", _admit(HOME_UID)).status_code == 401
    rig.lst = held
    assert _post(rig, "admit", _admit(HOME_UID)).status_code == 200

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    r = _post(rig, "look", {"project_uid": HOME_UID})
    assert r.status_code == 404, r.text
    assert _post(rig, "look", {"project_uid": HOME_UID}, head={"Authorization": "Bearer nonsense"}).status_code == 404


def test_an_open_jobs_power_keeps_the_receivers_own_limits(rig, monkeypatch, tmp_path):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: tmp_path, raising=True)
    ids = [paths.new_job_id() for _ in range(5)]
    try:
        for jid in ids[:4]:
            assert _post(rig, "admit", {"job_id": jid, "project_uid": HOME_UID, "kind": "suite"}).status_code == 200
        r = _post(rig, "admit", {"job_id": ids[4], "project_uid": HOME_UID, "kind": "suite"})
        assert r.status_code == 503 and _code(r) == "host_busy", r.text
        host_admit.drop(ids[0])
        assert _post(rig, "admit", {"job_id": ids[4], "project_uid": HOME_UID, "kind": "suite"}).status_code == 200
    finally:
        for jid in ids:
            host_admit.drop(jid)

    full = {**MARK, "restrictions": {"allowed_projects": ["SENTINEL_R"]}, "credential_offers": ["SENTINEL_O"], "members": ["SENTINEL_M"],
            "reserve": {"level": "in_use", "cpu_pct": 30, "mem_pct": 20, "config": {"rule": "SENTINEL_C"}}}
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: full)
    looked = _post(rig, "look", {"project_uid": HOME_UID})
    assert looked.status_code == 200 and "SENTINEL" not in looked.text and looked.json()["snapshot"]["reserve"] == {"level": "in_use", "cpu_pct": 30, "mem_pct": 20}
    assert _post(rig, "look", {"project_uid": UNHELD_UID}).json()["project"] == "project_not_here"
    rig.state["restrictions"] = restrictions_mod.Restrictions(allowed_projects=[HOME_UID])
    looked = _post(rig, "look", {"project_uid": UNHELD_UID})
    assert looked.json() == {"snapshot": None, "project": "pack_restricted"}, looked.text
    rig.state["restrictions"] = restrictions_mod.Restrictions()

    base = tmp_path / "base"
    plain = base / "plain"
    plain.mkdir(parents=True)
    from src.core import project_writes

    monkeypatch.setattr(project_writes, "_base_folders", lambda: [str(base)])
    with closing(connect(rig.path, create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, uid, pack_state) "
                     "VALUES (?, ?, 'plain', 'user', 'unchecked', 't', 't', 'uid-plain-001', 'home')", (str(plain), str(plain)))
        conn.commit()

    def register(uid: str, root: str):
        return rig.client.post(P + "replica", json={"project_uid": uid, "name": "n-" + uid, "root": root}, headers=rig.head)

    r = register("uid-new-00001", str(tmp_path / "outside"))
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    r = register("uid-new-00002", str(base / ".." / "outside"))
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    escape = str(base / ".." / "esc" / ".." / base.name / "y")
    r = register("uid-new-00009", escape)
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    assert not (base.parent / "esc").exists()
    r = register("uid-new-00003", str(plain))
    assert r.status_code == 409 and _code(r) == "project_root_in_use", r.text
    r = register("uid-new-00004", str(plain / "sub"))
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    rig.state["restrictions"] = restrictions_mod.Restrictions(allowed_projects=[HOME_UID])
    r = register("uid-new-00004", str(base / "ok"))
    assert r.status_code == 403 and _code(r) == "pack_restricted", r.text
    rig.state["restrictions"] = restrictions_mod.Restrictions()
    r = register("uid-new-00005", str(base / "ok"))
    assert r.status_code == 200 and r.json()["created"] is True, r.text

    inbox_dir = tmp_path / "pack" / "inbox"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "b-foreign00001.part").write_bytes(b"x")
    (inbox_dir / "b-foreign00001.peer").write_text("iid-other")
    import hashlib

    chunk = b"y"
    head = {**rig.head, "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest()}
    r = rig.client.put(P + "blobs/b-foreign00001?offset=1", content=chunk, headers=head)
    assert r.status_code == 403 and _code(r) == "blob_not_yours", r.text
    r = rig.client.post(P + "blobs/b-foreign00001/seal", json={"size": 1, "sha256": hashlib.sha256(b"x").hexdigest(), "kind": "bundle"}, headers=rig.head)
    assert r.status_code == 403 and _code(r) == "blob_not_yours", r.text
    assert rig.client.get(P + "blobs/b-foreign00001", headers=rig.head).status_code == 404
    assert rig.client.put(P + "blobs/b-mine0000001?offset=0", content=chunk, headers=head).status_code == 200


def test_production_opens_jobs_only_behind_the_switch(env, monkeypatch):  # noqa: F811
    head = _bearer(_mint(env))
    assert mesh_powers.MESH_JOBS in mesh_powers.OPEN_POWERS
    assert capabilities.CAP_JOBS_MESH in capabilities.names()
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert capabilities.CAP_JOBS_MESH not in capabilities.names()
    jobs_rows = [row for row, power in mesh_powers.ROUTES.items() if power == mesh_powers.MESH_JOBS]
    assert ("POST", P + "jobs/look") in jobs_rows and ("POST", "/api/v1/federation/swarm/body") not in jobs_rows
    for method, path in jobs_rows:
        r = env.client.request(method, path.replace("{blob_id}", "b1").replace("{install_id}", "i1").replace("{project_uid}", "uid-home-0001"), json={}, headers=head)
        assert r.status_code in (401, 404), (method, path, r.status_code)
    assert env.client.post(P + "jobs/look", content=b"{not json", headers=head).status_code == 404


@pytest.mark.parametrize("locked", [True, False])
def test_parallel_member_holds_never_pass_the_cap_of_four(monkeypatch, locked):
    import contextlib
    import threading
    import time

    from src.core.pack.jobs import member_view
    from src.core.pack.jobs.types import JobError

    monkeypatch.setattr(host_admit, "HOLDS", Holds())
    monkeypatch.setattr(host_admit.folders, "busy_count", lambda store, uid: 0)
    if not locked:
        monkeypatch.setattr(host_admit, "_MEMBER_LOCK", contextlib.nullcontext())
    real = host_admit.member_load
    gate = threading.Barrier(6)

    def counted(*a, **k):
        n = real(*a, **k)
        try:
            gate.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return n

    monkeypatch.setattr(host_admit, "member_load", counted)
    host = SimpleNamespace(store=SimpleNamespace(host_list=lambda states: [], slot_rows=lambda *a: []), _clock=time.time, _admit=lambda work: "")
    work = host_admit.Workload(est_cpu_cores=0.1, est_ram_gb=0.1)
    for i in range(3):
        host_admit.HOLDS.try_hold(f"old{i}", "M", 0.1, 0.1, 100.0, lambda c, r: True)
    results = []

    def go(i):
        try:
            host_admit._hold(host, f"j{i}", "M", "uid", work, 100.0, member=True)
            results.append(True)
        except JobError:
            results.append(False)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    new = results.count(True)
    if locked:
        assert new == member_view.MAX_JOBS_PER_MEMBER - 3
        assert len(host_admit.HOLDS.keys_of("M")) == member_view.MAX_JOBS_PER_MEMBER
    else:
        assert new > member_view.MAX_JOBS_PER_MEMBER - 3


def _hold_four(owner: str) -> None:
    for i in range(4):
        assert host_admit.HOLDS.try_hold(f"cap{i}", owner, 0.1, 0.1, 100.0, lambda c, r: True)


def test_the_member_cap_of_four_holds_on_start_and_on_prewarm(rig, monkeypatch):
    from src.api import federation_pack_prewarm_routes as prewarm_routes
    from src.core.pack.jobs import prewarm

    _hold_four(B)
    start = {"job_id": paths.new_job_id(), "project_uid": REPLICA_UID, "snapshot_commit": "a" * 40, "snapshot_blob_id": "b-0123456789ab", "kind": "suite", "command": "true", "caller_roots": ["/x"]}
    r = _post(rig, "start", start)
    assert r.status_code == 503 and _code(r) == "host_busy", r.text
    seen = {}

    async def spy(host, caller, body, member=False):
        seen["member"] = member
        return {"ok": False, "reason": "spy"}

    monkeypatch.setattr(prewarm_routes.prewarm_mod, "prewarm", spy)
    assert _post(rig, "prewarm", {"project_uid": REPLICA_UID, "commit": "a" * 40, "dep_dirs": [{"path": "web/node_modules", "kind": "npm"}]}).status_code == 200
    assert seen == {"member": True}
    body = prewarm.PrewarmBody(project_uid=REPLICA_UID, commit="a" * 40, dep_dirs=[{"path": "web/node_modules", "kind": "npm"}])
    deps = [prewarm.DepDir("web/node_modules", "npm", {}, None)]
    try:
        said = prewarm._refusal(rig.host, B, body, deps, member=True)
        assert said and "4 jobs" in said, said
        assert prewarm._refusal(rig.host, B, body, deps, member=False) is None
    finally:
        host_admit.drop(prewarm.marker(REPLICA_UID))
        for i in range(4):
            host_admit.drop(f"cap{i}")


def test_the_prewarm_route_answers_the_member_cap_end_to_end_and_starts_nothing(rig, monkeypatch):
    from src.core.pack.jobs import prewarm

    monkeypatch.setattr(prewarm, "_commit_here", lambda root, commit: True)
    _hold_four(B)
    try:
        r = _post(rig, "prewarm", {"project_uid": REPLICA_UID, "commit": "a" * 40, "dep_dirs": [{"path": "web/node_modules", "kind": "npm"}]})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["ok"] is False and "4 jobs" in out["reason"], out
        assert rig.host.store.host_get(prewarm.marker(REPLICA_UID)) is None
        assert host_admit.HOLDS.owner(prewarm.marker(REPLICA_UID)) is None
    finally:
        for i in range(4):
            host_admit.drop(f"cap{i}")


def test_a_members_restrictions_are_checked_on_bundle_apply(rig, monkeypatch, tmp_path):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: tmp_path, raising=True)
    body = {"blob_id": "b-0123456789ab", "project_uid": REPLICA_UID}
    rig.state["restrictions"] = restrictions_mod.Restrictions(allowed_projects=[HOME_UID])
    r = rig.client.post(P + "bundle/apply", json=body, headers=rig.head)
    assert r.status_code == 403 and _code(r) == "pack_restricted", r.text
    rig.state["restrictions"] = restrictions_mod.Restrictions()
    r = rig.client.post(P + "bundle/apply", json=body, headers=rig.head)
    assert r.status_code == 404 and _code(r) == "unknown_blob", r.text


def test_the_member_inbox_quota_leaves_room_for_the_star_link(rig, monkeypatch, tmp_path):
    import hashlib

    from src.config import settings
    from src.core.pack.transport import blobs

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: tmp_path, raising=True)
    monkeypatch.setattr(blobs, "MAX_BLOB_BYTES", 4)
    monkeypatch.setattr(blobs, "MAX_PEER_INBOX_BYTES", 8)
    monkeypatch.setattr(blobs, "MAX_TOTAL_INBOX_BYTES", 12)

    def put(blob: str, data: bytes):
        part = tmp_path / "pack" / "inbox" / (blob + ".part")
        off = part.stat().st_size if part.is_file() else 0
        return rig.client.put(P + f"blobs/{blob}?offset={off}", content=data, headers={**rig.head, "X-Chunk-Sha256": hashlib.sha256(data).hexdigest()})

    assert put("b-member00001", b"abcd").status_code == 200
    r = put("b-member00002", b"e")
    assert r.status_code == 507 and _code(r) == "inbox_quota_peer", r.text
    inbox_dir = tmp_path / "pack" / "inbox"
    for f in inbox_dir.glob("b-member0000*"):
        f.unlink()
    (inbox_dir / "b-foreign00001.part").write_bytes(b"x" * 6)
    (inbox_dir / "b-foreign00001.peer").write_text("iid-other")
    r = put("b-member00003", b"abc")
    assert r.status_code == 507 and _code(r) == "inbox_quota_total", r.text
    star = blobs.Inbox(inbox_dir)
    chunk = b"y" * 4
    assert star.put("b-star0000001", 0, chunk, hashlib.sha256(chunk).hexdigest(), "iid-star") == 4
    chunk = b"z" * 2
    assert star.put("b-star0000002", 0, chunk, hashlib.sha256(chunk).hexdigest(), "iid-star") == 2
    with pytest.raises(blobs.BlobError) as over:
        star.put("b-star0000002", 2, b"w", hashlib.sha256(b"w").hexdigest(), "iid-star")
    assert over.value.code == "inbox_quota_total"


def test_a_member_root_is_its_own_empty_folder_inside_the_projects_folder(rig, monkeypatch, tmp_path):
    import os
    import shutil
    import subprocess
    import unicodedata

    from src.config import settings
    from src.core import project_writes
    from src.core.pack.identity import replicas

    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setattr(project_writes, "_base_folders", lambda: [str(base)])
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self_: base, raising=True)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: tmp_path, raising=True)
    plain, nfc = base / "plain", base / unicodedata.normalize("NFC", "café")
    plain.mkdir()
    nfc.mkdir()
    (base / "link").symlink_to(plain)
    (base / "dang").symlink_to(base / "gone-target")
    (base / "team" / "proj").mkdir(parents=True)
    (base / "full").mkdir()
    (base / "full" / "a.txt").write_text("x")
    (base / "empty").mkdir()
    (base / "repo").mkdir()
    subprocess.run(["git", "init", "-q", str(base / "repo")], check=True)
    with closing(connect(rig.path, create=False)) as conn:
        for uid, name, root, archived in (("uid-plain-001", "plain", plain, None), ("uid-cafe-0001", "cafe", nfc, None),
                                           ("uid-proj-0001", "proj", base / "team" / "proj", "2026-01-01T00:00:00Z")):
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, uid, pack_state, archived_at) "
                         "VALUES (?, ?, ?, 'user', 'unchecked', 't', 't', ?, 'home', ?)", (str(root), str(root), name, uid, archived))
        conn.commit()
    seq = iter(range(1, 1000))

    def register(root, name=None, uid=None):
        n = next(seq)
        r = rig.client.post(P + "replica", json={"project_uid": uid or f"uid-m-{n:06d}", "name": name or f"copy{n}", "root": root}, headers=rig.head)
        assert r.status_code < 500, (root, name, r.status_code, r.text)
        return r

    upper_exists = os.path.exists(str(base / "PLAIN"))
    in_use = [str(plain) + "/", str(plain) + "/.", str(base / "x" / ".." / "plain"), str(base / "link")]
    if upper_exists:
        in_use.append(str(base / "PLAIN"))
    for root in in_use:
        r = register(root)
        assert r.status_code == 409 and _code(r) == "project_root_in_use", (root, r.status_code, r.text)
    if upper_exists:
        r = register(None, name="PLAIN")
        assert r.status_code == 409 and _code(r) == "project_root_in_use", r.text
    refused = [str(base / "link" / "sub"), str(base / "team"), str(base / "full"), str(base / "repo" / "sub"), str(base / "repo" / ".git" / "x"),
               str(base / "dang"), unicodedata.normalize("NFD", str(nfc)) + "/sub"]
    if upper_exists:
        refused.append(str(base / "PLAIN" / "sub"))
    for root in refused:
        r = register(root)
        assert r.status_code == 403 and _code(r) == "member_root_refused", (root, r.status_code, r.text)
    r = register(None, name="full")
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text

    r = register(str(base / "fresh"), uid="uid-fresh-001")
    assert r.status_code == 200 and r.json()["created"] is True, r.text
    assert register(str(base / "fresh"), uid="uid-fresh-001").status_code == 200
    assert register(None, name="brandnew").status_code == 200
    assert register(str(base / "empty")).status_code == 200
    with closing(connect(rig.path, create=False)) as conn:
        with pytest.raises(replicas.ReplicaRefused) as second:
            replicas.accept_replica(conn, home_install_id="iid-other", project_uid="uid-second-01", name="second", root=str(base / "fresh"), member_caller=True)
        assert second.value.status == 409
        star = replicas.accept_replica(conn, home_install_id=B, project_uid="uid-star-0001", name="plainstar", root=str(plain), member_caller=False)
        assert star["adopted"] is True

    assert register(str(base / "r2"), uid="uid-r2-000001").status_code == 200
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    apply = {"blob_id": "b-0123456789ab", "project_uid": "uid-r2-000001"}
    r = rig.client.post(P + "bundle/apply", json=apply, headers=rig.head)
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    shutil.rmtree(base / ".git")
    r = rig.client.post(P + "bundle/apply", json=apply, headers=rig.head)
    assert r.status_code == 404 and _code(r) == "unknown_blob", r.text
    (base / "deep" / "inner").mkdir(parents=True)
    (base / "link2").symlink_to(base / "deep" / "inner")
    with closing(connect(rig.path, create=False)) as conn:
        with pytest.raises(replicas.ReplicaRefused) as dots:
            replicas.accept_replica(conn, home_install_id="iid-other", project_uid="uid-dots-0001", name="dots", root=str(base / "link2" / ".." / "x"), member_caller=True)
        assert dots.value.status == 403 and dots.value.code == "member_root_refused"
        replicas.accept_replica(conn, home_install_id=B, project_uid="uid-r3-000001", name="n-r3", root=str(base / "link2" / ".." / "x"), member_caller=False)
    subprocess.run(["git", "init", "-q", str(base / "deep")], check=True)
    r = rig.client.post(P + "bundle/apply", json={"blob_id": "b-0123456789ab", "project_uid": "uid-r3-000001"}, headers=rig.head)
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
    shutil.rmtree(base / "deep" / ".git")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    r = register(str(base / "new"))
    assert r.status_code == 403 and _code(r) == "member_root_refused", r.text
