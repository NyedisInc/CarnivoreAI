
from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from starlette.websockets import WebSocketDisconnect

from src.api import federation_routes, peer_auth
from src.core.computers import direction, store
from src.core.computers.store import LinkRow
from src.core.pack.machines import exchange as pack_exchange
from tests.python.federation.test_pairing_routes import _client, _pair, _token, macs  # noqa: F401

SESSIONS = "/api/v1/sessions/list"


@pytest.fixture()
def paired(macs):  # noqa: F811
    acceptor, initiator = macs
    client = _client()
    answer, _ = _pair(acceptor, initiator, client)
    token = _token(acceptor, initiator, client, answer["grant_id"]).json()["token"]
    yield acceptor, initiator, client, {"Authorization": f"Bearer {token}"}, token
    store.CACHE.replace([])
    direction.note_restrictions("main", None)


def _set(acceptor, initiator, inbound: bool) -> None:
    with closing(acceptor.conn()) as conn:
        store.set_direction(conn, initiator.install_id, inbound)


def _code(response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return ""
    return detail.get("code") if isinstance(detail, dict) else ""


def test_one_way_computer_is_refused_on_sessions_but_keeps_hello_and_exchange(paired):
    acceptor, initiator, client, bearer, _ = paired
    assert _code(client.get(SESSIONS, headers=bearer)) != direction.REFUSAL_CODE
    _set(acceptor, initiator, False)
    refused = client.get(SESSIONS, headers=bearer)
    assert refused.status_code == 403 and _code(refused) == direction.REFUSAL_CODE
    hello = client.get("/api/v1/federation/hello", headers=bearer)
    assert hello.status_code == 200 and hello.json()["restrictions_for_caller"] == ["one_way"]
    assert "one_way" not in hello.json()["capabilities"]
    exchange = client.post("/api/v1/federation/pack/exchange", headers=bearer, json={})
    assert _code(exchange) != direction.REFUSAL_CODE
    _set(acceptor, initiator, True)
    assert client.get("/api/v1/federation/hello", headers=bearer).json()["restrictions_for_caller"] == []
    assert _code(client.get(SESSIONS, headers=bearer)) != direction.REFUSAL_CODE


def test_ssh_peer_with_no_row_and_a_missing_table_are_unaffected(paired):
    acceptor, initiator, client, bearer, _ = paired
    assert _code(client.get(SESSIONS, headers=bearer)) != direction.REFUSAL_CODE
    with closing(acceptor.conn()) as conn:
        conn.execute("DROP TABLE computer_links")
        conn.commit()
    assert _code(client.get(SESSIONS, headers=bearer)) != direction.REFUSAL_CODE


def test_a_database_error_answers_503_never_waves_the_computer_through(paired, monkeypatch):
    _, _, client, bearer, _ = paired

    def broken(_conn, _iid):
        raise sqlite3.DatabaseError("disk image is malformed")

    monkeypatch.setattr(store, "get", broken)
    refused = client.get(SESSIONS, headers=bearer)
    assert refused.status_code == 503 and _code(refused) == "computer_direction_unknown"


def test_one_way_computer_opens_no_terminal_socket(paired):
    acceptor, initiator, client, _, token = paired
    _set(acceptor, initiator, False)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/terminal?session_id=x", subprotocols=["cloude.jwt.v1", token]):
            pass
    assert closed.value.code == 4401


def test_link_refuses_a_tcp_back_route_from_a_tls_member(paired):
    acceptor, initiator, client, bearer, _ = paired
    body = {"kind": "tcp", "port": 43000, "route_id": "r" * 32}
    assert _code(client.post("/api/v1/federation/link", headers=bearer, json=body)) != "link_tcp_refused"
    with closing(acceptor.conn()) as conn:
        store.put(conn, LinkRow(initiator.install_id, "member", "tls", "new"))
    refused = client.post("/api/v1/federation/link", headers=bearer, json=body)
    assert refused.status_code == 403 and _code(refused) == "link_tcp_refused"


def test_pack_hooks_read_the_same_flag(paired):
    acceptor, initiator, *_ = paired
    iid = initiator.install_id
    assert direction.contained(iid) is False
    _set(acceptor, initiator, False)
    assert direction.contained(iid) is True
    ran = []
    runtime = type("R", (), {"settings": lambda self: ran.append("settings")})()
    assert pack_exchange.PackMachines._merge_remote(runtime, {"any": "doc"}, iid) is False
    assert ran == []
    _set(acceptor, initiator, True)
    assert direction.contained(iid) is False


def test_member_skips_a_main_that_calls_it_one_way():
    assert direction.is_one_way_toward("main") is False
    direction.note_restrictions("main", ["one_way"])
    assert direction.is_one_way_toward("main") is True
    direction.note_restrictions("main", "garbage")
    assert direction.is_one_way_toward("main") is False
