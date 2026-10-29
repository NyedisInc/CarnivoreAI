
from __future__ import annotations

import os
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

from tests.python.federation.test_pairing_routes import LOOPBACK, Mac, _client, _pair, _token, macs  # noqa: F401

# ruff: noqa: E402
from src.api import federation_routes
from src.api.auth import require_auth
from src.core import relay_keychain
from src.core.federation import fed_key, grants, key_rotate, pair_sas, pairing
from src.core.federation.pairing import PairingOffers
from src.core.relay_identity.device_key import b64url
from src.main import app



def test_an_anonymous_begin_cannot_replace_or_starve_the_owners_typed_offer(tmp_path):
    offers = PairingOffers(clock=lambda: 0.0)
    typed = offers.begin(pairing.PROOF_TYPED, tmp_path)
    ssh = offers.begin(pairing.PROOF_SSH_FILE, tmp_path)
    for _ in range(4):
        try:
            offers.begin(pairing.PROOF_SSH_FILE, tmp_path)
        except pairing.RateLimited:
            pass
    with pytest.raises(pairing.RateLimited):
        offers.begin(pairing.PROOF_SSH_FILE, tmp_path)
    assert offers.begin(pairing.PROOF_TYPED, tmp_path).nonce != typed.nonce
    assert ssh.nonce != typed.nonce


def test_both_kinds_stay_redeemable_side_by_side(tmp_path):
    offers = PairingOffers(clock=lambda: 0.0)
    typed = offers.begin(pairing.PROOF_TYPED, tmp_path)
    ssh = offers.begin(pairing.PROOF_SSH_FILE, tmp_path)
    assert offers.redeem(typed.nonce, typed.code).proof == pairing.PROOF_TYPED
    assert offers.redeem(ssh.nonce, ssh.code).proof == pairing.PROOF_SSH_FILE


@pytest.mark.parametrize("nonce_bad,code_bad", [(False, True), (True, True), (True, False)])
def test_non_ascii_nonce_or_code_is_a_401_never_a_500(macs, nonce_bad, code_bad):
    acceptor, initiator = macs
    offer = pairing.OFFERS.begin(pairing.PROOF_TYPED, acceptor.root)
    body = {"nonce": "éé" if nonce_bad else offer.nonce, "code": "éé" if code_bad else offer.code,
            "install_id": initiator.install_id, "label": "x", "public_key": fed_key.public_key_b64(initiator.key),
            "grant_id": "g", "protocol": 1}
    assert _client().post("/api/v1/federation/pair/complete", json=body).status_code == 401



def test_the_token_limit_is_per_grant_and_per_client_for_strangers(macs):
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    gid = answer["grant_id"]
    statuses = [_token(acceptor, initiator, client, gid, nonce=os.urandom(16)).status_code for _ in range(60)]
    assert set(statuses) == {200}
    assert _token(acceptor, initiator, client, gid).status_code == 429
    other = Mac(acceptor.root.parent / "c", 3)
    answer2, _ = _pair(acceptor, other, client)
    assert _token(acceptor, other, client, answer2["grant_id"]).status_code == 200
    stranger = [_token(acceptor, initiator, client, os.urandom(8).hex()).status_code for _ in range(21)]
    assert stranger[:20] == [401] * 20 and stranger[20] == 429
    assert _token(acceptor, initiator, _client(("192.168.1.50", 1)), os.urandom(8).hex()).status_code == 401



