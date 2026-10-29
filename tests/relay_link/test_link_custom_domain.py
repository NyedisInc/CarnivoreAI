
from __future__ import annotations

import time

import pytest

from relay import auth
from relay.phonelink import frames
from tests.relay_link.support import (
    Phone, client_hello, host_for, link_reauth, link_relay, tunnel, wait_online)
from tests.relay_v2_support import Device, Issuer

HOST = "sync.example.com"


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


def claim(host: str = HOST, va: int = 1000) -> list:
    return [{"h": host, "va": va}]


def until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


def test_claimed_name_routes_to_the_device(issuer):
    device = Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, cdom=claim()) as mac:
        Phone(port).send(client_hello(HOST))
        sid, opened, _ = mac.accept_stream()
        assert sid == 1 and opened["sni"] == HOST


def test_unclaimed_name_closes_silently(issuer):
    device = Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, cdom=claim()) as mac:
        phone = Phone(port).send(client_hello("other.example.com"))
        assert phone.is_closed()
        Phone(port).send(client_hello(HOST))
        assert mac.accept_stream()[0] == 1


def test_two_claims_resolve_to_the_newest_verified_binding(issuer):
    older, newer = Device(), Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, newer, issuer, cdom=claim(va=2000)) as mac_new, \
            tunnel(client, older, issuer, cdom=claim(va=1000)):
        Phone(port).send(client_hello(HOST))
        assert mac_new.accept_stream()[1]["sni"] == HOST
        assert client.app.state.link.custom_device(HOST) == newer.device_id


def test_tie_keeps_the_current_winner(issuer):
    first, second = Device(), Device()
    with link_relay(issuer) as (client, _port), \
            tunnel(client, first, issuer, cdom=claim(va=5)), \
            tunnel(client, second, issuer, cdom=claim(va=5)):
        assert client.app.state.link.custom_device(HOST) == first.device_id


def test_winner_leaving_hands_the_name_to_the_other_claim(issuer):
    older, newer = Device(), Device()
    with link_relay(issuer) as (client, _port), \
            tunnel(client, older, issuer, cdom=claim(va=1000)):
        with tunnel(client, newer, issuer, cdom=claim(va=2000)):
            assert client.app.state.link.custom_device(HOST) == newer.device_id
        until(lambda: client.app.state.link.custom_device(HOST) == older.device_id)
    until(lambda: client.app.state.link.custom_device(HOST) is None)


def test_reauth_without_the_claim_stops_routing(issuer):
    device = Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, cdom=claim()) as mac:
        assert client.app.state.link.custom_device(HOST) == device.device_id
        mac.send(frames.REAUTH, 0, link_reauth(device, issuer.token(device)))
        until(lambda: client.app.state.link.custom_device(HOST) is None)
        assert Phone(port).send(client_hello(HOST)).is_closed()


def test_reauth_moves_the_claim(issuer):
    device = Device()
    with link_relay(issuer) as (client, _port), \
            tunnel(client, device, issuer, cdom=claim()) as mac:
        mac.send(frames.REAUTH, 0, link_reauth(device, issuer.token(device, cdom=claim("b.example.org"))))
        until(lambda: client.app.state.link.custom_device("b.example.org") == device.device_id)
        assert client.app.state.link.custom_device(HOST) is None


def test_expired_token_closes_the_tunnel_and_drops_the_claim(issuer, monkeypatch):
    from relay import publish_v2
    monkeypatch.setattr(publish_v2, "REAUTH_GRACE_SECONDS", 0)
    device = Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, cdom=claim(), exp=int(time.time()) + 1):
        until(lambda: client.app.state.link.custom_device(HOST) is None, timeout=8)
        assert Phone(port).send(client_hello(HOST)).is_closed()


def test_link_name_routing_is_unchanged_with_a_claim(issuer):
    device = Device()
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, cdom=claim()) as mac:
        Phone(port).send(client_hello(host_for(device)))
        assert mac.accept_stream()[1]["sni"] == host_for(device)


@pytest.mark.parametrize("bad", [
    [], {}, "x", [{"h": HOST}], [{"h": HOST, "va": True}], [{"h": "UPPER.example.com", "va": 1}],
    [{"h": "nodot", "va": 1}], [{"h": "a" * 254 + ".com", "va": 1}],
    [{"h": HOST, "va": 1}, {"h": "b.example.com", "va": 2}], ["x"]])
def test_malformed_claim_refuses_the_token(issuer, bad):
    device = Device()
    with pytest.raises(auth.TokenRefused) as err:
        auth.verify_relay_token(issuer.token(device, cdom=bad), issuer.pins)
    assert str(err.value) == "malformed"


def test_own_zone_claim_is_ignored(issuer):
    device = Device()
    for host in ("carnivore.ai", "x.carnivore.ai", "a.link.carnivore.ai"):
        got = auth.verify_relay_token(issuer.token(device, cdom=claim(host)), issuer.pins)
        assert got.cdom is None
    assert auth.verify_relay_token(issuer.token(device), issuer.pins).cdom is None
