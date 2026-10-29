
from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import time
from contextlib import closing

import pytest

from tests.python.federation.test_pairing_routes import Mac, _client, _pair, _token, macs  # noqa: F401

# ruff: noqa: E402
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.api import federation_peer_routes, federation_routes
from src.api.auth import require_auth
from src.core.federation import grants, pair_driver, pairing, peer_hosts, peer_http, peer_links, peer_prove
from src.core.federation.peer_client import PeerClient, PeerRefused, PeerUnreachable, Route, prove_route
from src.core.federation.peer_link import PeerLink
from src.core.hosts.ssh_exec import SshDestination
from src.core.relay_identity.device_key import b64url, unb64url
from src.main import app

IID = "initiator-install-id"
PRIV = Ed25519PrivateKey.generate()
PUB = b64url(PRIV.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
TAG = "a1" * 16


async def _serve(port, name, seen, *, sign_route=TAG, big=False):
    async def handle(r, w):
        try:
            while True:
                head = (await r.readuntil(b"\r\n\r\n")).decode().split("\r\n")
                hdrs = {ln.split(":", 1)[0].lower(): ln.split(":", 1)[1].strip() for ln in head[1:] if ":" in ln}
                body = await r.readexactly(int(hdrs.get("content-length", "0")))
                path = head[0].split()[1]
                seen.append((name, path, hdrs.get("authorization")))
                if big:
                    w.write(b"HTTP/1.1 200 OK\r\ncontent-length: 67108864\r\n\r\n" + b"x" * 200000)
                    await w.drain()
                    return
                if path.endswith("/prove") and name == "real":
                    nonce = unb64url(json.loads(body)["nonce"], 16)
                    out = {"install_id": IID, "signature": b64url(PRIV.sign(peer_prove.prove_message(nonce, IID, sign_route)))}
                elif path.endswith("/token"):
                    out = {"token": "PEER-TOKEN", "expires_in": 900, "install_id": IID}
                else:
                    out = {"install_id": IID, "protocol": 1}
                data = json.dumps(out).encode()
                w.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: %d\r\n\r\n" % len(data) + data)
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()
    return await asyncio.start_server(handle, "127.0.0.1", port, reuse_address=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _client_for(port, tag=TAG) -> PeerClient:
    return PeerClient(Route("tcp", port, tag), grant_id="g", peer_install_id=IID, sign=lambda m: "sig", peer_public_key=PUB)


@pytest.mark.asyncio
async def test_h1_a_squatter_on_the_freed_port_never_sees_the_bearer():
    seen, port = [], _free_port()
    real = await _serve(port, "real", seen)
    client = _client_for(port)
    assert (await client.request("GET", "/federation/hello")).status_code == 200
    real.close()
    await real.wait_closed()
    evil = await _serve(port, "attacker", seen)
    try:
        await client.request("GET", "/federation/hello")
    except (PeerRefused, PeerUnreachable):
        pass
    evil.close()
    await evil.wait_closed()
    assert [row for row in seen if row[0] == "real" and row[2]], "population check: the real peer did get the bearer"
    assert [row for row in seen if row[0] == "attacker"], "population check: the squatter was contacted"
    assert [row for row in seen if row[0] == "attacker" and row[2]] == []
    assert [row[1].rsplit("/", 1)[-1] for row in seen if row[0] == "attacker"] == ["prove"]


@pytest.mark.asyncio
async def test_h1_a_proof_relayed_from_another_route_does_not_verify():
    seen, port = [], _free_port()
    server = await _serve(port, "real", seen, sign_route="b2" * 16)
    try:
        with pytest.raises(PeerRefused):
            await _client_for(port).request("GET", "/federation/hello")
    finally:
        server.close()
        await server.wait_closed()
    assert all(row[2] is None for row in seen)


@pytest.mark.asyncio
async def test_m4_an_endless_body_fails_closed_without_being_held():
    seen, port = [], _free_port()
    server = await _serve(port, "real", seen, big=True)
    try:
        with pytest.raises(PeerUnreachable) as caught:
            await _client_for(port).public("GET", "/federation/hello")
        assert caught.value.hard and peer_http.MAX_BODY == 64 * 1024
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_m3_a_rate_limited_prove_is_unreachable_never_identity_changed():
    async def handle(r, w):
        await r.readuntil(b"\r\n\r\n")
        w.write(b"HTTP/1.1 429 Too Many\r\ncontent-length: 2\r\n\r\n{}")
        await w.drain()
        w.close()
    port = _free_port()
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    try:
        with pytest.raises(PeerUnreachable):
            await prove_route(Route("tcp", port, TAG), PUB, IID)
    finally:
        server.close()
        await server.wait_closed()


def test_m3_strangers_share_a_small_bucket_a_real_grant_has_its_own(macs, monkeypatch):
    acceptor, initiator = macs
    monkeypatch.setattr(federation_routes, "_PROVE_STRANGER_WINDOWS", pairing.KeyedWindows(3, 60.0))
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    nonce = {"nonce": b64url(os.urandom(16))}
    codes = [client.post("/api/v1/federation/prove", json=nonce).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert client.post("/api/v1/federation/prove", json={**nonce, "grant_id": answer["grant_id"]}).status_code == 200
    stale = client.post("/api/v1/federation/prove", json={**nonce, "grant_id": answer["grant_id"], "route": "x" * 16})
    assert stale.status_code == 404


def test_m1_the_caller_cannot_claim_a_fid_match_and_the_answer_must_carry_the_observed_fid(macs):
    assert "fid_matches_pinned" not in federation_peer_routes.PairRequest.model_fields

    class Discovery:
        def discovered(self):
            return [{"name": "hosta", "fid": "FID1", "state": "pinned"}, {"name": "evil", "fid": "FID2", "state": "new"}]

    class Req:
        class app:  # noqa: N801
            class state:  # noqa: N801
                federation_discovery = Discovery()

    assert federation_peer_routes._pinned_fid(Req, "hosta") == "FID1"
    assert federation_peer_routes._pinned_fid(Req, "evil") == "" and federation_peer_routes._pinned_fid(Req, None) == ""
    acceptor, initiator = macs
    answer = {"install_id": acceptor.install_id, "public_key": pair_driver.fed_key.public_key_b64(acceptor.key),
              "fid": pair_driver.fed_key.fid_for(acceptor.key.raw_pub), "grant_id": "g", "label": "a", "protocol": 1}
    with pytest.raises(pair_driver.PairingFailed):
        pair_driver._check_answer(answer, "FID1")
    assert pair_driver._check_answer(answer, answer["fid"]) == acceptor.key.raw_pub
    with pytest.raises(pair_driver.PairingFailed):
        pair_driver._check_answer({**answer, "fid": "FID9"}, "")


@pytest.mark.asyncio
async def test_l1_pinned_is_decided_from_what_ssh_resolves(monkeypatch):
    calls = []

    async def fake(*argv):
        calls.append(argv)
        if argv[1] == "-G":
            return "hostname 198.51.100.14\nport 2201\nuserknownhostsfile ~/.ssh/kh_other\nglobalknownhostsfile /etc/ssh/ssh_known_hosts\n"
        return "found" if argv[2] == "[198.51.100.14]:2201" and argv[4].endswith("kh_other") else None

    monkeypatch.setattr(pair_driver, "_run_out", fake)
    assert await pair_driver.host_key_pinned(SshDestination("hosta")) is True
    asked = [c for c in calls if c[1] == "-F"]
    assert asked[0][2] == "[198.51.100.14]:2201"
    monkeypatch.setattr(pair_driver, "_run_out", lambda *a: asyncio.sleep(0, None))
    assert await pair_driver.host_key_pinned(SshDestination("hosta")) is False


def test_l2_a_prefix_collision_never_overwrites_another_peers_row(macs):
    acceptor, _ = macs
    with closing(acceptor.conn()) as c:
        a = peer_hosts.upsert(c, install_id="AAAAAAAAAAAA-one", label="one", grant_id="g1", fid="f1", initiator=True)
        b = peer_hosts.upsert(c, install_id="AAAAAAAAAAAA-two", label="two", grant_id="g2", fid="f2", initiator=True)
        assert a.key != b.key and len(peer_hosts.list_peers(c)) == 2
        assert peer_hosts.get(c, "AAAAAAAAAAAA-one").peer_grant_id == "g1"


def test_l2_the_initiator_never_replaces_a_live_grant_held_by_another_key(macs):
    acceptor, initiator = macs
    with closing(initiator.conn()) as c:
        grants.create_grant(c, peer_install_id=acceptor.install_id,
                            public_key=pair_driver.fed_key.public_key_b64(acceptor.key), label="real")
    other = Mac(initiator.root.parent / "c", 9)
    answer = {"install_id": acceptor.install_id, "public_key": pair_driver.fed_key.public_key_b64(other.key),
              "fid": pair_driver.fed_key.fid_for(other.key.raw_pub), "grant_id": "g", "label": "x", "protocol": 1}
    with pytest.raises(pair_driver.PairingFailed) as caught:
        pair_driver._persist(initiator.conn, our_grant_id="mine", answer=answer, dest=SshDestination("t"),
                             remote_port=8000, back_kind="unix")
    assert caught.value.code == "peer_identity_changed"
    with closing(initiator.conn()) as c:
        assert grants.live_for_peer(c, acceptor.install_id).label == "real"


def test_l3_an_owner_revoke_removes_the_peers_link(macs, monkeypatch):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    removed = []

    class Links:
        async def remove(self, peer):
            removed.append(peer)

    monkeypatch.setattr(federation_routes.peer_links, "LINKS", Links())
    app.dependency_overrides[require_auth] = lambda: True
    assert client.delete(f"/api/v1/federation/grants/{answer['grant_id']}").status_code == 200
    assert removed == [initiator.install_id]


@pytest.mark.asyncio
async def test_l3_an_initiator_with_no_live_grant_does_not_start(macs):
    acceptor, initiator = macs
    with closing(initiator.conn()) as c:
        row = peer_hosts.upsert(c, install_id="gone-peer", label="g", grant_id="g", fid="f", initiator=True,
                                ssh_target="hosta")
    links = peer_links.PeerLinks(open_db=initiator.conn, listener_path="/tmp/x.sock")
    links.use_key(initiator.key)
    await links.start_initiator(row)
    assert "gone-peer" not in links._links


def test_l4_the_grant_recheck_runs_even_while_the_peer_keeps_talking(macs, monkeypatch):
    acceptor, initiator = macs
    monkeypatch.setattr(federation_routes, "WS_RECHECK_SECONDS", 0.3)
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    bearer = {"Authorization": f"Bearer {_token(acceptor, initiator, client, answer['grant_id']).json()['token']}"}
    closed = None
    with client.websocket_connect("/api/v1/federation/ws", headers=bearer) as ws:
        assert ws.receive_json() == {"hello": True}
        with closing(acceptor.conn()) as c:
            grants.revoke(c, answer["grant_id"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and closed is None:
            try:
                ws.send_text("x")
                msg = ws.receive()
                if msg["type"] == "websocket.close":
                    closed = msg["code"]
            except Exception:  # noqa: BLE001
                break
            time.sleep(0.05)
    assert closed == 4412


@pytest.mark.asyncio
async def test_l5_an_acceptor_with_no_route_idles_and_a_new_route_moves_the_link(macs):
    acceptor, initiator = macs
    calls = []

    async def establish():
        calls.append(1)
        return Route("unix", "/x")

    async def wait_never():
        await asyncio.Event().wait()

    link = PeerLink(peer_install_id="i", establish=establish, make_client=lambda r: None, delay=lambda _a: 0.01,
                    settle=wait_never)
    link.start()
    await asyncio.sleep(0.2)
    await link.stop()
    assert calls == []
    with closing(acceptor.conn()) as c:
        grant = grants.create_grant(c, peer_install_id=initiator.install_id,
                                    public_key=pair_driver.fed_key.public_key_b64(initiator.key), label="i",
                                    remote_grant_id="theirs")
    links = peer_links.PeerLinks(open_db=acceptor.conn, listener_path="/tmp/x.sock")
    links.use_key(acceptor.key)
    await links.accept_route(grant, ("tcp", 1, "a" * 16))
    await asyncio.sleep(0.2)
    first = links._links[grant.peer_install_id]
    await links.accept_route(grant, ("tcp", 2, "b" * 16))
    assert links._links[grant.peer_install_id] is first and links._back[grant.peer_install_id][1] in (2, None)
    await links.shutdown()
