
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_p4_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_p4_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
from websockets.asyncio.server import serve, unix_serve  # noqa: E402

from src.api import peer_ws_auth  # noqa: E402
from src.api.websocket import router  # noqa: E402
from src.core.federation import peer_hosts, peer_links, peer_terminal_proxy as proxy  # noqa: E402
from src.core.federation.peer_client import Route  # noqa: E402
from tests.test_ws_subprotocol_auth import _mint_token, patched_auth_config  # noqa: E402,F401

INSTALL_ID = "iid-hosta-0001"
HOST_KEY = "peer-legacy"
STORED_KEY = HOST_KEY
assert HOST_KEY != peer_hosts.host_key_for(INSTALL_ID)
WIRE = f"remote:{HOST_KEY}:cloude_hosta_pane"
PEER_TOKEN = "PEER.TOKEN-never-reaches-the-browser"


class FakeOwner:

    def __init__(self, path: str, close_after=None, tcp: bool = False) -> None:
        self.path, self.close_after, self.tcp, self.port = path, close_after, tcp, 0
        self.seen: list = []
        self.request = None
        self._ready = threading.Event()
        self._stop: asyncio.Future
        threading.Thread(target=self._run, daemon=True).start()
        assert self._ready.wait(5)

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._stop = asyncio.get_running_loop().create_future()
        if self.tcp:
            async with serve(self._handle, "127.0.0.1", 0, subprotocols=["cloude.jwt.v1"]) as server:
                self.port = server.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop
            return
        async with unix_serve(self._handle, self.path, subprotocols=["cloude.jwt.v1"]):
            self._ready.set()
            await self._stop

    async def _handle(self, ws) -> None:
        self.request = ws.request
        await ws.send(json.dumps({"type": "request_dims"}))
        await ws.send(json.dumps({"type": "preferences.changed", "secret": "owner-only"}))
        await ws.send(json.dumps({"type": "toast.new", "toast": {}}))
        await ws.send(json.dumps({"type": "size_master", "session_id": "ses_owner_1", "master": None,
                                  "master_attached": False}))
        await ws.send(json.dumps({"type": "terminal.ready", "startup_command": "none"}))
        async for frame in ws:
            self.seen.append(frame)
            if isinstance(frame, bytes):
                await ws.send(b"echo:" + frame)
                if self.close_after is not None:
                    await ws.close(code=self.close_after)

    def stop(self) -> None:
        try:
            self._stop.get_loop().call_soon_threadsafe(self._stop.set_result, None)
        except RuntimeError:
            pass


class FakeClient:
    def __init__(self, path: str, port: int = 0) -> None:
        self.route = Route("tcp", port, "route-tag") if port else Route("unix", path)
        self.forced, self.proofs = [], 0

    async def proven_socket(self):
        import socket
        self.proofs += 1
        return socket.create_connection(("127.0.0.1", self.route.target))

    async def bearer(self, force: bool = False) -> str:
        self.forced.append(force)
        return PEER_TOKEN


@pytest.fixture()
def viewer(tmp_path, monkeypatch):
    sock = os.path.join(tempfile.mkdtemp(prefix="p4", dir="/tmp"), "o.sock")
    made: dict = {}

    def build(close_after=None, tcp: bool = False):
        made["owner"] = FakeOwner(sock, close_after, tcp)
        client = FakeClient(sock, made["owner"].port)
        monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(connected_clients=lambda: [(INSTALL_ID, client)]))
        monkeypatch.setattr(proxy.peer_auth, "open_db", lambda: SimpleNamespace(close=lambda: None))
        monkeypatch.setattr(proxy.peer_hosts, "get", lambda _conn, iid: SimpleNamespace(key=STORED_KEY) if iid == INSTALL_ID else None)
        app = FastAPI()
        app.include_router(router)
        app.state.session_manager = SimpleNamespace()
        app.state.services = SimpleNamespace(registry=SimpleNamespace(sessions={}))
        app.state.local_servers = SimpleNamespace()
        app.state.log_monitor = SimpleNamespace()
        made["client"] = client
        return TestClient(app), made["owner"], client

    yield build
    if "owner" in made:
        made["owner"].stop()


def _connect(tc: TestClient, query: str):
    return tc.websocket_connect(f"/ws/terminal?{query}", subprotocols=["cloude.jwt.v1", _mint_token()])


