
from __future__ import annotations

import os
import stat
import time
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from fastapi.testclient import TestClient

from src.api import federation_routes, peer_auth
from src.api.auth import require_auth
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.federation import fed_key, grants, pair_sas, pairing, peer_sockets, peer_token
from src.core.federation.pairing import PairingOffers, plan_pairing
from src.core.relay_identity.device_key import b64url
from src.main import app

LOOPBACK = ("127.0.0.1", 50000)


class Mac:

    def __init__(self, root: Path, seed: int) -> None:
        ensure_db_migrated(root)
        self.root, self.path = root, db_path_for(root)
        self.key = fed_key.DeviceKey.from_seed(bytes([seed]) * 32)
        with closing(self.conn()) as c:
            self.install_id = get_meta(c, "install_id")

    def conn(self):
        return connect(self.path, create=False)


@pytest.fixture()
def macs(tmp_path, monkeypatch):
    acceptor, initiator = Mac(tmp_path / "a", 1), Mac(tmp_path / "b", 2)
    monkeypatch.setattr(peer_auth, "open_db", acceptor.conn)
    monkeypatch.setattr(federation_routes, "_local_key", lambda _iid: acceptor.key)
    monkeypatch.setattr(federation_routes, "_state_dir", lambda: acceptor.root)
    monkeypatch.setattr(pairing, "OFFERS", PairingOffers())
    monkeypatch.setattr(pair_sas, "ACCEPTING", pair_sas.PendingPairs())
    monkeypatch.setattr(federation_routes, "_TOKEN_GRANT_WINDOWS", pairing.KeyedWindows(60, 60.0))
    monkeypatch.setattr(federation_routes, "_TOKEN_STRANGER_WINDOWS", pairing.KeyedWindows(20, 60.0))
    yield acceptor, initiator
    app.dependency_overrides.pop(require_auth, None)


def _client(port=LOOPBACK) -> TestClient:
    return TestClient(app, raise_server_exceptions=False, client=port)


def _ssh_begin(acceptor: Mac) -> str:
    return pairing.OFFERS.begin(pairing.PROOF_SSH_FILE, acceptor.root).nonce


def _pair(acceptor: Mac, initiator: Mac, client: TestClient):
    nonce = _ssh_begin(acceptor)
    code = (acceptor.root / "federation" / f"pair-{nonce}").read_text().strip()
    with closing(initiator.conn()) as c:
        mine = grants.create_grant(c, peer_install_id=acceptor.install_id,
                                   public_key=fed_key.public_key_b64(acceptor.key), label="acceptor")
    done = client.post("/api/v1/federation/pair/complete", json={
        "nonce": nonce, "code": code, "install_id": initiator.install_id, "label": "initiator",
        "public_key": fed_key.public_key_b64(initiator.key), "grant_id": mine.grant_id, "protocol": 1})
    assert done.status_code == 200, done.text
    nonce_accept = client.post("/api/v1/federation/pair/finish", json={
        "nonce": nonce, "accept": True, "signature": initiator.key.sign(pair_sas.finish_message(nonce, True))})
    assert nonce_accept.json() == {"state": "active"}, nonce_accept.text
    return done.json(), mine


def _token(acceptor: Mac, initiator: Mac, client: TestClient, grant_id: str, *, ts=None, nonce=None):
    ts = int(time.time()) if ts is None else ts
    raw_nonce = os.urandom(16) if nonce is None else nonce
    sig = initiator.key.sign(peer_token.challenge_message(grant_id, acceptor.install_id, ts, raw_nonce))
    return client.post("/api/v1/federation/token", json={
        "grant_id": grant_id, "ts": ts, "nonce": b64url(raw_nonce), "signature": sig})


def test_pairing_creates_both_grants_and_the_token_reads_hello(macs):
    acceptor, initiator = macs
    client = _client()
    answer, mine = _pair(acceptor, initiator, client)
    with closing(acceptor.conn()) as c:
        theirs = grants.live_for_peer(c, initiator.install_id)
    assert theirs and theirs.grant_id == answer["grant_id"] and theirs.remote_grant_id == mine.grant_id
    assert theirs.fid == fed_key.fid_for(initiator.key.raw_pub)
    assert answer["public_key"] == fed_key.public_key_b64(acceptor.key) and answer["install_id"] == acceptor.install_id
    assert mine.peer_install_id == acceptor.install_id and mine.fid == answer["fid"]
    minted = _token(acceptor, initiator, client, answer["grant_id"])
    assert minted.status_code == 200
    hello = client.get("/api/v1/federation/hello", headers={"Authorization": f"Bearer {minted.json()['token']}"})
    assert hello.status_code == 200 and hello.json()["install_id"] == acceptor.install_id


