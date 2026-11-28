
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import closing
from types import SimpleNamespace
from typing import List, Optional, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mesh_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mesh_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import structlog  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_mesh_routes, peer_auth  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.argent import pair_sync  # noqa: E402
from src.core.computers import mesh  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants, mesh_grants, mesh_powers, peer_forward, peer_links, peer_token  # noqa: E402
from src.core.pack.machines import capabilities, runtime as pack_runtime  # noqa: E402
from src.core.relay_identity.device_key import b64url  # noqa: E402
from src.main import app  # noqa: E402
from src.plugins.host.peer_refusal import PEER_FORBIDDEN_CODE  # noqa: E402
from tests.python.computers.test_mesh_links import A, B, C, _v2  # noqa: E402
from tests.python.federation.test_federation_route_inventory import PEER_ALLOWED, _fill, _peer_scopes, _routes  # noqa: E402
from tests.python.pack import test_settings_signing as ss  # noqa: E402
from tests.test_route_auth_inventory import _dep_calls, _walk  # noqa: E402

HELLO = "/api/v1/federation/hello"
TOKEN = "/api/v1/federation/mesh/token"
REFUSED_CODE = "mesh_power_refused"


class Tagged:

    def __init__(self, inner, state) -> None:
        self.inner, self.state = inner, state

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and self.state.tag:
            scope = dict(scope, mesh_peer=self.state.tag)
        await self.inner(scope, receive, send)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    with closing(connect(path, create=False)) as conn:
        conn.execute("INSERT INTO project_replicas (project_uid, install_id, created_at, updated_at) VALUES ('p', ?, 't', 't')", (B,))
        conn.commit()
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    monkeypatch.setattr(peer_auth, "read_install_id", lambda conn: C)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(federation_mesh_routes, "_WINDOWS", federation_mesh_routes.pairing.KeyedWindows(60, 60.0))
    lst, _ = _v2()
    st = SimpleNamespace(lst=lst, sha=lst.entry(B).shas()[0], tag=B, path=path)
    stub = SimpleNamespace(trusted_pin=lambda peer: (st.lst, st.sha) if peer == B else None, snapshot=lambda: None)
    monkeypatch.setattr(mesh, "_ACTIVE", stub)
    st.client = TestClient(Tagged(app, st), raise_server_exceptions=False)
    return st


def _edit(lst, iid, **changes):
    return lst.model_copy(update={"computers": [c.model_copy(update=changes) if c.install_id == iid else c for c in lst.computers]})


def _signed(env, *, sha: Optional[str] = None, key: str = "b") -> dict:
    gid = mesh_grants.grant_id_for(C, B, ss.PUB[B], sha or env.sha)
    raw_nonce, ts = os.urandom(16), int(time.time())
    return {"ts": ts, "nonce": b64url(raw_nonce), "signature": ss.KEYS[key].sign(peer_token.challenge_message(gid, C, ts, raw_nonce, prefix=peer_token.MESH_CHALLENGE_PREFIX))}


def _mint(env, **kw):
    return env.client.post(TOKEN, json=_signed(env, **kw))


def _bearer(response) -> dict:
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def _guarded() -> List[Tuple[str, str, object]]:
    return [(m, p, r) for m, p, r in _routes() if any(c is require_auth or hasattr(c, "peer_scope") for c in _dep_calls(r.dependant))]


def _code(response) -> Optional[str]:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail.get("code") if isinstance(detail, dict) else None


def _sweep(env, head: dict, skip=()) -> List[Tuple[str, str, int, Optional[str]]]:
    out = []
    for method, path, _route in _guarded():
        if (method, path) in skip or path.startswith(("/api/v1/federation/pair/", "/api/v1/federation/token", TOKEN)):
            continue
        r = env.client.request(method, _fill(path), headers=head)
        out.append((method, path, r.status_code, _code(r)))
    return out


def _peer_rows() -> List[Tuple[str, str]]:
    return [(m, p) for m, p, r in _routes() if _peer_scopes(r)]


