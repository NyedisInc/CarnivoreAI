
from __future__ import annotations

import asyncio
import errno

import pytest
from fastapi import HTTPException

from src.api import messaging_routes
from src.core.messaging import client, events, stream
from src.core.notifications import http

NO_ROUTE = OSError(errno.EHOSTUNREACH, "No route to host")


def _client(monkeypatch, exc: Exception, url: str = "http://192.168.1.5:8787") -> client.HttpProviderClient:
    async def fake(method, u, **kw):
        raise exc

    monkeypatch.setattr(client.http, "guarded_request", fake)
    return client.HttpProviderClient("p_x", url, "tok", allow_private=True, allow_plain_http=True)


def _network_error(cause: OSError) -> http.GuardNetworkError:
    err = http.GuardNetworkError("oserror")
    err.__cause__ = cause
    return err


@pytest.mark.parametrize("url", ["http://192.168.1.5:8787", "http://10.0.0.9:1", "http://169.254.1.2:1"])
def test_ehostunreach_to_a_lan_address_says_local_network_and_keeps_the_code(monkeypatch, url):
    cli = _client(monkeypatch, _network_error(NO_ROUTE), url)
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.capabilities())
    assert exc.value.code == client.UNREACHABLE and exc.value.detail == client.LOCAL_NETWORK_DETAIL
    shown = messaging_routes._provider_down(exc.value).detail
    assert shown["code"] == "provider_unreachable" and shown["reason"] == client.LOCAL_NETWORK_DETAIL


def test_other_failures_and_public_hosts_get_no_hint(monkeypatch):
    refused = _network_error(OSError(errno.ECONNREFUSED, "refused"))
    for cli in (_client(monkeypatch, refused), _client(monkeypatch, _network_error(NO_ROUTE), "http://8.8.8.8:1"),
                _client(monkeypatch, _network_error(NO_ROUTE), "http://127.0.0.1:1"),
                _client(monkeypatch, http.GuardTimeout("timeout"))):
        with pytest.raises(client.ProviderError) as exc:
            asyncio.run(cli.capabilities())
        assert exc.value.code == client.UNREACHABLE and exc.value.detail is None


def test_a_hostname_is_resolved_best_effort(monkeypatch):
    monkeypatch.setattr(client.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("192.168.7.7", 0))])
    assert asyncio.run(client.local_network_hint(NO_ROUTE, "http://bridge.local:1")) == client.LOCAL_NETWORK_DETAIL

    def boom(host, port):
        raise OSError("nodename nor servname")

    monkeypatch.setattr(client.socket, "getaddrinfo", boom)
    assert asyncio.run(client.local_network_hint(NO_ROUTE, "http://bridge.local:1")) is None


def test_the_stream_records_the_hint_logs_it_once_and_the_view_shows_it(world, monkeypatch):
    state = world.rt.providers[world.pid]
    warnings = []
    monkeypatch.setattr(stream.log, "warning", lambda event, **kw: warnings.append(event))
    sleeps = []

    async def fake_sleep(_):
        sleeps.append(1)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    async def caps():
        raise client.ProviderError(client.UNREACHABLE, detail=client.LOCAL_NETWORK_DETAIL)

    state.client = type("C", (), {"capabilities": staticmethod(caps)})()
    monkeypatch.setattr(stream.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(stream.run_stream(world.rt, state))
    assert state.extra[events.DETAIL_KEY] == client.LOCAL_NETWORK_DETAIL
    assert warnings.count("messaging_stream_detail") == 1
    assert messaging_routes.provider_view(state.row, state)["stream"]["detail"] == client.LOCAL_NETWORK_DETAIL
