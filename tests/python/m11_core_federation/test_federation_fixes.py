
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import structlog

from src.core.federation import pairing, peer_event_stream, peer_http, peer_links, peer_terminal_proxy
from src.core.federation.peer_client import PeerClient, PeerRefused, Route
from src.core.federation.peer_token import NonceCache


class _ProbeDict(dict):

    def __init__(self) -> None:
        super().__init__()
        self.inside = 0
        self.max_inside = 0
        self._guard = threading.Lock()

    def _linger(self) -> None:
        with self._guard:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        time.sleep(0.03)
        with self._guard:
            self.inside -= 1

    def __contains__(self, key: object) -> bool:
        self._linger()
        return super().__contains__(key)

    def values(self) -> Any:
        self._linger()
        return super().values()


def _run_threads(target: Any, count: int = 4) -> None:
    threads = [threading.Thread(target=target) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_the_replay_cache_checks_and_inserts_atomically() -> None:
    cache = NonceCache()
    cache._seen = _ProbeDict()  # type: ignore[assignment]
    results: List[bool] = []
    _run_threads(lambda: results.append(cache.accept("g", "n", now=100.0)))
    assert results.count(True) == 1, "one signed (grant, nonce) pair may be accepted once, however many race"
    assert cache._seen.max_inside == 1  # type: ignore[attr-defined]


def test_the_pairing_offers_serialise_redeem_attempts() -> None:
    offers = pairing.PairingOffers()
    offers._offers = _ProbeDict()  # type: ignore[assignment]
    offers._offers["typed"] = pairing.Offer(nonce="abcd", proof="typed", expires=time.monotonic() + 60, _code="ZZZZ2345")

    def attempt() -> None:
        try:
            offers.redeem("abcd", "WRONG000")
        except pairing.PairError:
            pass

    _run_threads(attempt, 3)
    assert offers._offers.max_inside == 1  # type: ignore[attr-defined]


def test_a_status_line_with_no_space_is_a_value_error_not_an_index_error() -> None:
    with pytest.raises(ValueError):
        peer_http._status_of("garbage")
    with pytest.raises(ValueError):
        peer_http._status_of("NOTHTTP 200 OK")
    assert peer_http._status_of("HTTP/1.1 404 Not Found") == 404


def _client(reply: Any) -> PeerClient:
    client = PeerClient(Route("unix", "/x"), grant_id="g", peer_install_id="peer", sign=lambda m: "sig")

    async def send(*_a: Any, **_k: Any) -> Any:
        return reply

    client._send = send  # type: ignore[assignment]
    return client


class _Reply:
    def __init__(self, status: int, data: Any = None, bad_json: bool = False) -> None:
        self.status_code, self._data, self._bad = status, data, bad_json

    def json(self) -> Any:
        if self._bad:
            raise ValueError("not json")
        return self._data


@pytest.mark.parametrize("reply", [_Reply(200, bad_json=True), _Reply(200, {"install_id": "peer"}),
                                   _Reply(200, ["x"])])
def test_a_non_json_or_tokenless_token_answer_is_a_refusal(reply: _Reply) -> None:
    with pytest.raises(PeerRefused) as caught:
        asyncio.run(_client(reply)._mint())
    assert caught.value.code == "bad_answer"


def test_the_crown_path_encodes_the_name_and_client_id_and_survives_an_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: Dict[str, str] = {}

    class Client:
        async def request(self, method: str, path: str, json: Any = None) -> Any:
            seen["path"] = path
            return _Reply(404, bad_json=True)

    monkeypatch.setattr(peer_terminal_proxy, "_peer_client", lambda _key: Client())
    status, data = asyncio.run(peer_terminal_proxy.forward_crown("peer-ab", "a/b?c", "GET", "wire", client_id="x y&z=1"))
    assert seen["path"] == "/sessions/a%2Fb%3Fc/size-master?client_id=x+y%26z%3D1"
    assert (status, data) == (404, {})


def test_sync_restarts_a_follower_when_the_link_gets_a_new_client(monkeypatch: pytest.MonkeyPatch) -> None:
    started: List[Any] = []

    async def follow(_state: Any, _key: str, client: Any, _install_id: str, _open_db: Any) -> None:
        started.append(client)
        await asyncio.sleep(3600)

    connected = {"clients": []}  # type: Dict[str, list]
    monkeypatch.setattr(peer_event_stream, "_follow", follow)
    monkeypatch.setattr(peer_event_stream.peer_hosts, "get", lambda _c, iid: SimpleNamespace(key="peer-" + iid))
    monkeypatch.setattr(peer_event_stream.peer_links, "LINKS",
                        SimpleNamespace(connected_clients=lambda: list(connected["clients"])))

    class Conn:
        def close(self) -> None:
            pass

    async def scenario() -> None:
        first, second = object(), object()
        connected["clients"] = [("a", first)]
        peer_event_stream.sync(None, lambda: Conn())
        await asyncio.sleep(0)
        peer_event_stream.sync(None, lambda: Conn())
        await asyncio.sleep(0)
        assert started == [first]
        connected["clients"] = [("a", second)]
        peer_event_stream.sync(None, lambda: Conn())
        await asyncio.sleep(0)
        assert started == [first, second]
        await peer_event_stream.stop()

    asyncio.run(scenario())


def _links(open_db: Any) -> peer_links.PeerLinks:
    return peer_links.PeerLinks(open_db=open_db, listener_path="/x")


def test_link_state_writes_land_in_the_order_they_were_made(monkeypatch: pytest.MonkeyPatch) -> None:
    order: List[str] = []

    def set_state(_conn: Any, _iid: str, state: str, _protocol: Any) -> None:
        if state == "connecting":
            time.sleep(0.15)
        order.append(state)

    monkeypatch.setattr(peer_links.peer_hosts, "set_state", set_state)
    links = _links(lambda: sqlite3.connect(":memory:"))

    async def scenario() -> None:
        write = links._persist_state("peer-install-id")
        for state in ("connecting", "connected", "disconnected"):
            write(state, None)
        await asyncio.get_running_loop().run_in_executor(links._state_writer, lambda: None)

    asyncio.run(scenario())
    assert order == ["connecting", "connected", "disconnected"]


def test_a_failed_state_write_is_logged_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(peer_links.peer_hosts, "set_state", broken)
    links = _links(lambda: sqlite3.connect(":memory:"))
    with structlog.testing.capture_logs() as logs:
        links._write_state("peer-install-id", "connected", None)
    assert any(e["event"] == "peer_state_write_failed" and e["state"] == "connected"
               and e["error_type"] == "OperationalError" for e in logs)