JOBS_OK_STATUS = {200, 400, 403, 404, 409, 422}
JOBS_OK_403 = {"not_a_counterpart", "blob_not_yours", "pack_restricted", "peer_token_required", "member_root_refused"}
JOBS_ROWS_SEEN: dict = {
    ("DELETE", "/api/v1/federation/pack/replica/{project_uid}"): 200,
    ("GET", "/api/v1/federation/pack/blobs/{blob_id}"): 400,
    ("GET", "/api/v1/federation/pack/jobs/activity"): 200,
    ("GET", "/api/v1/federation/pack/jobs/install/{install_id}"): 400,
    ("POST", "/api/v1/federation/pack/blobs/{blob_id}/seal"): 400,
    ("POST", "/api/v1/federation/pack/bundle/apply"): 400,
    ("POST", "/api/v1/federation/pack/jobs/admit"): 400,
    ("POST", "/api/v1/federation/pack/jobs/collect"): 400,
    ("POST", "/api/v1/federation/pack/jobs/forget-copy"): 400,
    ("POST", "/api/v1/federation/pack/jobs/install"): 400,
    ("POST", "/api/v1/federation/pack/jobs/look"): 422,
    ("POST", "/api/v1/federation/pack/jobs/prewarm"): 400,
    ("POST", "/api/v1/federation/pack/jobs/release"): 400,
    ("POST", "/api/v1/federation/pack/jobs/reply"): 400,
    ("POST", "/api/v1/federation/pack/jobs/start"): 400,
    ("POST", "/api/v1/federation/pack/jobs/status"): 400,
    ("POST", "/api/v1/federation/pack/jobs/stop"): 400,
    ("POST", "/api/v1/federation/pack/replica"): 400,
    ("PUT", "/api/v1/federation/pack/blobs/{blob_id}"): 400,
}


def _install_jobs_host(env, monkeypatch, tmp_path) -> None:
    from src.config import settings
    from src.core.pack.jobs import host_admit
    from src.core.pack.jobs.host import Host
    from src.core.pack.machines import config_state, restrictions as restrictions_mod
    from src.core.pack.reserve.holds import Holds

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: tmp_path, raising=True)
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    host = Host(state_dir=tmp_path, jobs_root=jobs, install_id=C, open_db=lambda: connect(env.path, create=False), admit=lambda _w: None,
                restrictions=lambda: restrictions_mod.Restrictions(), live_agents=lambda: 0)
    monkeypatch.setattr(app.state, "pack_jobs_host", host, raising=False)
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=lambda: restrictions_mod.Restrictions()))
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: {"can": {"marker": "own-snapshot"}, "pressure": {"pegged": False}})
    monkeypatch.setattr(host_admit, "HOLDS", Holds())


DATA_ROWS_SEEN: dict = {("POST", "/api/v1/federation/pack/mesh/sync"): (503, "meshdata_unavailable"),
                        ("GET", "/api/v1/federation/pack/rollup"): (503, "stats_unavailable")}


def _data_row(seen: dict, method: str, path: str, status: int, code: Optional[str]) -> None:
    assert code != REFUSED_CODE, (method, path, status, code)
    assert status < 500 or (status, code) in ((503, "meshdata_unavailable"), (503, "stats_unavailable")), (method, path, status, code)
    seen[(method, path)] = (status, code)


def _jobs_row(seen: dict, method: str, path: str, status: int, code: Optional[str]) -> None:
    assert status in JOBS_OK_STATUS, (method, path, status, code)
    assert code != REFUSED_CODE, (method, path, status, code)
    if status == 403:
        assert code in JOBS_OK_403, (method, path, code)
    seen[(method, path)] = status


