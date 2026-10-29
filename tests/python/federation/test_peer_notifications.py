
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest
import pytest_asyncio

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fed_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fed_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import events_routes, peer_auth  # noqa: E402
from src.core import event_hub  # noqa: E402
from src.core.db import connect, db_path_for, get_meta  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants, peer_event_stream, peer_events, peer_token  # noqa: E402
from src.core.notifications import contracts  # noqa: E402
from tests.python.notifications.engine_fakes import ev  # noqa: E402
from tests.python.notifications.test_engine import Rig  # noqa: E402
from src.main import app  # noqa: E402

HOST = "peer-ab12"
TOAST = {"type": "toast.new", "toast": {"id": "t1", "session_id": "ses_1", "session_name": "carnivore_api",
                                        "kind": "PermissionRequest", "title": "needs you", "body": "run ls?"}}
STATUS = {"type": "session.status", "session_id": "ses_1", "tmux_session": "carnivore_api",
          "activity_status": "question", "unread": True}


def test_translate_addresses_the_wire_id_and_marks_origin_peer() -> None:
    status = peer_event_stream.translate(STATUS, HOST)
    assert status["session_id"] == f"remote:{HOST}:carnivore_api" and status["origin"] == "peer"
    assert status["activity_status"] == "question" and status["unread"] is True
    toast = peer_event_stream.translate(TOAST, HOST)
    assert toast["origin"] == "peer" and toast["toast"]["session_id"] == f"remote:{HOST}:carnivore_api"
    assert toast["toast"]["id"] == "t1"
    assert peer_event_stream.translate({"type": "events.hello"}, HOST)["type"] == "sessions.changed"
    assert peer_event_stream.translate({"type": "preferences.changed"}, HOST) is None
    assert peer_event_stream.translate({"type": "session.status", "session_id": "ses_1"}, HOST) is None


def test_the_owner_sends_a_paired_mac_only_status_and_toasts_for_its_own_sessions() -> None:
    ok = events_routes.peer_may_receive
    assert ok(json.dumps(STATUS)) and ok(json.dumps(TOAST)) and ok('{"type": "pong"}')
    assert not ok('{"type": "preferences.changed"}') and not ok("not json") and not ok("[]")
    assert not ok(json.dumps({**STATUS, "session_id": "remote:studio:x"}))
    assert not ok(json.dumps({"type": "toast.new", "toast": {"session_id": "remote:studio:x"}}))


@pytest.fixture()
def peer_bearer(tmp_path, monkeypatch) -> str:
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        install_id = get_meta(conn, "install_id")
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer")
    return peer_token.mint(grant, install_id)[0]


def test_a_peer_token_opens_the_owners_events_socket_and_gets_only_its_notices(peer_bearer, monkeypatch) -> None:
    hub = event_hub.EventHub()
    monkeypatch.setattr(app.state, "event_hub", hub, raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    with client.websocket_connect("/ws/events", subprotocols=["cloude.jwt.v1", peer_bearer]) as ws:
        assert json.loads(ws.receive_text())["type"] == "events.hello"
        hub.publish({"type": "preferences.changed", "secret": "no"})
        hub.publish(TOAST)
        assert json.loads(ws.receive_text())["type"] == "toast.new"


class _Upstream:

    def __init__(self, frames) -> None:
        self._frames, self.closed = frames, False

    def __aiter__(self):
        async def gen():
            assert HOST in peer_event_stream.LIVE
            for frame in self._frames:
                yield json.dumps(frame)
        return gen()

    async def close(self) -> None:
        self.closed = True


def _viewer_state():
    hub = event_hub.EventHub()
    return SimpleNamespace(event_hub=hub), hub


@pytest.mark.asyncio
async def test_the_follower_re_raises_owner_notices_with_origin_peer_and_frees_the_poll_after(monkeypatch) -> None:
    state, hub = _viewer_state()
    seen = hub.register()
    upstream = _Upstream([{"type": "events.hello"}, STATUS, TOAST, {"type": "preferences.changed"}])

    async def connect(_client, _url):
        return upstream

    monkeypatch.setattr(peer_event_stream, "connect_upstream", connect)
    await peer_event_stream._follow_once(state, HOST, SimpleNamespace(), "iid", None)
    frames = [json.loads(await asyncio.wait_for(seen.stream.get(), 1)) for _ in range(3)]
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(seen.stream.get(), 0.1)
    assert [f["type"] for f in frames] == ["sessions.changed", "session.status", "toast.new"]
    assert all(f.get("origin", "peer") == "peer" for f in frames)
    assert upstream.closed and HOST not in peer_event_stream.LIVE


def test_the_poll_stays_quiet_for_a_live_peer_and_drives_a_peer_with_no_subscription(monkeypatch) -> None:
    lights = {"type": "session.status", "session_id": f"remote:{HOST}:x"}
    other = {"type": "session.status", "session_id": "remote:peer-other:y"}
    structural = {"type": "sessions.changed", "reason": "peer"}
    monkeypatch.setattr(peer_event_stream, "LIVE", {HOST})
    assert peer_events._drop_live_lights([lights, other, structural]) == [other, structural]


@pytest_asyncio.fixture()
async def rig():
    r = Rig([_dest()])
    await r.engine.start()
    contracts.install_sink(r.engine.offer)
    try:
        yield r
    finally:
        contracts.uninstall_sink()
        await r.engine.stop()


def _dest():
    from tests.python.notifications.engine_fakes import dest
    return dest(1, reminder_minutes=0)


@pytest.mark.asyncio
async def test_a_peer_notice_is_refused_by_the_real_engine(rig) -> None:
    peer_event_stream.offer_to_engine(peer_event_stream.translate(TOAST, HOST))
    await asyncio.sleep(0.05)
    await rig.engine.join()
    assert rig.sender.calls == []


@pytest.mark.asyncio
async def test_the_count_can_see_a_push_when_the_event_is_local(rig) -> None:
    contracts.emit(ev("session.permission"))
    await asyncio.sleep(0.05)
    await rig.engine.join()
    assert len(rig.sender.calls) == 1
