
from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from typing import Iterator

import pytest

from tests.relay_link.support import Phone, client_hello, host_for, link_relay, tunnel
from tests.relay_link.test_link_custom_domain import claim
from tests.relay_v2_support import Device, Issuer

FOREIGN = "dead.example.com"


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


class Sidecar:

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.received: list = []
        self.conns: list = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.conns.append(conn)
            data = conn.recv(65536)
            self.received.append(data)
            conn.sendall(b"SIDECAR")

    def close(self) -> None:
        self.server.close()
        for conn in self.conns:
            conn.close()


@contextmanager
def sidecar() -> Iterator[Sidecar]:
    box = Sidecar()
    try:
        yield box
    finally:
        box.close()


def test_foreign_unclaimed_name_is_piped_with_the_hello_first(issuer):
    hello = client_hello(FOREIGN)
    with sidecar() as box, link_relay(issuer, redirect_port=box.port) as (_client, port):
        phone = Phone(port).send(hello)
        assert phone.recv_exact(7) == b"SIDECAR"
        assert box.received == [hello]


def test_link_zone_and_carnivore_names_are_never_forwarded(issuer):
    with sidecar() as box, link_relay(issuer, redirect_port=box.port) as (_client, port):
        for name in ("a" * 26 + ".link.carnivore.ai", "api.carnivore.ai", "carnivore.ai"):
            assert Phone(port).send(client_hello(name)).is_closed()
        assert box.received == []


def test_claimed_live_name_goes_to_the_device_not_the_sidecar(issuer):
    device = Device()
    with sidecar() as box, link_relay(issuer, redirect_port=box.port) as (client, port), \
            tunnel(client, device, issuer, cdom=claim(FOREIGN)) as mac:
        Phone(port).send(client_hello(FOREIGN))
        assert mac.accept_stream()[1]["sni"] == FOREIGN
        assert box.received == []


def test_sidecar_down_closes_silently(issuer):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    free_port = dead.getsockname()[1]
    dead.close()
    with link_relay(issuer, redirect_port=free_port) as (_client, port):
        assert Phone(port).send(client_hello(FOREIGN)).is_closed()


def test_no_sidecar_configured_closes_silently(issuer):
    with link_relay(issuer) as (_client, port):
        assert Phone(port).send(client_hello(FOREIGN)).is_closed()


def test_forward_cap_is_enforced(issuer):
    hello = client_hello(FOREIGN)
    with sidecar() as box, link_relay(
            issuer, redirect_port=box.port, redirect_max_connections=1) as (_client, port):
        first = Phone(port).send(hello)
        assert first.recv_exact(7) == b"SIDECAR"
        assert Phone(port).send(hello).is_closed()
        assert box.received == [hello]


def test_config_reads_the_sidecar_port_and_cap(issuer):
    from relay.config import settings_from_env
    env = {"RELAY_PUBLISH_TOKEN": "t", "RELAY_LINK_ENABLED": "1",
           "CARNIVORE_RELAY_ISSUER_KEYS": ",".join(f"{k}:{v}" for k, v in
                                                   (p.split(":") for p in [issuer_pin(issuer)])),
           "RELAY_REDIRECT_PORT": "8444", "RELAY_REDIRECT_MAX_CONNECTIONS": "9"}
    got = settings_from_env(env)
    assert (got.redirect_port, got.redirect_max_connections) == (8444, 9)
    assert settings_from_env({**env, "RELAY_REDIRECT_PORT": ""}).redirect_port == 0


def issuer_pin(issuer: Issuer) -> str:
    kid, key = next(iter(issuer.pins.items()))
    from relay.auth import b64url
    return f"{kid}:{b64url(key)}"