def test_the_member_gate_over_the_real_app(env, monkeypatch, capsys, tmp_path):
    head = _bearer(_mint(env))
    hello = env.client.get(HELLO, headers=head)
    assert hello.status_code == 200 and hello.json()["principal"] == "peer" and hello.json()["restrictions_for_caller"] == []

    sockets = {("WS", p) for kind, p, r, _ in _walk(app.routes) if kind != "http" and _peer_scopes(r)}
    assert set(_peer_rows()) | sockets == set(mesh_powers.ROUTES)

    monkeypatch.setattr(pair_sync, "PAIR", None)
    _install_jobs_host(env, monkeypatch, tmp_path)
    jobs_seen: dict = {}
    data_seen: dict = {}
    request_row = ("POST", "/api/v1/federation/argent/credential/request")
    results = _sweep(env, head, skip={("GET", "/api/v1/federation/hello")})
    assert len(results) >= 100
    for method, path, status, code in results:
        if (method, path) == request_row:
            assert (status, code) == (503, "pair_not_ready"), (method, path, status, code)
            continue
        if mesh_powers.ROUTES.get((method, path)) in (mesh_powers.MESH_JOBS, mesh_powers.MESH_DATA):
            if mesh_powers.ROUTES.get((method, path)) == mesh_powers.MESH_JOBS:
                _jobs_row(jobs_seen, method, path, status, code)
            else:
                _data_row(data_seen, method, path, status, code)
            continue
        assert status in (401, 403), (method, path, status)
        if status == 403:
            assert code in (REFUSED_CODE, PEER_FORBIDDEN_CODE) or (mesh_powers.ROUTES.get((method, path)) == mesh_powers.MESH_LOGINS and code == "pack_restricted"), (method, path, code)
    for method, path in _peer_rows():
        if (method, path) != ("GET", "/api/v1/federation/hello"):
            r = env.client.request(method, _fill(path), headers=head)
            if (method, path) == request_row:
                assert r.status_code == 503 and _code(r) == "pair_not_ready", (method, path, r.status_code)
                continue
            if mesh_powers.ROUTES.get((method, path)) in (mesh_powers.MESH_JOBS, mesh_powers.MESH_DATA):
                if mesh_powers.ROUTES.get((method, path)) == mesh_powers.MESH_JOBS:
                    _jobs_row(jobs_seen, method, path, r.status_code, _code(r))
                else:
                    _data_row(data_seen, method, path, r.status_code, _code(r))
                continue
            if mesh_powers.ROUTES.get((method, path)) == mesh_powers.MESH_LOGINS:
                assert r.status_code == 403 and _code(r) == "pack_restricted", (method, path, r.status_code)
                continue
            assert r.status_code == 403 and _code(r) == REFUSED_CODE, (method, path, r.status_code)

    assert data_seen == DATA_ROWS_SEEN, data_seen
    assert jobs_seen == JOBS_ROWS_SEEN, jobs_seen

    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", mesh_powers.ALL_POWERS)
    refused = [row for row, power in mesh_powers.ROUTES.items() if power == mesh_powers.REFUSED and row[0] != "WS"]
    assert refused
    for method, path in refused:
        r = env.client.request(method, _fill(path), headers=head)
        assert r.status_code == 403 and _code(r) == REFUSED_CODE, (method, path, r.status_code)
    for star in (("PUT", "/api/v1/federation/pack/reserve"), ("POST", "/api/v1/federation/pack/skills/apply"),
                 ("POST", "/api/v1/federation/pack/global/apply")):
        assert star in mesh_powers.ROUTES and mesh_powers.ROUTES[star] == mesh_powers.REFUSED, star
    sync = "/api/v1/federation/pack/mesh/sync"
    assert mesh_powers.power_for("POST", sync) == mesh_powers.MESH_DATA and mesh_powers.OPEN_POWERS >= {mesh_powers.MESH_DATA}
    for method, path in (("POST", "pack/exchange"), ("PUT", "pack/labels"), ("POST", "pack/rescan"), ("GET", "stats/feed/local")):
        full = "/api/v1/federation/" + path if path.startswith("pack/") else "/api/v1/" + path
        assert mesh_powers.power_for(method, full) is None, (method, path)
    assert mesh_powers.power_for("GET", "/api/v1/federation/pack/rollup") == mesh_powers.MESH_DATA
    outside = _sweep(env, head, skip=set(mesh_powers.ROUTES))
    assert outside and all(status in (401, 403) for _, _, status, _ in outside)
    for (method, path), power in mesh_powers.ROUTES.items():
        if power in (mesh_powers.REFUSED, mesh_powers.MESH_LOGINS):
            continue
        ws = method == "WS"
        conn = SimpleNamespace(scope={"mesh_peer": B, "type": "websocket" if ws else "http", "method": method}, url=SimpleNamespace(path=_fill(path)))
        scope = "sessions" if ws else PEER_ALLOWED[(method, path)]
        import asyncio
        principal = asyncio.run(peer_auth._authorize_peer(head["Authorization"][7:], scope, conn=conn))
        assert principal.is_peer and principal.grant.scopes == () and not principal.grant.allows("machine"), (method, path)

    compiled = mesh_powers._COMPILED
    monkeypatch.setattr(mesh_powers, "_COMPILED", tuple(x for x in compiled if x[2] != ("GET", HELLO)))
    r = env.client.get(HELLO, headers=head)
    assert r.status_code == 403 and _code(r) == REFUSED_CODE
    monkeypatch.setattr(mesh_powers, "_COMPILED", compiled)
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset({mesh_powers.MESH_LINK}))

    calls: list = []
    spy = SimpleNamespace(client=lambda *a, **k: calls.append("client"), transport=lambda *a, **k: calls.append("transport"),
                          capabilities=lambda *a, **k: calls.append("caps"))
    monkeypatch.setattr(peer_links, "LINKS", spy)
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", mesh_powers.ALL_POWERS)
    r = env.client.get("/api/v1/sessions?session_id=remote:peer-x:abc", headers=head)
    assert r.status_code in (401, 409) and calls == []
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset({mesh_powers.MESH_LINK}))

    env.tag = None
    assert env.client.post(TOKEN, json=_signed(env)).status_code == 401
    assert env.client.get(HELLO, headers=head).status_code == 401
    forged = {**head, "mesh_peer": B, "x-mesh-peer": B}
    assert env.client.get(HELLO, headers=forged).status_code == 401
    assert env.client.post(TOKEN, json={**_signed(env), "install_id": B}, headers={"x-mesh-peer": B}).status_code == 401
    env.tag = "iid-d"
    assert env.client.get(HELLO, headers=head).status_code == 401
    assert env.client.post(TOKEN, json=_signed(env)).status_code == 401
    env.tag = B

    with closing(connect(env.path, create=False)) as conn:
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        star_grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer", scopes=("sessions", "machine"))
    star = {"Authorization": "Bearer " + peer_token.mint(star_grant, C)[0]}
    assert env.client.get(HELLO, headers=star).status_code == 401
    env.tag = None
    assert env.client.get(HELLO, headers=star).status_code == 200
    env.tag = B

    held = env.lst
    env.lst = _edit(held, B, one_way=True)
    assert env.client.get(HELLO, headers=head).json()["restrictions_for_caller"] == ["one_way"]
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", mesh_powers.ALL_POWERS)
    r = env.client.get("/api/v1/sessions/list", headers=head)
    assert r.status_code == 403 and _code(r) == "computer_one_way"
    monkeypatch.setattr(mesh_powers, "OPEN_POWERS", frozenset({mesh_powers.MESH_LINK}))

    for gone in (env.lst.model_copy(update={"computers": [c for c in held.computers if c.install_id != B]}),
                 _edit(held, B, link_peers=False), _edit(held, C, link_peers=False)):
        env.lst = gone
        assert env.client.get(HELLO, headers=head).status_code == 401
    env.lst = held
    assert env.client.get(HELLO, headers=head).status_code == 200

    rotated, _ = _v2()
    assert rotated.entry(B).shas() != held.entry(B).shas() and rotated.entry(B).fed_public_key == held.entry(B).fed_public_key
    env.lst, env.sha = rotated, rotated.entry(B).shas()[0]
    assert env.client.get(HELLO, headers=head).status_code == 401
    assert env.client.get(HELLO, headers=_bearer(_mint(env))).status_code == 200
    env.lst, env.sha = held, held.entry(B).shas()[0]

    body = _signed(env)
    with structlog.testing.capture_logs() as logs:
        minted = env.client.post(TOKEN, json=body)
        env.client.get(HELLO, headers={"Authorization": "Bearer " + minted.json()["token"] + "x"})
        env.client.post(TOKEN, json={**body, "signature": body["signature"]})
    captured = capsys.readouterr()
    seen = json.dumps(logs, default=str) + captured.out + captured.err
    assert minted.json()["token"] not in seen and body["signature"] not in seen and body["nonce"] not in seen

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    off = env.client.post(TOKEN, content=b"{not json", headers={"content-type": "application/json"})
    assert off.status_code == 404 and off.json() == {"detail": "Not Found"}
    assert env.client.get(HELLO, headers=head).status_code == 401