def test_the_code_is_single_use_and_five_wrong_tries_burn_the_offer(macs):
    acceptor, initiator = macs
    client = _client()
    _pair(acceptor, initiator, client)
    begin = {"nonce": _ssh_begin(acceptor)}
    body = {"nonce": begin["nonce"], "code": "WRONGCODE", "install_id": "x", "public_key": "x", "grant_id": "g",
            "protocol": 1}
    code = (acceptor.root / "federation" / f"pair-{begin['nonce']}").read_text().strip()
    for _ in range(5):
        assert client.post("/api/v1/federation/pair/complete", json={**body, "public_key": fed_key.public_key_b64(
            initiator.key)}).status_code == 401
    good = {**body, "code": code, "public_key": fed_key.public_key_b64(initiator.key)}
    assert client.post("/api/v1/federation/pair/complete", json=good).status_code == 401


def test_begin_without_login_is_refused_on_http_even_from_loopback(macs):
    acceptor, _ = macs
    for client, headers in ((_client(("192.0.2.15", 4000)), {}), (_client(), {}),
                            (_client(), {"X-Forwarded-For": "8.8.8.8"})):
        refused = client.post("/api/v1/federation/pair/begin", headers=headers)
        assert refused.status_code == 401 and refused.json()["detail"]["code"] == "owner_login_required"
    nonce = _ssh_begin(acceptor)
    path = acceptor.root / "federation" / f"pair-{nonce}"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_an_owner_gets_the_typed_code_on_screen_and_begin_is_rate_limited(macs):
    app.dependency_overrides[require_auth] = lambda: True
    client = _client(("192.0.2.15", 4000))
    first = client.post("/api/v1/federation/pair/begin")
    assert first.json()["proof"] == "typed" and len(first.json()["code"]) == 8
    codes = [client.post("/api/v1/federation/pair/begin").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 429]


def test_one_outstanding_offer_new_begin_replaces_the_old_file(macs):
    acceptor, _ = macs
    a, b = _ssh_begin(acceptor), _ssh_begin(acceptor)
    files = {p.name for p in (acceptor.root / "federation").iterdir()}
    assert files == {f"pair-{b}"} and a != b


def test_an_expired_offer_is_refused_and_its_file_removed(tmp_path):
    now = [0.0]
    offers = PairingOffers(clock=lambda: now[0])
    offer = offers.begin(pairing.PROOF_SSH_FILE, tmp_path)
    code = offer.code
    now[0] += pairing.FILE_TTL_SECONDS + 1
    with pytest.raises(pairing.PairError):
        offers.redeem(offer.nonce, code)
    assert not list((tmp_path / "federation").iterdir())


def test_the_challenge_is_fresh_signed_and_single_use(macs):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    gid = answer["grant_id"]
    nonce = os.urandom(16)
    assert _token(acceptor, initiator, client, gid, nonce=nonce).status_code == 200
    assert _token(acceptor, initiator, client, gid, nonce=nonce).status_code == 401
    assert _token(acceptor, initiator, client, gid, ts=int(time.time()) - 3600).status_code == 401
    impostor = Mac(acceptor.root.parent / "c", 3)
    assert _token(acceptor, impostor, client, gid).status_code == 401
    assert _token(acceptor, initiator, client, "0" * 32).status_code == 401


