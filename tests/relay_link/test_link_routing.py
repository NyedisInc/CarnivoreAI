
from __future__ import annotations

import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from relay import publish_v2
from relay.bounded import REFUSED_CLOSE_CODE
from relay.phonelink import frames
from relay.phonelink.endpoint import LINK_SUBPROTOCOL
from relay.phonelink.tunnel import REPLACED_CLOSE_CODE, LinkLimits
from tests.relay_link.support import (
    DOMAIN, Phone, client_hello, host_for, link_headers, link_reauth, link_relay, ppv2,
    tunnel)
from tests.relay_v2_support import Device, Issuer
from tests.test_relay_sockets import PUBLISH_TOKEN

UNKNOWN = "a" * 26


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def device() -> Device:
    return Device()


def good_phone_gets_stream_one(port, device, mac) -> None:
    Phone(port).send(client_hello(host_for(device)))
    sid, opened, _ = mac.accept_stream()
    assert sid == 1 and opened["sni"] == host_for(device)




def test_bytes_round_trip_phone_to_fake_mac_and_back(issuer, device):
    hello = client_hello(host_for(device))
    with link_relay(issuer) as (client, port), tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(hello)
        sid, opened, first = mac.accept_stream()
        assert first == hello
        assert opened == {"client_ip": "127.0.0.1", "client_port": phone.sock.getsockname()[1],
                          "sni": host_for(device)}
        mac.send(frames.DATA, sid, b"server-bytes")
        assert phone.recv_exact(12) == b"server-bytes"
        kind, wsid, payload = mac.frame()
        assert (kind, wsid, frames.window_credit(payload)) == (frames.WINDOW, sid, 12)
        phone.send(b"app-bytes")
        assert mac.frame() == (frames.DATA, sid, b"app-bytes")
        mac.send(frames.CLOSE, sid, bytes([frames.REASON_NORMAL]))
        assert phone.is_closed()
        assert mac.frame()[:2] == (frames.CLOSE, sid)


def test_round_trip_behind_a_load_balancer_reads_the_client_from_the_header(issuer, device):
    with link_relay(issuer, link_proxy_protocol="required") as (client, port), \
            tunnel(client, device, issuer) as mac:
        Phone(port).send(ppv2("198.51.100.7", 4242) + client_hello(host_for(device)))
        _sid, opened, _ = mac.accept_stream()
        assert (opened["client_ip"], opened["client_port"]) == ("198.51.100.7", 4242)
        Phone(port).send(ppv2("2001:db8::7", 99) + client_hello(host_for(device)))
        assert mac.accept_stream()[1]["client_ip"] == "2001:db8::7"


def test_phone_eof_reaches_the_mac_and_the_stream_ends_when_the_mac_answers(issuer, device):
    with link_relay(issuer) as (client, port), tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(client_hello(host_for(device)))
        sid, _, _ = mac.accept_stream()
        phone.sock.shutdown(1)
        assert mac.frame()[:2] == (frames.CLOSE, sid)
        mac.send(frames.CLOSE, sid, bytes([frames.REASON_NORMAL]))
        assert phone.is_closed()



DIRECT_BAD = {
    "unknown device": lambda d: client_hello(f"{UNKNOWN}.{DOMAIN}"),
    "wrong domain": lambda d: client_hello(f"{d.device_id}.example.com"),
    "no sni": lambda d: client_hello(None),
    "not tls": lambda d: b"GET / HTTP/1.1\r\n\r\n",
    "proxy header when none expected": lambda d: ppv2() + client_hello(host_for(d)),
    "oversize hello": lambda d: b"\x16\x03\x01" + (20000).to_bytes(2, "big") + b"x" * 100,
    "sni with a dot dot": lambda d: client_hello(f"{d.device_id}..{DOMAIN}"),
}


@pytest.mark.parametrize("name", sorted(DIRECT_BAD))
def test_router_closes_bad_connections_silently(issuer, device, name):
    with link_relay(issuer) as (client, port), tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(DIRECT_BAD[name](device))
        assert phone.is_closed()
        good_phone_gets_stream_one(port, device, mac)


def test_router_closes_a_slow_hello(issuer, device):
    with link_relay(issuer, LinkLimits(hello_timeout=0.3)) as (client, port), \
            tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(client_hello(host_for(device))[:7])
        assert phone.is_closed()
        good_phone_gets_stream_one(port, device, mac)


