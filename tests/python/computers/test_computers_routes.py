
from __future__ import annotations

import json
import re
from contextlib import closing
from typing import List

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.python.computers.test_computers_runtime import _runtime
from tests.python.computers.test_join_commit import JOIN, MAIN, Side, _join_prov, _main_prov, world  # noqa: F401

# ruff: noqa: E402
from src.api import computers_routes, federation_routes
from src.api.auth import require_auth
from src.core import setup_state
from src.core.computers import commit, forget, membership, store
from src.core.computers.join_link import parse_link
from src.core.federation import grants, peer_hosts, peer_links, peer_sockets
from src.core.federation.pairing import KeyedWindows
from src.core.federation.peer_client import PeerUnreachable
from src.core.federation.peer_links import PeerLinks
from src.core.mcp import computers_tools, route_adapters as ra
from src.core.mcp.common import ToolError


async def _started(side: Side, monkeypatch, **kw):
    rt = _runtime(side, monkeypatch, **kw)
    monkeypatch.setattr(computers_routes, "_INVITE_WINDOW", KeyedWindows(6, 60.0))
    links = PeerLinks(open_db=side.open_db, listener_path=rt._listener_path)
    monkeypatch.setattr(peer_links, "LINKS", links)
    await rt.prepare(links)
    await rt.start()
    return rt


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(computers_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_invite_lifecycle_never_leaks_a_code_into_the_view(world, monkeypatch):
    main, _join = world
    rt = await _started(main, monkeypatch)
    try:
        async with _client() as c:
            made = await c.post("/api/v1/computers/invites")
            assert made.status_code == 201
            body = made.json()
            assert re.fullmatch(r"\d{6}", body["code"]) and body["addresses"] == ["air.local"]
            link = parse_link(body["link"])
            assert link is not None and link.invite_id == body["id"] and link.hosts == ["air.local"]
            assert rt.join_server.port == rt.link_port + 1
            view = (await c.get("/api/v1/computers")).json()
            text = json.dumps(view)
            assert body["code"] not in text and body["link"] not in text and link.secret.hex() not in text
            assert view["self"]["role"] == "standalone" and view["self"]["link"]["join_open"] is True
            assert view["invites"] == [{"id": body["id"], "kind": "code", "code_live": True, "expires_at": body["expires_at"], "attempts_left": 3}]
            again = (await c.get(f"/api/v1/computers/invites/{body['id']}")).json()
            assert again["code"] == body["code"] and again["link"] == body["link"]
            assert (await c.delete(f"/api/v1/computers/invites/{body['id']}")).json() == {"deleted": True}
            assert (await c.get(f"/api/v1/computers/invites/{body['id']}")).status_code == 404
            assert (await c.delete(f"/api/v1/computers/invites/{body['id']}")).status_code == 404
            await rt.join_server.sync()
            assert rt.join_server.port is None
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_invite_refusals(world, monkeypatch):
    main, _join = world
    rt = await _started(main, monkeypatch, complete=False)
    try:
        async with _client() as c:
            assert (await c.post("/api/v1/computers/invites")).json()["detail"]["code"] == "setup_incomplete"
        rt.complete = True
        monkeypatch.setattr(rt, "refresh_flags", lambda: setattr(rt, "complete", True))
        async with _client() as c:
            for _ in range(6):
                assert (await c.post("/api/v1/computers/invites")).status_code == 201
            assert len(rt.invites.live()) == 4
            assert (await c.post("/api/v1/computers/invites")).json()["detail"]["code"] == "invite_rate"
        rt.joined = True
        monkeypatch.setattr(rt, "refresh_flags", lambda: None)
        async with _client() as c:
            assert (await c.post("/api/v1/computers/invites")).json()["detail"]["code"] == "joined_computer"
    finally:
        await rt.stop()
    assert computers_routes.runtime.active() is None
    async with _client() as c:
        assert (await c.get("/api/v1/computers")).status_code == 503


@pytest.mark.asyncio
async def test_view_direction_and_remove_on_main(world, monkeypatch):
    main, join = world
    await _main_prov(main, join, "new")
    rt = await _started(main, monkeypatch)
    closed: List[str] = []

    async def close(grant_id: str) -> int:
        closed.append(grant_id)
        return 1

    monkeypatch.setattr(peer_sockets, "close_grant", close)
    try:
        async with _client() as c:
            view = (await c.get("/api/v1/computers")).json()
            assert view["self"]["role"] == "main" and view["self"]["link"]["state"] == "dialing"
            (entry,) = view["computers"]
            assert (entry["install_id"], entry["transport"], entry["role"], entry["state"], entry["direction"]) == (
                JOIN, "tls", "member", "waiting_first_link", "both")
            assert entry["dial"]["state"] in ("dialing", "unreachable") and "since" in entry["dial"]
            one = await c.put(f"/api/v1/computers/peers/{JOIN}/direction", json={"direction": "one_way"})
            assert one.json()["direction"] == "one_way" and len(closed) == 1
            assert main.query(lambda cn: store.get(cn, JOIN)).inbound_control == 0
            both = await c.put(f"/api/v1/computers/peers/{JOIN}/direction", json={"direction": "both"})
            assert both.json()["direction"] == "both" and len(closed) == 1
            assert (await c.put("/api/v1/computers/peers/nobody/direction", json={"direction": "both"})).status_code == 404
            assert (await c.put(f"/api/v1/computers/peers/{JOIN}/direction", json={"direction": "x"})).status_code == 422
            gone = await c.delete(f"/api/v1/computers/peers/{JOIN}")
            assert gone.json() == {"removed": True, "peer_told": False}
            assert (await c.delete(f"/api/v1/computers/peers/{JOIN}")).status_code == 404
        rows, gr, hosts = main.query(lambda cn: (store.list_rows(cn), grants.list_grants(cn), peer_hosts.list_peers(cn)))
        assert rows == [] and hosts == [] and all(g.revoked for g in gr) and rt.last_pins == () and rt.link_state == "stopped"
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_leave_cleans_a_member_and_a_non_member_is_refused(world, monkeypatch):
    main, join = world
    res = await _main_prov(main, join, "new")
    await _join_prov(main, join, res, "new")
    commit._write_marker(setup_state.joined_marker_path(join.config), MAIN, "2026-10-11T00:00:00Z")
    sentinel = join.config.parent / setup_state.PAIRED_SENTINEL_NAME
    sentinel.write_text("x")
    rt = await _started(join, monkeypatch, joined=True)
    own_files = f"link-{rt.iid[:12]}-*"
    assert list(join.dir.glob(own_files))
    try:
        async with _client() as c:
            view = (await c.get("/api/v1/computers")).json()
            assert view["self"]["role"] == "member" and view["self"]["main"]["label"] == "air" and view["self"]["link"]["state"] == "listening"
            done = await c.post("/api/v1/computers/leave")
            assert done.json() == {"left": True, "main_told": False}
            assert (await c.post("/api/v1/computers/leave")).json()["detail"]["code"] == "not_member"
        assert rt.member_listener.state == "stopped"
        assert not setup_state.joined_marker_path(join.config).exists() and not sentinel.exists()
        assert not list(join.dir.glob(own_files))
        assert join.pack.settings().master_install_id == rt.iid
        assert join.query(lambda cn: (store.list_rows(cn), peer_hosts.list_peers(cn))) == ([], [])
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_courtesy_counts_a_dropped_link_as_told_and_a_missing_link_as_not():
    class Client:
        def __init__(self, error=None):
            self.error = error

        async def request(self, method, path, **kw):
            assert (method, path) == ("DELETE", "/federation/grants/self")
            if self.error:
                raise self.error
            return type("R", (), {"status_code": 200})()

    class Links:
        def __init__(self, client):
            self._client = client

        def client(self, iid):
            return self._client

    assert await forget.tell_peer(Links(Client()), "x") is True
    assert await forget.tell_peer(Links(Client(PeerUnreachable("down"))), "x") is True
    assert await forget.tell_peer(Links(None), "x") is False


@pytest.mark.asyncio
async def test_removal_hook_drops_a_tls_row_and_ssh_pairing_is_refused(world, monkeypatch):
    main, join = world
    await _main_prov(main, join, "new")
    rt = await _started(main, monkeypatch)
    try:
        assert rt.link_state == "dialing"
        with pytest.raises(HTTPException) as err:
            federation_routes.refuse_tls_pairing(JOIN)
        assert err.value.status_code == 409 and err.value.detail["code"] == "computer_linked_tls"
        federation_routes.refuse_tls_pairing("some-ssh-peer")
        await membership.on_peer_removed(JOIN)
        assert main.query(lambda cn: store.list_rows(cn)) == [] and rt.link_state == "stopped"
        federation_routes.refuse_tls_pairing(JOIN)
        await membership.on_peer_removed(JOIN)
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_mcp_invite_result_carries_no_code_and_only_one_way_is_open():
    secret = {"id": "ab12cd34", "code": "123456", "link": "carnivore://join/v1?x", "expires_at": "2026-10-11T00:00:00Z", "attempts_left": 3}

    async def route(request):
        return secret

    result = await computers_tools._invite(ra.Call(route=route, request=None, args={}))
    assert result == {"id": "ab12cd34", "expires_at": "2026-10-11T00:00:00Z", "attempts_left": 3, "shown_on": computers_tools.SHOWN_ON}
    assert "123456" not in json.dumps(result) and "carnivore://" not in json.dumps(result)
    with pytest.raises(ToolError):
        computers_tools._direction(ra.Call(route=route, request=None, args={"computer": "x", "direction": "both"}))
    writes = set(computers_tools.WRITE_TOOLS)
    assert writes == {"computer_invite", "computer_remove", "computer_direction_set", "computer_leave", "computer_invite_delete", "computer_add"}