def test_keystrokes_reach_the_owner_and_output_returns_and_owner_only_frames_never_reach_the_browser(viewer) -> None:
    tc, owner, client = viewer()
    seen_text = []
    with _connect(tc, f"session_id={WIRE}&client_id=tab-abcdef123") as ws:
        while True:
            frame = ws.receive()
            if frame.get("text") is not None:
                seen_text.append(json.loads(frame["text"]))
                if seen_text[-1]["type"] == "terminal.ready":
                    break
        ws.send_text(json.dumps({"type": "pty_resize", "cols": 91, "rows": 33, "hidden": True, "evil": 1}))
        ws.send_text(json.dumps({"type": "size_master_admin", "x": 1}))
        ws.send_bytes(b"echo acceptance-163\r")
        assert ws.receive_bytes() == b"echo:echo acceptance-163\r"
    types = [m["type"] for m in seen_text]
    assert types == ["request_dims", "size_master", "terminal.ready"], types
    assert "preferences.changed" not in types and "toast.new" not in types
    assert [m for m in seen_text if m["type"] == "size_master"][0]["session_id"] == WIRE
    assert owner.seen == [json.dumps({"type": "pty_resize", "cols": 91, "rows": 33, "hidden": True}),
                          b"echo acceptance-163\r"]
    assert owner.request.path == "/ws/terminal?session_id=cloude_hosta_pane&client_id=tab-abcdef123"
    assert PEER_TOKEN in owner.request.headers["Sec-WebSocket-Protocol"]
    assert client.forced == [False]


def test_a_tcp_route_relays_over_the_connection_that_proved_the_key(viewer) -> None:
    tc, owner, client = viewer(tcp=True)
    with _connect(tc, f"session_id={WIRE}") as ws:
        while json.loads(ws.receive_text()).get("type") != "terminal.ready":
            pass
        ws.send_bytes(b"ls\r")
        assert ws.receive_bytes() == b"echo:ls\r"
    assert client.proofs == 1 and owner.seen == [b"ls\r"]


def test_the_peer_token_never_reaches_the_browser(viewer) -> None:
    tc, _, _ = viewer()
    with _connect(tc, f"session_id={WIRE}") as ws:
        blob = b""
        while True:
            frame = ws.receive()
            blob += (frame.get("text") or "").encode() + (frame.get("bytes") or b"")
            if b"terminal.ready" in blob:
                break
        assert ws.accepted_subprotocol == "cloude.jwt.v1"
    assert PEER_TOKEN.encode() not in blob


def test_a_revoke_and_a_lost_link_are_translated(viewer, tmp_path) -> None:
    tc, owner, _ = viewer(close_after=4412)
    with _connect(tc, f"session_id={WIRE}") as ws:
        while json.loads(ws.receive_text()).get("type") != "terminal.ready":
            pass
        ws.send_bytes(b"x")
        with pytest.raises(WebSocketDisconnect) as gone:
            while True:
                ws.receive_bytes()
    assert (gone.value.code, gone.value.reason) == (4412, "peer_revoked")
    owner.stop()
    import src.core.federation.peer_links as pl
    pl.LINKS = SimpleNamespace(connected_clients=lambda: [])
    with pytest.raises(WebSocketDisconnect) as down:
        with _connect(tc, f"session_id={WIRE}") as ws:
            ws.receive_text()
    assert (down.value.code, down.value.reason) == (4502, "peer_unavailable")


def test_the_close_codes_and_the_frame_filters_are_pure() -> None:
    assert proxy.close_for(4412) == (4412, "peer_revoked")
    assert proxy.close_for(None) == (4502, "peer_unavailable")
    assert proxy.close_for(1006) == (4502, "peer_unavailable")
    assert proxy.close_for(1000) == (1000, "")
    assert proxy.close_for(proxy.VIEWER_OVERFLOW_CLOSE_CODE)[0] == proxy.VIEWER_OVERFLOW_CLOSE_CODE
    for dropped in ("preferences.changed", "toast.new", "local_server_detected", "log", "session.renamed", "junk"):
        assert proxy.down_text(json.dumps({"type": dropped}), "w") is None
    assert proxy.down_text("not json", "w") is None
    assert proxy.up_text(json.dumps({"type": "preferences.changed"})) is None
    assert proxy.up_text(json.dumps({"type": "pty_resize", "cols": 1, "rows": 2, "x": 3})) == \
        json.dumps({"type": "pty_resize", "cols": 1, "rows": 2})
    assert proxy.up_text(json.dumps({"type": "repaint"})) == json.dumps({"type": "repaint"})
    assert proxy.up_text(" " * 5000) is None