def test_router_refuses_an_offline_device(issuer, device):
    with link_relay(issuer) as (_client, port):
        assert Phone(port).send(client_hello(host_for(device))).is_closed()


PROXY_BAD = {
    "no header": lambda d: client_hello(host_for(d)),
    "bad signature": lambda d: b"\r\n\r\n\x00\r\nQUIX" + bytes(4) + client_hello(host_for(d)),
    "bad version": lambda d: ppv2()[:12] + bytes([0x11, 0x11]) + ppv2()[14:] + client_hello(host_for(d)),
    "oversize body": lambda d: ppv2()[:14] + (4000).to_bytes(2, "big") + b"x" * 4000,
    "unknown command": lambda d: ppv2()[:12] + bytes([0x23, 0x11]) + ppv2()[14:] + client_hello(host_for(d)),
    "unsupported family": lambda d: ppv2()[:13] + bytes([0x31]) + ppv2()[14:] + client_hello(host_for(d)),
    "local (a health check)": lambda d: ppv2(command=0) + client_hello(host_for(d)),
}


@pytest.mark.parametrize("name", sorted(PROXY_BAD))
def test_router_in_required_mode_refuses_missing_or_malformed_proxy_headers(issuer, device, name):
    with link_relay(issuer, link_proxy_protocol="required") as (client, port), \
            tunnel(client, device, issuer) as mac:
        assert Phone(port).send(PROXY_BAD[name](device)).is_closed()
        Phone(port).send(ppv2() + client_hello(host_for(device)))
        assert mac.accept_stream()[0] == 1


def test_a_truncated_proxy_header_is_closed_quietly(issuer, device):
    with link_relay(issuer, LinkLimits(hello_timeout=0.3), link_proxy_protocol="required") \
            as (client, port), tunnel(client, device, issuer):
        assert Phone(port).send(ppv2()[:10]).is_closed()




def test_one_address_cannot_burn_the_device_budget(issuer, device):
    limits = LinkLimits(max_streams_per_ip=2, opens_per_ip_per_second=1000)
    with link_relay(issuer, limits, link_proxy_protocol="required") as (client, port), \
            tunnel(client, device, issuer) as mac:
        hello = client_hello(host_for(device))
        held = [Phone(port).send(ppv2("203.0.113.5", 1) + hello) for _ in range(2)]
        assert [mac.accept_stream()[0] for _ in held] == [1, 2]
        assert Phone(port).send(ppv2("203.0.113.5", 2) + hello).is_closed()
        Phone(port).send(ppv2("203.0.113.6", 1) + hello)
        assert mac.accept_stream()[0] == 3


def test_one_address_is_rate_limited_on_new_connections(issuer, device):
    limits = LinkLimits(max_streams_per_ip=100, opens_per_ip_per_second=1, ip_burst=1)
    with link_relay(issuer, limits) as (client, port), tunnel(client, device, issuer) as mac:
        hello = client_hello(host_for(device))
        Phone(port).send(hello)
        assert mac.accept_stream()[0] == 1
        assert Phone(port).send(hello).is_closed()


def test_device_stream_and_open_rate_caps(issuer, device):
    with link_relay(issuer, LinkLimits(max_streams=1, max_streams_per_ip=100,
                                       opens_per_ip_per_second=1000)) as (client, port), \
            tunnel(client, device, issuer) as mac:
        hello = client_hello(host_for(device))
        Phone(port).send(hello)
        assert mac.accept_stream()[0] == 1
        assert Phone(port).send(hello).is_closed()
    with link_relay(issuer, LinkLimits(opens_per_second=1, opens_burst=1, max_streams_per_ip=100,
                                       opens_per_ip_per_second=1000)) as (client, port), \
            tunnel(client, device, issuer) as mac:
        Phone(port).send(hello)
        assert mac.accept_stream()[0] == 1
        assert Phone(port).send(hello).is_closed()


def test_idle_stream_is_closed(issuer, device):
    with link_relay(issuer, LinkLimits(idle_seconds=0.3)) as (client, port), \
            tunnel(client, device, issuer) as mac:
        phone = Phone(port).send(client_hello(host_for(device)))
        sid, _, _ = mac.accept_stream()
        assert mac.frame() == (frames.CLOSE, sid, bytes([frames.REASON_IDLE]))
        assert phone.is_closed()