def test_a_claimed_install_id_cannot_swap_another_peers_grant(macs):
    acceptor, initiator = macs
    client = _client()
    first, _ = _pair(acceptor, initiator, client)
    thief = Mac(acceptor.root.parent / "c", 3)
    offer = pairing.OFFERS.begin(pairing.PROOF_TYPED, acceptor.root)
    claim = {"nonce": offer.nonce, "code": offer.code, "install_id": initiator.install_id, "label": "x",
             "public_key": fed_key.public_key_b64(thief.key), "grant_id": "g", "protocol": 1}
    refused = client.post("/api/v1/federation/pair/complete", json=claim)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "peer_identity_changed"
    with closing(acceptor.conn()) as c:
        live = grants.live_for_peer(c, initiator.install_id)
    assert live.grant_id == first["grant_id"] and live.public_key == fed_key.public_key_b64(initiator.key)
    offer = pairing.OFFERS.begin(pairing.PROOF_TYPED, acceptor.root)
    again = client.post("/api/v1/federation/pair/complete", json={
        **claim, "nonce": offer.nonce, "code": offer.code, "public_key": fed_key.public_key_b64(initiator.key)})
    assert again.status_code == 200 and again.json()["grant_id"] != first["grant_id"]
    accept = client.post("/api/v1/federation/pair/finish", json={"nonce": offer.nonce, "accept": True, "signature":
                         initiator.key.sign(pair_sas.finish_message(offer.nonce, True))})
    assert accept.status_code == 200
    app.dependency_overrides[require_auth] = lambda: True
    client.post(f"/api/v1/federation/pending-pairs/{offer.nonce}/confirm")
    with closing(acceptor.conn()) as c:
        assert grants.get_grant(c, first["grant_id"]).revoked



class FakeKeychain:

    def __init__(self) -> None:
        self.items = {}

    def read(self, service, account):
        v = self.items.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret, replace=True):
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


def test_staging_and_committing_a_rotation_touches_the_live_seed_only_at_commit():
    kc = FakeKeychain()
    svc = relay_keychain.FEDERATION_KEY_SERVICE
    kc.items[(svc, "iid")] = b64url(bytes([1]) * 32)
    new = fed_key.begin_rotation("iid", write=kc.write, read=kc.read)
    assert kc.items[(svc, "iid")] == b64url(bytes([1]) * 32) and (svc, "iid.next") in kc.items
    fed_key.commit_rotation("iid", read=kc.read, write=kc.write, delete=kc.delete)
    assert fed_key.load_key("iid", read=kc.read, write=kc.write).raw_pub == new.raw_pub
    assert (svc, "iid.next") not in kc.items
    with pytest.raises(fed_key.DeviceKeyUnavailable):
        fed_key.commit_rotation("iid", read=kc.read, write=kc.write, delete=kc.delete)


def test_a_retry_resumes_the_staged_key_instead_of_minting_another():
    kc = FakeKeychain()
    svc = relay_keychain.FEDERATION_KEY_SERVICE
    kc.items[(svc, "iid")] = b64url(bytes([1]) * 32)
    first = fed_key.begin_rotation("iid", write=kc.write, read=kc.read)
    again = fed_key.begin_rotation("iid", write=kc.write, read=kc.read)
    assert again.raw_pub == first.raw_pub


@pytest.mark.asyncio
async def test_a_second_rotation_while_one_runs_is_refused():
    import asyncio

    release = asyncio.Event()

    async def slow(**_kw):
        await release.wait()
        return {}

    original = key_rotate._rotate_locked
    key_rotate._rotate_locked = slow
    try:
        first = asyncio.create_task(key_rotate.rotate(install_id="iid", links=None, live_grants=0))
        await asyncio.sleep(0)
        with pytest.raises(key_rotate.RotationBusy):
            await key_rotate.rotate(install_id="iid", links=None, live_grants=0)
        release.set()
        await first
    finally:
        key_rotate._rotate_locked = original


class Links:

    def __init__(self, client) -> None:
        self._c, self.key = client, None

    def connected_clients(self):
        return [("peer-iid", self._c)]

    def use_key(self, key):
        self.key = key


class RouteClient:

    def __init__(self, acceptor, initiator, grant_id, http) -> None:
        self.acceptor, self.initiator, self.grant_id, self.http = acceptor, initiator, grant_id, http

    async def request(self, method, path, *, json=None):
        minted = _token(self.acceptor, self.initiator, self.http, self.grant_id).json()["token"]
        return self.http.request(method, f"/api/v1{path}", json=json, headers={"Authorization": f"Bearer {minted}"})