def test_a_paired_mac_reaches_only_local_sessions_by_name_or_id() -> None:
    from src.core.hosts.remote_backend import RemoteTmuxBackend

    remote = RemoteTmuxBackend.__new__(RemoteTmuxBackend)
    backends = {"ses_a": SimpleNamespace(tmux_session="cloude_a"), "remote:hosta:x": remote}
    registry = SimpleNamespace(
        sessions=dict.fromkeys(backends), get_backend=backends.get,
        registered_ids_for_tmux_name=lambda name: [s for s, b in backends.items()
                                                   if getattr(b, "tmux_session", None) == name])
    assert peer_ws_auth.local_session_id(registry, "cloude_a") == "ses_a"
    assert peer_ws_auth.local_session_id(registry, "ses_a") == "ses_a"
    assert peer_ws_auth.local_session_id(registry, "remote:hosta:x") == peer_ws_auth.NOT_LOCAL
    assert peer_ws_auth.local_session_id(registry, None) == peer_ws_auth.NOT_LOCAL
    assert peer_ws_auth.local_session_id(registry, "nope") == peer_ws_auth.NOT_LOCAL


def test_the_owner_takes_a_live_peer_token_and_refuses_a_revoked_or_forged_one(tmp_path, monkeypatch) -> None:
    from contextlib import closing

    from src.api import peer_auth
    from src.core.db import connect, db_path_for, get_meta
    from src.core.db_migration import ensure_db_migrated
    from src.core.federation import fed_key, grants, peer_sockets, peer_token

    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        install_id = get_meta(conn, "install_id")
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer")
    token, _ = peer_token.mint(grant, install_id)
    app = FastAPI()
    app.include_router(router)
    app.state.session_manager = SimpleNamespace()
    app.state.services = SimpleNamespace(registry=SimpleNamespace(
        sessions={}, get_backend=lambda s: None, registered_ids_for_tmux_name=lambda n: []))
    app.state.local_servers = SimpleNamespace()
    app.state.log_monitor = SimpleNamespace()
    tc = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as gone:
        with tc.websocket_connect("/ws/terminal?session_id=remote:peer-x:y", subprotocols=["cloude.jwt.v1", token]) as ws:
            assert ws.accepted_subprotocol == "cloude.jwt.v1"
            ws.receive_text()
    assert gone.value.code == 4404
    assert peer_sockets.count(grant.grant_id) == 1
    with pytest.raises(WebSocketDisconnect) as forged:
        with tc.websocket_connect("/ws/terminal?session_id=a", subprotocols=["cloude.jwt.v1", token[:-3] + "abc"]):
            pass
    assert forged.value.code == 4401
    with closing(connect(path, create=False)) as conn:
        assert grants.revoke(conn, grant.grant_id)
    with pytest.raises(WebSocketDisconnect) as revoked:
        with tc.websocket_connect("/ws/terminal?session_id=a", subprotocols=["cloude.jwt.v1", token]):
            pass
    assert revoked.value.code == 4401


def test_a_keypad_arrow_for_the_id_the_session_answer_gives_reaches_the_owners_pane(viewer) -> None:
    from src.core.federation import peer_forward
    tc, owner, _ = viewer()
    answer = json.dumps({"session": {"id": "ses_owner_1"}, "tmux_session": "cloude_hosta_pane"}).encode()
    sid = json.loads(peer_forward.wire_session_reply(answer, HOST_KEY, "hosta", "cloude_hosta_pane"))["session"]["id"]
    assert sid == WIRE
    with _connect(tc, f"session_id={sid}") as ws:
        while json.loads(ws.receive_text()).get("type") != "terminal.ready":
            pass
        ws.send_bytes(b"\x1b[B")
        assert ws.receive_bytes() == b"echo:\x1b[B"
    assert owner.seen == [b"\x1b[B"]