def test_a_token_from_another_install_or_the_owner_secret_never_works(macs):
    import jwt

    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    with closing(acceptor.conn()) as c:
        grant = grants.get_live(c, answer["grant_id"])
    forged = jwt.encode({"typ": "peer", "sub": grant.grant_id, "iid": acceptor.install_id,
                         "exp": int(time.time()) + 600}, "testjwtnotreal", algorithm="HS256")
    wrong_iid, _ = peer_token.mint(grant, "some-other-install")
    for bad in (forged, wrong_iid):
        r = client.get("/api/v1/federation/hello", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401


def test_revoke_closes_that_peers_sockets_with_4412_and_refuses_its_token(macs):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    gid = answer["grant_id"]
    bearer = {"Authorization": f"Bearer {_token(acceptor, initiator, client, gid).json()['token']}"}

    class FakeSocket:
        def __init__(self):
            self.closed = None

        async def close(self, code, reason):
            self.closed = (code, reason)

    mine, other = FakeSocket(), FakeSocket()
    peer_sockets.register(gid, mine)
    peer_sockets.register("another-grant", other)
    assert client.delete(f"/api/v1/federation/grants/{gid}", headers=bearer).status_code == 401
    app.dependency_overrides[require_auth] = lambda: True
    done = client.delete(f"/api/v1/federation/grants/{gid}")
    assert done.status_code == 200 and done.json() == {"revoked": True, "sockets_closed": 1}
    assert mine.closed == (4412, "peer_revoked") and other.closed is None
    assert client.get("/api/v1/federation/hello", headers=bearer).status_code == 401
    assert client.delete(f"/api/v1/federation/grants/{gid}").status_code == 404
    peer_sockets.unregister("another-grant", other)


def test_unpair_with_a_peer_token_deletes_the_callers_grant_here(macs):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    with closing(acceptor.conn()) as c:
        bystander = grants.create_grant(c, peer_install_id="iid-bystander",
                                        public_key=fed_key.public_key_b64(fed_key.DeviceKey.from_seed(b"\x07" * 32)),
                                        label="b")
    bearer = {"Authorization": f"Bearer {_token(acceptor, initiator, client, answer['grant_id']).json()['token']}"}
    assert client.delete("/api/v1/federation/grants/self", headers=bearer).json() == {"unpaired": True}
    with closing(acceptor.conn()) as c:
        assert grants.get_grant(c, answer["grant_id"]) is None and grants.get_live(c, bystander.grant_id)


def test_the_grants_list_is_owner_only(macs):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    bearer = {"Authorization": f"Bearer {_token(acceptor, initiator, client, answer['grant_id']).json()['token']}"}
    assert client.get("/api/v1/federation/grants", headers=bearer).status_code == 401
    app.dependency_overrides[require_auth] = lambda: True
    rows = client.get("/api/v1/federation/grants").json()
    assert [r["grant_id"] for r in rows] == [answer["grant_id"]] and "public_key" not in rows[0]


def test_a_protocol_major_mismatch_is_refused_before_the_code_is_spent(macs):
    acceptor, initiator = macs
    client = _client()
    nonce = _ssh_begin(acceptor)
    r = client.post("/api/v1/federation/pair/complete", json={
        "nonce": nonce, "code": "X", "install_id": "i", "public_key": "k", "grant_id": "g", "protocol": 2})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "protocol_mismatch"
    assert pairing.OFFERS.outstanding()


def test_link_accepts_a_tcp_port_and_a_socket_only_inside_our_own_0700_dir(macs, tmp_path, monkeypatch):
    import socket

    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    gid = answer["grant_id"]
    bearer = {"Authorization": f"Bearer {_token(acceptor, initiator, client, gid).json()['token']}"}
    fed = Path("/tmp") / f"fedt{os.getpid()}"
    fed.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(federation_routes, "fed_dir", lambda: fed)
    proven, accepted = [True], []

    async def fake_prove(_route, _key, _iid, **_kw):
        return proven[0]

    class Links:
        async def accept_route(self, _grant, route):
            accepted.append(route)

    monkeypatch.setattr(federation_routes.peer_client, "prove_route", fake_prove)
    monkeypatch.setattr(federation_routes.peer_links, "LINKS", Links())
    good, elsewhere, plain = fed / f"in-{gid}-abc.sock", Path("/tmp") / f"in-{gid}-abc.sock", fed / f"in-{gid}-file.sock"
    plain.write_text("x")
    socks = []
    try:
        for path in (good, elsewhere):
            s = socket.socket(socket.AF_UNIX)
            s.bind(str(path))
            socks.append(s)
        assert client.post("/api/v1/federation/link", headers=bearer, json={"kind": "tcp", "port": 43000, "route_id": "r" * 32}).status_code == 200
        assert client.post("/api/v1/federation/link", headers=bearer,
                           json={"kind": "unix", "path": str(good)}).status_code == 200
        assert accepted[-1] == ("unix", str(good.resolve()), "")
        proven[0] = False
        refused = client.post("/api/v1/federation/link", headers=bearer, json={"kind": "tcp", "port": 43000, "route_id": "r" * 32})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "link_invalid"
        proven[0] = True
        for bad in (elsewhere, plain, fed / "missing.sock"):
            r = client.post("/api/v1/federation/link", headers=bearer, json={"kind": "unix", "path": str(bad)})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "link_invalid", bad
        os.chmod(fed, 0o770)
        assert client.post("/api/v1/federation/link", headers=bearer,
                           json={"kind": "unix", "path": str(good)}).status_code == 400
    finally:
        for s in socks:
            s.close()
        for p in (good, elsewhere, plain):
            p.unlink(missing_ok=True)
        os.chmod(fed, 0o700)
        fed.rmdir()


@pytest.mark.parametrize("pinned,fid,same_user,proof,route", [
    (True, False, True, "ssh_file", "unix"),
    (False, True, True, "ssh_file", "unix"),
    (False, False, True, "typed", "unix"),
    (True, True, False, "typed", "tcp"),
])
def test_f14_and_f17_decide_the_proof_and_the_back_route(pinned, fid, same_user, proof, route):
    plan = plan_pairing(host_key_pinned_before=pinned, fid_matches_pinned=fid, ssh_user_matches=same_user)
    assert (plan.proof, plan.back_route) == (proof, route)