def _rotation_setup(macs, monkeypatch):
    acceptor, initiator = macs
    http = _client()
    answer, _ = _pair(acceptor, initiator, http)
    kc = FakeKeychain()
    svc = relay_keychain.FEDERATION_KEY_SERVICE
    kc.items[(svc, initiator.install_id)] = b64url(bytes([2]) * 32)
    monkeypatch.setattr(fed_key, "load_key", lambda iid: fed_key.load_or_create(
        iid, read=kc.read, write=kc.write, service=svc))
    real_begin, real_commit = fed_key.begin_rotation, fed_key.commit_rotation
    monkeypatch.setattr(fed_key, "begin_rotation", lambda iid: real_begin(iid, write=kc.write, read=kc.read))
    monkeypatch.setattr(fed_key, "commit_rotation", lambda iid: real_commit(
        iid, read=kc.read, write=kc.write, delete=kc.delete))
    return acceptor, initiator, http, answer["grant_id"], kc


@pytest.mark.asyncio
async def test_rotation_end_to_end_the_peer_swaps_on_the_old_keys_signature(macs, monkeypatch):
    acceptor, initiator, http, gid, kc = _rotation_setup(macs, monkeypatch)
    links = Links(RouteClient(acceptor, initiator, gid, http))
    result = await key_rotate.rotate(install_id=initiator.install_id, links=links, live_grants=1)
    assert result["announced"] == 1 and result["not_announced"] == 0
    new_key = fed_key.load_key(initiator.install_id)
    assert links.key.raw_pub == new_key.raw_pub != initiator.key.raw_pub
    assert result["fid"] == fed_key.fid_for(new_key.raw_pub)
    with closing(acceptor.conn()) as c:
        assert grants.get_live(c, gid).public_key == fed_key.public_key_b64(new_key)
    fresh = Mac(acceptor.root.parent / "d", 2)
    assert _token(acceptor, fresh, http, gid).status_code == 401
    now_new = SimpleNamespace(key=new_key, install_id=initiator.install_id)
    assert _token(acceptor, now_new, http, gid).status_code == 200


@pytest.mark.asyncio
async def test_the_peer_rejects_an_announcement_not_signed_by_the_pinned_key(macs, monkeypatch):
    acceptor, initiator, http, gid, _ = _rotation_setup(macs, monkeypatch)
    minted = _token(acceptor, initiator, http, gid).json()["token"]
    head = {"Authorization": f"Bearer {minted}"}
    new = fed_key.DeviceKey.from_seed(bytes([7]) * 32)
    wrong = fed_key.DeviceKey.from_seed(bytes([8]) * 32)
    for signer, receiver in ((wrong, gid), (initiator.key, "some-other-grant")):
        sig = signer.sign(key_rotate.announce_message(initiator.install_id, receiver, initiator.key.raw_pub, new.raw_pub))
        r = http.post("/api/v1/federation/key/announce", headers=head,
                      json={"new_public_key": fed_key.public_key_b64(new), "signature": sig})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "rotation_refused"
    with closing(acceptor.conn()) as c:
        assert grants.get_live(c, gid).public_key == fed_key.public_key_b64(initiator.key)


def test_rotate_is_owner_only_and_re_advertises_the_new_fid(macs, monkeypatch):
    acceptor, initiator, http, gid, kc = _rotation_setup(macs, monkeypatch)
    peer = _token(acceptor, initiator, http, gid).json()["token"]
    monkeypatch.setattr(federation_routes, "_install_id", lambda conn: initiator.install_id)
    assert http.post("/api/v1/federation/key/rotate", headers={"Authorization": f"Bearer {peer}"}).status_code == 401
    assert http.post("/api/v1/federation/key/rotate").status_code == 401
    told = []
    monkeypatch.setattr(app.state, "federation_discovery", SimpleNamespace(refresh_fid=told.append), raising=False)
    app.dependency_overrides[require_auth] = lambda: True
    r = http.post("/api/v1/federation/key/rotate")
    assert r.status_code == 200, r.text
    assert told == [r.json()["fid"]] and r.json()["announced"] == 0 and r.json()["not_announced"] == 1
