
from __future__ import annotations

from contextlib import closing

import pytest

from tests.python.federation.test_pairing_routes import Mac, _client, _ssh_begin, macs  # noqa: F401

# ruff: noqa: E402
from src.api import federation_peer_routes, peer_auth, federation_routes  # noqa: F401
from src.api.auth import require_auth
from src.core.federation import fed_key, grants, pair_driver, pair_sas, pairing, peer_links
from src.main import app

API = "/api/v1/federation"


def _pub(mac: Mac) -> bytes:
    return mac.key.raw_pub


def _complete(acceptor: Mac, initiator_key, initiator_iid: str, client, *, typed: bool):
    if typed:
        offer = pairing.OFFERS.begin(pairing.PROOF_TYPED, acceptor.root)
        nonce, code = offer.nonce, offer.code
    else:
        nonce = _ssh_begin(acceptor)
        code = (acceptor.root / "federation" / f"pair-{nonce}").read_text().strip()
    done = client.post(f"{API}/pair/complete", json={
        "nonce": nonce, "code": code, "install_id": initiator_iid, "label": "initiator",
        "public_key": fed_key.public_key_b64(initiator_key), "grant_id": "g" * 32, "protocol": 1})
    assert done.status_code == 200, done.text
    return nonce, done


def _finish(client, key, nonce, accept):
    return client.post(f"{API}/pair/finish", json={"nonce": nonce, "accept": accept,
                                                   "signature": key.sign(pair_sas.finish_message(nonce, accept))})


def _grant_for(acceptor: Mac, install_id: str):
    with closing(acceptor.conn()) as c:
        return grants.live_for_peer(c, install_id)


def test_both_sides_compute_the_same_value_in_either_order():
    a, b = fed_key.DeviceKey.from_seed(b"\x01" * 32).raw_pub, fed_key.DeviceKey.from_seed(b"\x02" * 32).raw_pub
    assert pair_sas.compute_sas(a, b, "n1") == pair_sas.compute_sas(b, a, "n1")
    assert pair_sas.compute_sas(a, b, "n1") != pair_sas.compute_sas(a, b, "n2")
    digits = pair_sas.compute_sas(a, b, "n1").replace(" ", "")
    assert len(digits) == pair_sas.SAS_DIGITS and digits.isdigit()


def test_the_acceptor_screen_shows_the_value_the_initiator_computes(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=True)
    app.dependency_overrides[require_auth] = lambda: True
    (shown,) = client.get(f"{API}/pending-pairs").json()
    assert shown["nonce"] == nonce and shown["proof"] == "typed"
    assert shown["sas"] == pair_sas.compute_sas(_pub(initiator), _pub(acceptor), nonce)


def test_a_man_in_the_middle_with_its_own_key_gets_a_different_value_on_each_screen(macs):
    acceptor, initiator = macs
    mitm = fed_key.DeviceKey.from_seed(b"\x09" * 32)
    client = _client()
    nonce, done = _complete(acceptor, mitm, initiator.install_id, client, typed=True)
    app.dependency_overrides[require_auth] = lambda: True
    on_acceptor = client.get(f"{API}/pending-pairs").json()[0]["sas"]
    on_initiator = pair_sas.compute_sas(_pub(initiator), mitm.raw_pub, nonce)
    assert on_acceptor != on_initiator
    assert done.json()["public_key"] == fed_key.public_key_b64(acceptor.key)


def test_no_grant_is_active_before_the_confirmation_and_a_typed_pairing_needs_both_owners(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=True)
    assert _grant_for(acceptor, initiator.install_id) is None
    assert _finish(client, initiator.key, nonce, True).json() == {"state": "awaiting_owner"}
    assert _grant_for(acceptor, initiator.install_id) is None
    app.dependency_overrides[require_auth] = lambda: True
    assert client.post(f"{API}/pending-pairs/{nonce}/confirm").json() == {"state": "active"}
    assert _grant_for(acceptor, initiator.install_id) is not None


def test_a_typed_pairing_the_owner_alone_confirmed_still_waits_for_the_initiator(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=True)
    app.dependency_overrides[require_auth] = lambda: True
    assert client.post(f"{API}/pending-pairs/{nonce}/confirm").json() == {"state": "awaiting_initiator"}
    assert _grant_for(acceptor, initiator.install_id) is None


def test_a_zero_typing_pairing_activates_on_the_signed_accept_alone(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=False)
    forged = _finish(client, fed_key.DeviceKey.from_seed(b"\x09" * 32), nonce, True)
    assert forged.status_code == 404 and _grant_for(acceptor, initiator.install_id) is None
    assert _finish(client, initiator.key, nonce, True).json() == {"state": "active"}
    assert _grant_for(acceptor, initiator.install_id) is not None