def refused(client, headers, subprotocols=(LINK_SUBPROTOCOL,)) -> None:
    with pytest.raises(WebSocketDisconnect) as gone:
        with client.websocket_connect("/v1/link/tunnel", headers=headers,
                                      subprotocols=list(subprotocols)):
            pass
    assert gone.value.code == REFUSED_CLOSE_CODE


def test_tunnel_refuses_every_bad_credential(issuer, device):
    with link_relay(issuer) as (client, _port):
        token = issuer.token(device)
        refused(client, {"authorization": "Bearer garbage"})
        refused(client, {})
        refused(client, {"authorization": f"Bearer {PUBLISH_TOKEN}"})
        refused(client, device.headers(token))
        stranger = Device()
        refused(client, link_headers(stranger, token))
        refused(client, link_headers(device, token, ts=int(time.time()) - 600))
        refused(client, link_headers(device, issuer.token(device, exp=int(time.time()) - 500)))
        refused(client, link_headers(device, token), subprotocols=())
        assert client.app.state.link.online(device.device_id) is None


def test_a_replayed_handshake_is_refused(issuer, device):
    with link_relay(issuer) as (client, _port):
        headers = link_headers(device, issuer.token(device))
        with client.websocket_connect("/v1/link/tunnel", headers=headers,
                                      subprotocols=[LINK_SUBPROTOCOL]):
            refused(client, headers)


def test_tunnel_is_refused_when_link_mode_is_off(issuer, device):
    with link_relay(issuer, link_enabled=False) as (client, _port):
        refused(client, link_headers(device, issuer.token(device)))


def test_newest_tunnel_per_device_wins_and_the_old_one_closes_4409(issuer, device):
    with link_relay(issuer) as (client, port), tunnel(client, device, issuer) as old:
        with tunnel(client, device, issuer) as new:
            with pytest.raises(WebSocketDisconnect) as gone:
                old.frame()
            assert gone.value.code == REPLACED_CLOSE_CODE
            Phone(port).send(client_hello(host_for(device)))
            assert new.accept_stream()[0] == 1




@pytest.fixture
def no_grace(monkeypatch):
    monkeypatch.setattr(publish_v2, "REAUTH_GRACE_SECONDS", 0)


def test_tunnel_without_reauth_closes_4440_at_expiry(issuer, device, no_grace):
    with link_relay(issuer) as (client, _port), \
            tunnel(client, device, issuer, exp=int(time.time()) + 1) as mac:
        with pytest.raises(WebSocketDisconnect) as gone:
            mac.frame()
        assert gone.value.code == publish_v2.EXPIRED_CLOSE_CODE


def test_reauth_extends_the_tunnel_without_disturbing_streams(issuer, device, no_grace):
    with link_relay(issuer) as (client, port), \
            tunnel(client, device, issuer, exp=int(time.time()) + 1) as mac:
        phone = Phone(port).send(client_hello(host_for(device)))
        sid, _, _ = mac.accept_stream()
        mac.send(frames.REAUTH, 0, link_reauth(device, issuer.token(device)))
        time.sleep(2.5)
        mac.send(frames.DATA, sid, b"still-here")
        assert phone.recv_exact(10) == b"still-here"
        Phone(port).send(client_hello(host_for(device)))
        assert mac.frame()[0] == frames.WINDOW
        assert mac.accept_stream()[0] == 2


def test_a_bad_reauth_does_not_extend_the_tunnel(issuer, device, no_grace):
    with link_relay(issuer) as (client, _port), \
            tunnel(client, device, issuer, exp=int(time.time()) + 1) as mac:
        wrong = link_reauth(device, issuer.token(device), audience=b"relay.carnivore.ai/publish")
        mac.send(frames.REAUTH, 0, wrong)
        mac.send(frames.REAUTH, 0, b"not json")
        with pytest.raises(WebSocketDisconnect) as gone:
            mac.frame()
        assert gone.value.code == publish_v2.EXPIRED_CLOSE_CODE


def test_protocol_violations_close_the_tunnel_4400(issuer, device):
    with link_relay(issuer) as (client, _port), tunnel(client, device, issuer) as mac:
        mac.send(frames.OPEN, 5, json.dumps({}).encode())
        with pytest.raises(WebSocketDisconnect) as gone:
            mac.frame()
        assert gone.value.code == 4400
