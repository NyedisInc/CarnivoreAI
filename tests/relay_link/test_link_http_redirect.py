
from __future__ import annotations

from tests.relay_link.support import Phone, client_hello, link_relay
from tests.relay_v2_support import Issuer


def http_port(client) -> int:
    return client.app.state.http_redirect.sockets[0].getsockname()[1]


def test_http_gets_308_to_https_same_host_and_path() -> None:
    with link_relay(Issuer(), http_port=0) as (client, tls_port):
        raw = Phone(http_port(client)).send(
            b"GET /pair?x=1 HTTP/1.1\r\nHost: Sync.Example.com:80\r\n\r\n")
        reply = raw.sock.recv(4096).decode()
        assert reply.startswith("HTTP/1.1 308 ")
        assert "Location: https://sync.example.com/pair?x=1\r\n" in reply
        tls = Phone(tls_port).send(client_hello("sync.example.com"))
        assert tls.is_closed()


def test_bad_host_is_closed_without_a_reply() -> None:
    with link_relay(Issuer(), http_port=0) as (client, _):
        for head in (b"GET / HTTP/1.1\r\nHost: a/b.example.com\r\n\r\n",
                     b"GET / HTTP/1.1\r\n\r\n"):
            assert Phone(http_port(client)).send(head).is_closed()