def test_the_reserve_is_the_alphas_and_tighten_never_echoes_text(env, monkeypatch):
    with closing(connect(env.path, create=False)) as conn:
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer", scopes=("sessions", "machine"))
    head = {"Authorization": "Bearer " + peer_token.mint(grant, C)[0]}
    env.tag = None

    def boom(patch, from_peer=False):
        raise ValueError("/Users/demo/secret/path/restrictions.json is bad")

    alpha = {"who": "iid-a"}
    runtime = SimpleNamespace(content_alpha=lambda: alpha["who"], set_reserve=lambda patch: SimpleNamespace(model_dump=lambda: {"ok": True}),
                              set_restrictions=boom)
    monkeypatch.setattr(pack_runtime, "wiring", lambda: SimpleNamespace(runtime=runtime, sync_scopes=lambda: None))
    r = env.client.put("/api/v1/federation/pack/reserve", json={"patch": {}}, headers=head)
    assert r.status_code == 403 and _code(r) == "pack_reserve_alpha_only"
    alpha["who"] = None
    assert env.client.put("/api/v1/federation/pack/reserve", json={"patch": {}}, headers=head).status_code == 403
    alpha["who"] = "iid-peer"
    assert env.client.put("/api/v1/federation/pack/reserve", json={"patch": {}}, headers=head).status_code == 200
    alpha["who"] = "iid-a"
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert env.client.put("/api/v1/federation/pack/reserve", json={"patch": {}}, headers=head).status_code == 200
    for on in (True, False):
        monkeypatch.setattr(capabilities, "MESH_BUILD_ON", on)
        r = env.client.put("/api/v1/federation/pack/restrictions/tighten", json={"patch": {}}, headers=head)
        assert r.status_code == 422 and _code(r) == "restrictions_invalid" and "secret" not in r.text and "/Users" not in r.text


DATA_ROW_WITH_STORE: Tuple[int, Optional[str]] = (422, "mesh_sync_body")


def test_the_mesh_sync_row_runs_its_handler_with_a_record_store_running(env, monkeypatch, tmp_path):
    from src.core.pack.meshdata import gossip  # noqa: PLC0415
    from src.core.pack.meshdata.store import RecordStore  # noqa: PLC0415

    head = _bearer(_mint(env))
    monkeypatch.setattr(gossip, "ACTIVE", SimpleNamespace(store=RecordStore(tmp_path / "records.db", C)))
    response = env.client.post("/api/v1/federation/pack/mesh/sync", json={}, headers=head)
    seen = (response.status_code, _code(response))
    assert response.status_code < 500 and _code(response) != REFUSED_CODE, seen
    assert seen == DATA_ROW_WITH_STORE and (("POST", "/api/v1/federation/pack/mesh/sync") in DATA_ROWS_SEEN)