def test_a_cancel_from_either_side_drops_the_pairing_and_nothing_is_granted(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=False)
    assert _finish(client, initiator.key, nonce, False).json() == {"state": "cancelled"}
    assert _finish(client, initiator.key, nonce, True).status_code == 404
    assert _grant_for(acceptor, initiator.install_id) is None
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=True)
    app.dependency_overrides[require_auth] = lambda: True
    assert client.post(f"{API}/pending-pairs/{nonce}/cancel").json() == {"cancelled": True}
    assert client.get(f"{API}/pending-pairs").json() == []
    assert _finish(client, initiator.key, nonce, True).status_code == 404


def test_the_pending_routes_are_owner_only(macs):
    acceptor, initiator = macs
    client = _client()
    nonce, _ = _complete(acceptor, initiator.key, initiator.install_id, client, typed=True)
    app.dependency_overrides.pop(require_auth, None)
    assert client.get(f"{API}/pending-pairs").status_code == 401
    assert client.post(f"{API}/pending-pairs/{nonce}/confirm").status_code == 401
    assert client.post(f"{API}/pending-pairs/{nonce}/cancel").status_code == 401
    assert _grant_for(acceptor, initiator.install_id) is None


def test_a_pending_pairing_expires():
    clock = [0.0]
    store = pair_sas.PendingPairs(clock=lambda: clock[0])
    store.add("n", proof="typed", sas="1", label="", fid="")
    assert store.get("n") is not None
    clock[0] += pair_sas.PENDING_TTL_SECONDS + 1
    assert store.get("n") is None


class _Links:

    def __init__(self, key) -> None:
        self.key, self.started = key, []

    async def _signer(self):
        return self.key

    async def start_initiator(self, row):
        self.started.append(row.peer_install_id)

    _listener = "/tmp/x.sock"

    def state(self, _iid):
        return "connecting"


class _Transport:
    back_kind = "unix"

    async def close(self):
        pass


async def _held(initiator: Mac, acceptor: Mac, monkeypatch, *, match_calls):
    links = _Links(initiator.key)
    monkeypatch.setattr(peer_links, "LINKS", links)
    monkeypatch.setattr(peer_auth, "open_db", initiator.conn)
    monkeypatch.setattr(pair_sas, "INITIATING", pair_sas.PendingPairs())
    monkeypatch.setattr(federation_peer_routes, "_transport", lambda *a: _Transport())

    async def finish(*, transport, key, nonce, accept):
        match_calls.append(accept)
        return "active"

    monkeypatch.setattr(pair_driver, "finish", finish)
    answer = {"install_id": acceptor.install_id, "public_key": fed_key.public_key_b64(acceptor.key),
              "fid": fed_key.fid_for(acceptor.key.raw_pub), "grant_id": "theirs", "label": "acc", "protocol": 1}
    pending = pair_driver.PairPending("nn", "typed", answer, "mine", pair_sas.compute_sas(_pub(initiator), _pub(acceptor), "nn"))
    from src.core.hosts.ssh_exec import SshDestination
    pair_sas.INITIATING.add("nn", proof="typed", sas=pending.sas, label="acc", fid=answer["fid"], pending=pending,
                            dest=SshDestination("studio"), remote_port=8000, same_user=True)
    return links


@pytest.mark.asyncio
async def test_they_differ_drops_the_initiators_pairing_tells_the_peer_and_writes_no_grant(macs, monkeypatch):
    acceptor, initiator = macs
    calls: list = []
    await _held(initiator, acceptor, monkeypatch, match_calls=calls)
    out = await federation_peer_routes.pair_confirm(federation_peer_routes.ConfirmRequest(nonce="nn", match=False))
    assert out == {"cancelled": True} and calls == [False]
    assert pair_sas.INITIATING.get("nn") is None
    with closing(initiator.conn()) as c:
        assert grants.live_for_peer(c, acceptor.install_id) is None


@pytest.mark.asyncio
async def test_they_match_tells_the_peer_writes_our_grant_and_starts_the_link(macs, monkeypatch):
    acceptor, initiator = macs
    calls: list = []
    links = await _held(initiator, acceptor, monkeypatch, match_calls=calls)
    out = await federation_peer_routes.pair_confirm(federation_peer_routes.ConfirmRequest(nonce="nn", match=True))
    assert calls == [True] and out["peer_install_id"] == acceptor.install_id and links.started == [acceptor.install_id]
    with closing(initiator.conn()) as c:
        assert grants.live_for_peer(c, acceptor.install_id).grant_id == "mine"
